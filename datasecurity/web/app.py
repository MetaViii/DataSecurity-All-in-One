from __future__ import annotations

import re
import csv
import io
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)
from starlette.middleware.trustedhost import TrustedHostMiddleware

from datasecurity import __version__
from datasecurity.core.pipeline import Pipeline

from .jobs import JobManager
from .workspace import SUPPORTED, Workspace
from .plugin_manager import PluginManager


def create_app(root: Path | str | None = None, *, frontend_dir: Path | None = None) -> FastAPI:
    workspace = Workspace(Path(root or Path.cwd()))
    jobs = JobManager(workspace)
    plugins = PluginManager(workspace)
    token = secrets.token_urlsafe(32)
    static = (frontend_dir or Path(__file__).resolve().parents[2] / "frontend" / "dist").resolve()

    @asynccontextmanager
    async def lifespan(app):
        yield
        jobs.close()

    app = FastAPI(title="DataSecurity Local API", version=__version__, lifespan=lifespan)
    app.state.workspace = workspace
    app.state.jobs = jobs
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Workspace-Token"],
    )

    @app.middleware("http")
    async def protect_writes(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "DELETE"}:
            if not secrets.compare_digest(request.headers.get("x-workspace-token", ""), token):
                return JSONResponse({"error": "会话已变化，请刷新页面后重试"}, status_code=403)
            origin = request.headers.get("origin")
            if origin:
                parsed = urlparse(origin)
                dev = origin in {"http://127.0.0.1:5173", "http://localhost:5173"}
                same = (
                    parsed.netloc == request.headers.get("host")
                    and parsed.scheme == request.url.scheme
                )
                if not (dev or same):
                    return JSONResponse({"error": "不接受跨站写入请求"}, status_code=403)
            limit = (
                128 * 1024 * 1024 + 1024 * 1024
                if request.url.path == "/api/files"
                else 2 * 1024 * 1024
            )
            try:
                too_large = int(request.headers.get("content-length", "0")) > limit
            except ValueError:
                return JSONResponse({"error": "无效的 Content-Length"}, status_code=400)
            if too_large:
                return JSONResponse({"error": "请求过大"}, status_code=413)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=422)

    @app.exception_handler(FileNotFoundError)
    async def missing(request, exc):
        return JSONResponse({"error": "文件或项目不存在"}, status_code=404)

    @app.exception_handler(KeyError)
    async def missing_key(request, exc):
        return JSONResponse({"error": str(exc).strip("'")}, status_code=404)

    @app.get("/api/bootstrap")
    def bootstrap():
        return {
            "token": token,
            "version": __version__,
            "workspace": str(workspace.root),
            "plugins": workspace.registry.describe(),
            "plugin_errors": workspace.registry.load_errors,
            "files": workspace.files(),
            "projects": workspace.list_projects(),
            "templates": workspace.templates(),
        }

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.post("/api/plugins/reload")
    def reload_plugins():
        try:
            with jobs.edit_plugins():
                workspace.reload_plugins()
                return plugins.describe()
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/plugins/manage")
    def manage_plugins():
        return plugins.describe()

    @app.post("/api/plugins/install")
    def install_plugin(payload: dict = Body(...)):
        try:
            with jobs.edit_plugins():
                return plugins.install(payload)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/plugins/toggle")
    def toggle_plugin(payload: dict = Body(...)):
        try:
            with jobs.edit_plugins():
                return plugins.toggle(payload)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/files")
    def list_files():
        return workspace.files()

    @app.post("/api/files")
    async def upload(file: UploadFile = File(...)):
        filename = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", Path(file.filename or "upload").name)[:100]
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED:
            raise HTTPException(415, "支持 CSV、TSV、JSON、JSONL、TXT、LOG 和 XLSX")
        path = workspace.uploads / f"{uuid.uuid4().hex[:12]}_{filename}"
        temporary = path.with_suffix(path.suffix + ".part")
        total = 0
        try:
            with temporary.open("wb") as handle:
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > 128 * 1024 * 1024:
                        raise HTTPException(413, "单个文件最多 128 MiB")
                    handle.write(chunk)
            temporary.replace(path)
        finally:
            await file.close()
            temporary.unlink(missing_ok=True)
        return workspace.inspect_file(path)

    @app.get("/api/projects")
    def projects():
        return workspace.list_projects()

    @app.post("/api/projects")
    def save_project(payload: dict = Body(...)):
        return workspace.save_project(payload)

    @app.get("/api/projects/{project_id}")
    def load_project(project_id: str):
        return workspace.load_project(project_id)

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: str):
        workspace.project_path(project_id).unlink()
        return {"ok": True}

    @app.post("/api/validate")
    def validate(payload: dict = Body(...)):
        definition = payload.get("definition")
        if not isinstance(definition, dict):
            raise ValueError("definition 必须是对象")
        prepared = jobs.prepare(definition, "validate")
        plan = Pipeline(workspace.registry).plan(prepared)
        return {"valid": True, "order": [step.id for step in plan]}

    @app.post("/api/runs")
    def start_run(payload: dict = Body(...)):
        preview, target = payload.get("preview", True), payload.get("target")
        if type(preview) is not bool or (target is not None and not isinstance(target, str)):
            raise ValueError("preview 必须是布尔值，target 必须是节点 ID")
        return jobs.start(payload.get("definition"), preview=preview, target=target)

    @app.get("/api/runs/{job_id}")
    def job_status(job_id: str):
        return jobs.snapshot(job_id)

    @app.post("/api/runs/{job_id}/cancel")
    def cancel_job(job_id: str):
        return jobs.cancel(job_id)

    @app.get("/api/runs/{job_id}/table")
    def table(
        job_id: str,
        node: str,
        port: str,
        view: str = Query("output", pattern="^(input|output)$"),
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=500),
        q: str = "",
    ):
        return jobs.table(job_id, node, port, view=view, page=page, page_size=page_size, query=q)

    @app.get("/api/runs/{job_id}/artifacts/{filename}")
    def artifact(job_id: str, filename: str):
        job = jobs.get(job_id)
        if not job.result:
            raise HTTPException(404, "尚无导出结果")
        path = next(
            (
                path
                for path in job.result.context.output_paths
                if path.name == filename and path.is_file()
            ),
            None,
        )
        if path is None or not path.is_relative_to(workspace.exports):
            raise HTTPException(404, "文件不存在")
        return FileResponse(path, filename=path.name)

    @app.get("/api/runs/{job_id}/table.csv")
    def export_table(
        job_id: str, node: str, port: str, view: str = Query("output", pattern="^(input|output)$")
    ):
        table = jobs.result_table(job_id, node, port, view=view)

        def content():
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow(table.columns)
            yield buffer.getvalue().encode("utf-8")
            for index, record in enumerate(table.records):
                buffer.seek(0)
                buffer.truncate(0)
                writer.writerow([record.values[field] for field in table.columns])
                yield buffer.getvalue().encode("utf-8")

        return StreamingResponse(
            content(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="branch.csv"',
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/docs/{name}", response_class=PlainTextResponse)
    def document(name: str):
        documents = {
            "code-tour": "code-tour.md",
            "plugins": "plugin-development.md",
            "nodes": "node-catalog.md",
            "architecture": "architecture.md",
            "recipes": "ctf-recipes.md",
            "workbench": "workbench-guide.md",
            "plugin-manager": "plugin-manager.md",
            "advanced-nodes": "advanced-nodes.md",
            "real-ctf": "real-ctf.md",
            "contest-round2": "contest-round2.md",
            "correction": "correction.md",
        }
        if name not in documents:
            raise HTTPException(404)
        return (Path(__file__).resolve().parents[2] / "docs" / documents[name]).read_text(
            encoding="utf-8"
        )

    @app.get("/api/{path:path}")
    def unknown_api(path: str):
        raise HTTPException(404, "接口不存在")

    @app.get("/{asset:path}")
    def frontend(asset: str):
        path = (static / asset).resolve()
        if not path.is_relative_to(static):
            raise HTTPException(404)
        if path.is_file():
            return FileResponse(
                path, headers={"Cache-Control": "no-cache"} if path.name == "index.html" else None
            )
        index = static / "index.html"
        if not index.is_file():
            return HTMLResponse(
                "<h1>前端尚未构建</h1><p>请在 frontend 目录执行 npm ci 和 npm run build，然后刷新。</p>",
                status_code=503,
            )
        if asset and "." in Path(asset).name:
            raise HTTPException(404)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app
