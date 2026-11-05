from __future__ import annotations

import copy
import re
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, RLock

from datasecurity.core.errors import ExecutionError
from datasecurity.core.pipeline import Pipeline, RunResult

from .workspace import Workspace


@dataclass
class Job:
    id: str
    definition: dict
    preview: bool
    target: str | None
    status: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    cancel: Event = field(default_factory=Event)
    steps: list[dict] = field(default_factory=list)
    current_node: str | None = None
    completed: int = 0
    total: int = 0
    error: str | None = None
    error_node: str | None = None
    result: RunResult | None = None


class JobManager:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self._jobs: dict[str, Job] = {}
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="datasecurity")

    def close(self):
        with self._lock:
            for job in self._jobs.values():
                job.cancel.set()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def prepare(self, definition, job_id):
        if not isinstance(definition, dict):
            raise ValueError("definition 必须是对象")
        result = copy.deepcopy(definition)
        if not isinstance(result.get("nodes"), list):
            raise ValueError("nodes 必须是数组")
        if result.get("plugin_dirs"):
            raise ValueError(
                "Web 模式的插件目录由服务管理，请移除流程中的 plugin_dirs；本地 plugins 目录已自动加载"
            )
        for node in result.get("nodes", []):
            if not isinstance(node, dict):
                raise ValueError("节点必须是对象")
            if not isinstance(node.get("plugin"), str):
                raise ValueError("节点缺少 plugin")
            if not isinstance(node.get("config", {}), dict):
                raise ValueError("config 必须是对象")
            plugin = self.workspace.registry.get(node.get("plugin", ""))
            if plugin.spec.kind == "output" and "path" in node.get("config", {}):
                value = node["config"]["path"]
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("输出文件名不能为空")
                filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(value).name).strip(" .")
                if not filename:
                    raise ValueError("输出文件名无效")
                node["config"]["path"] = f"work/exports/{job_id}/{filename}"
                # Each run owns a new directory; it never needs to replace an
                # existing output from an earlier run.
                if any(parameter.name == "overwrite" for parameter in plugin.spec.parameters):
                    node["config"]["overwrite"] = False
        return result

    def start(self, definition, *, preview=True, target=None):
        with self._lock:
            return self._start(definition, preview=preview, target=target)

    @contextmanager
    def edit_plugins(self):
        # Use the same lock as task submission, so no run can slip between the
        # active-task check and the registry swap.
        with self._lock:
            if any(job.status in {"queued", "running"} for job in self._jobs.values()):
                raise RuntimeError("流程运行中，请等待或取消任务后再修改插件")
            yield

    def _start(self, definition, *, preview=True, target=None):
        if not isinstance(definition, dict):
            raise ValueError("definition 必须是对象")
        if target is not None and not preview:
            raise ValueError("正式运行不能只指定一个节点")
        job_id = uuid.uuid4().hex
        registry = self.workspace.registry
        pipeline = Pipeline(registry)
        prepared = self.prepare(pipeline.scope(definition, target), job_id)
        plan = pipeline.plan(prepared)
        output_paths = [
            step.config.get("path")
            for step in plan
            if step.plugin.spec.kind == "output" and step.config.get("path")
        ]
        if len(set(output_paths)) != len(output_paths):
            raise ValueError("同一次运行的输出文件名不能重复")
        job = Job(job_id, prepared, preview, target, total=len(plan))
        with self._lock:
            active = [item for item in self._jobs.values() if item.status in {"queued", "running"}]
            if len(active) >= 3:
                raise ValueError("已有 3 个活动任务，请等待或取消后再运行")
            completed = [
                key for key, item in self._jobs.items() if item.status not in {"queued", "running"}
            ]
            for key in completed[:-3]:
                self._jobs.pop(key)
            self._jobs[job.id] = job
        self._executor.submit(self._execute, job, pipeline)
        return self.snapshot(job.id)

    def _execute(self, job, pipeline):
        def on_step(step):
            with self._lock:
                job.current_node = step["id"]
                job.completed, job.total = step["completed"], step["total"]
                if step["status"] != "running":
                    job.steps.append(step)

        with self._lock:
            job.status = "running"
        try:
            result = pipeline.run(
                job.definition,
                base_dir=self.workspace.root,
                preview=job.preview,
                target=job.target,
                workspace_root=self.workspace.root,
                cancel_event=job.cancel,
                on_step=on_step,
            )
            with self._lock:
                job.result = result
                job.status = "success"
        except InterruptedError:
            with self._lock:
                job.status = "cancelled"
        except Exception as exc:
            with self._lock:
                job.status = "error"
                job.error = str(exc)
                if isinstance(exc, ExecutionError):
                    job.result = exc.partial_result
                    job.error_node = exc.node_id

    def get(self, job_id):
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError("运行记录不存在或已从内存释放")
            return self._jobs[job_id]

    def snapshot(self, job_id):
        with self._lock:
            job = self.get(job_id)
            nodes = []
            if job.result:
                for node, ports in job.result.tables.items():
                    nodes.append(
                        {
                            "id": node,
                            "ports": {
                                port: {"rows": len(table), "columns": list(table.columns)}
                                for port, table in ports.items()
                            },
                        }
                    )
            artifacts = []
            if job.result:
                for path in sorted(job.result.context.output_paths):
                    if path.is_file():
                        artifacts.append(
                            {
                                "name": path.name,
                                "size": path.stat().st_size,
                                "url": f"/api/runs/{job.id}/artifacts/{path.name}",
                            }
                        )
            return {
                "id": job.id,
                "status": job.status,
                "preview": job.preview,
                "target": job.target,
                "created_at": job.created_at,
                "current_node": job.current_node,
                "completed": job.completed,
                "total": job.total,
                "steps": list(job.steps),
                "error": job.error,
                "error_node": job.error_node,
                "nodes": nodes,
                "artifacts": artifacts,
            }

    def cancel(self, job_id):
        job = self.get(job_id)
        job.cancel.set()
        return self.snapshot(job_id)

    def result_table(self, job_id, node_id, port, *, view="output"):
        job = self.get(job_id)
        if job.result is None:
            raise ValueError("该任务尚无可预览的结果")
        if view == "input":
            definition = next(
                (item for item in job.definition["nodes"] if item["id"] == node_id), None
            )
            if not definition or port not in definition.get("inputs", {}):
                raise ValueError("找不到该输入端口")
            node_id, port = definition["inputs"][port].split(":", 1)
        table = job.result.tables.get(node_id, {}).get(port)
        if table is None:
            raise ValueError("这个节点端口尚未产生结果")
        return table

    def table(self, job_id, node_id, port, *, view="output", page=1, page_size=50, query=""):
        table = self.result_table(job_id, node_id, port, view=view)
        records = table.records
        if query:
            needle = query.casefold()
            records = tuple(
                record
                for record in records
                if any(needle in value.casefold() for value in record.values.values())
            )
        page_size = min(max(page_size, 1), 500)
        page = max(page, 1)
        pages = max(1, (len(records) + page_size - 1) // page_size)
        page = min(page, pages)
        selected = records[(page - 1) * page_size : page * page_size]
        return {
            "columns": list(table.columns),
            "row_count": len(table),
            "filtered_count": len(records),
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "rows": [
                {"values": dict(record.values), **record.diagnostics()} for record in selected
            ],
        }
