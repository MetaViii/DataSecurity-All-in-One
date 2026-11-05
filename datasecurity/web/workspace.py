from __future__ import annotations

import csv
import json
import re
import uuid
from zipfile import BadZipFile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from datasecurity.builtin import create_registry
from datasecurity.builtin._files import atomic_text

SUPPORTED = {
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".ndjson",
    ".txt",
    ".log",
    ".xlsx",
    ".pcap",
    ".pcapng",
}


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.uploads = self.root / "work" / "uploads"
        self.projects = self.root / "work" / "projects"
        self.exports = self.root / "work" / "exports"
        for path in (self.uploads, self.projects, self.exports):
            path.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.reload_plugins()

    def reload_plugins(self):
        registry = create_registry()
        directory = self.root / "plugins"
        if directory.is_dir():
            registry.discover(directory)
        with self._lock:
            self.registry = registry
        return registry

    def path(self, value: str) -> Path:
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("文件必须位于工作区内")
        return path

    def inspect_file(self, path: Path) -> dict:
        result = {
            "name": path.name,
            "path": path.relative_to(self.root).as_posix(),
            "size": path.stat().st_size,
            "extension": path.suffix.lower(),
            "columns": [],
        }
        suffix = path.suffix.lower()
        result["reader"] = (
            "pcap.http"
            if suffix in {".pcap", ".pcapng"}
            else (
                "xlsx.read"
                if suffix == ".xlsx"
                else (
                    "json.read"
                    if suffix in {".json", ".jsonl", ".ndjson"}
                    else "text.read" if suffix in {".txt", ".log"} else "csv.read"
                )
            )
        )
        try:
            if suffix in {".pcap", ".pcapng"}:
                from datasecurity.builtin.extraction import HTTP_COLUMNS

                result["columns"] = list(HTTP_COLUMNS)
                result["note"] = "读取明文HTTP正文，需要本机TShark；TLS不解密"
            elif suffix in {".csv", ".tsv"}:
                for encoding in ("utf-8-sig", "gbk"):
                    try:
                        with path.open(encoding=encoding, newline="") as handle:
                            result["columns"] = next(
                                csv.reader(handle, delimiter="\t" if suffix == ".tsv" else ","), []
                            )
                        result["encoding"] = encoding
                        break
                    except UnicodeError:
                        continue
            elif suffix == ".xlsx":
                from openpyxl import load_workbook

                workbook = load_workbook(path, read_only=True, data_only=False)
                try:
                    result["sheets"] = workbook.sheetnames
                    result["columns"] = [
                        "" if value is None else str(value)
                        for value in next(workbook.worksheets[0].iter_rows(values_only=True), [])
                    ]
                finally:
                    workbook.close()
            elif suffix in {".txt", ".log"}:
                result["columns"] = ["行号", "内容"]
            elif suffix in {".jsonl", ".ndjson"}:
                with path.open(encoding="utf-8-sig") as handle:
                    value = next((json.loads(line) for line in handle if line.strip()), {})
                if isinstance(value, dict):
                    result["columns"] = list(value)
            elif suffix == ".json" and result["size"] < 1024 * 1024:
                value = json.loads(path.read_text(encoding="utf-8-sig"))
                first = value[0] if isinstance(value, list) and value else value
                if isinstance(first, dict):
                    result["columns"] = list(first)
        except (ValueError, OSError, csv.Error, KeyError, BadZipFile, EOFError):
            result["note"] = "无法快速读取表头，请配置参数后预览"
        return result

    def files(self):
        result = []
        for directory in (self.root / "examples" / "data", self.uploads):
            if not directory.exists():
                continue
            for path in sorted(directory.iterdir()):
                if (
                    path.is_file()
                    and path.suffix.lower() in SUPPORTED
                    and path.resolve().is_relative_to(self.root)
                ):
                    result.append(self.inspect_file(path))
        return result

    def list_projects(self):
        projects = []
        with self._lock:
            for path in self.projects.glob("*.json"):
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    projects.append(
                        {key: value[key] for key in ("id", "name", "updated_at", "revision")}
                    )
                except (ValueError, KeyError):
                    continue
        return sorted(projects, key=lambda item: item["updated_at"], reverse=True)

    def project_path(self, project_id):
        if not isinstance(project_id, str) or not re.fullmatch(r"[0-9a-f]{32}", project_id):
            raise ValueError("无效的项目 ID")
        return self.projects / f"{project_id}.json"

    def load_project(self, project_id):
        with self._lock:
            return json.loads(self.project_path(project_id).read_text(encoding="utf-8"))

    def save_project(self, payload):
        definition = payload.get("definition")
        if (
            not isinstance(definition, dict)
            or definition.get("version") != 1
            or not isinstance(definition.get("nodes"), list)
        ):
            raise ValueError("项目必须包含 version=1 的流程定义")
        name = str(payload.get("name", "未命名流程")).strip()[:100] or "未命名流程"
        project_id = payload.get("id") or uuid.uuid4().hex
        path = self.project_path(project_id)
        with self._lock:
            old = self.load_project(project_id) if path.exists() else None
            if old and payload.get("revision") != old["revision"]:
                raise ValueError("项目已在其他窗口更新，请重新打开后保存，或另存为新项目")
            result = {
                "id": project_id,
                "name": name,
                "definition": definition,
                "revision": old["revision"] + 1 if old else 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            with atomic_text(path, encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2)
        return result

    def templates(self):
        templates = []
        catalog = [
            ("clean_people", "人员数据清洗", "校验格式、条件筛选与异常分流"),
            (
                "generic_cleaning",
                "通用清洗与统计",
                "文本整理、组合校验、计算、去重、排序与分组统计",
            ),
        ]
        for path in sorted((self.root / "examples").glob("ctf_*.json")):
            definition = json.loads(path.read_text(encoding="utf-8"))
            catalog.append(
                (
                    path.stem,
                    definition.get("name", path.stem),
                    definition.get("description", "公开规则演练，使用虚构样本"),
                )
            )
        for key, name, description in catalog:
            path = self.root / "examples" / f"{key}.json"
            if not path.exists():
                continue
            definition = json.loads(path.read_text(encoding="utf-8"))
            definition["name"] = name
            for node in definition["nodes"]:
                plugin = self.registry.get(node["plugin"])
                for parameter in plugin.spec.parameters:
                    value = node.get("config", {}).get(parameter.name)
                    if isinstance(value, str) and parameter.widget in {
                        "input_file",
                        "input_file_template",
                    }:
                        node["config"][parameter.name] = (
                            self.path(str(Path("examples") / value))
                            .relative_to(self.root)
                            .as_posix()
                        )
                if plugin.spec.kind == "output" and "path" in node["config"]:
                    node["config"]["path"] = Path(node["config"]["path"]).name
            templates.append(
                {"id": key, "name": name, "description": description, "definition": definition}
            )
        return templates
