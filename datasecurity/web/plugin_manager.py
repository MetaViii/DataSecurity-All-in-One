"""Small local plugin installer. Python source is trusted code, never sandboxed."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

MAX_SOURCE = 256 * 1024

TEMPLATES = (
    {
        "id": "transform",
        "name": "字段处理",
        "description": "逐行修改字段，自动记录修改前后值",
        "filename": "my_transform.py",
        "source": """from datasecurity import Parameter, Plugin, PluginSpec


class MyTransform(Plugin):
    spec = PluginSpec(
        id="local.my_transform", name="我的字段处理", kind="transform",
        description="给字段添加前缀；可从这里修改处理逻辑", category="自定义插件",
        inputs=("data",), outputs=("data",),
        parameters=(
            Parameter("field", str, "处理字段", required=True, widget="field"),
            Parameter("prefix", str, "前缀", default="demo_"),
        ),
    )

    def run(self, inputs, config, context):
        table = inputs["data"]
        table.require_columns([config["field"]])
        records = []
        for record in table.records:
            context.check_cancelled()
            field = config["field"]
            records.append(record.with_updates(
                {field: config["prefix"] + record.values[field]},
                node=context.node_id, reason="自定义前缀",
            ))
        return {"data": table.with_records(records)}


PLUGINS = [MyTransform]
""",
    },
    {
        "id": "validator",
        "name": "校验与分流",
        "description": "把通过与异常记录分别输出，保留异常原因",
        "filename": "my_validator.py",
        "source": """from datasecurity import Parameter, Plugin, PluginSpec


class MyValidator(Plugin):
    spec = PluginSpec(
        id="local.my_validator", name="我的校验", kind="transform",
        description="示例：检查字段是否为非空数字", category="自定义插件",
        inputs=("data",), outputs=("valid", "invalid"),
        parameters=(Parameter("field", str, "校验字段", required=True, widget="field"),),
    )

    def run(self, inputs, config, context):
        table = inputs["data"]
        field = config["field"]
        table.require_columns([field])
        valid, invalid = [], []
        for record in table.records:
            context.check_cancelled()
            if record.values[field].isascii() and record.values[field].isdigit():
                valid.append(record)
            else:
                invalid.append(record.with_issue(
                    node=context.node_id, field=field, message="应为非空 ASCII 数字",
                ))
        return {"valid": table.with_records(valid), "invalid": table.with_records(invalid)}


PLUGINS = [MyValidator]
""",
    },
)


class PluginManager:
    def __init__(self, workspace):
        self.workspace = workspace

    def directory(self) -> Path:
        directory = self.workspace.root / "plugins"
        if directory.is_symlink() or not directory.resolve().is_relative_to(self.workspace.root):
            raise ValueError("plugins 必须是工作区内的实际目录")
        directory.mkdir(exist_ok=True)
        return directory

    def path(self, filename: str, enabled: bool = True) -> Path:
        if not isinstance(filename, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]{0,79}\.py", filename
        ):
            raise ValueError("文件名须以字母开头，只含字母、数字、下划线，以 .py 结尾")
        if filename[:-3].upper() in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }:
            raise ValueError("文件名不能使用系统保留名称")
        path = self.directory() / (filename if enabled else filename + ".disabled")
        if path.is_symlink() or not path.resolve().is_relative_to(self.workspace.root):
            raise ValueError("不支持链接插件文件")
        return path

    def describe(self):
        with self.workspace._lock:
            registry = self.workspace.registry
            files = []
            for path in sorted(self.directory().iterdir()):
                if path.name.startswith("_") or not (
                    path.name.endswith(".py") or path.name.endswith(".py.disabled")
                ):
                    continue
                enabled = path.name.endswith(".py")
                filename = path.name if enabled else path.name[:-9]
                item = {"filename": filename, "enabled": enabled, "plugin_ids": [], "size": 0}
                try:
                    self.path(filename, enabled)
                    item["size"] = path.stat().st_size
                    if item["size"] <= MAX_SOURCE:
                        item["source"] = path.read_text(encoding="utf-8-sig")
                    else:
                        item["error"] = "文件超过 256 KiB，界面不读取源码"
                    if enabled:
                        item["plugin_ids"] = list(registry.file_plugins.get(path.resolve(), ()))
                        if path.resolve() in registry.file_errors:
                            item["error"] = registry.file_errors[path.resolve()]
                except (OSError, ValueError) as exc:
                    item["error"] = str(exc)
                files.append(item)
            return {
                "files": files,
                "templates": list(TEMPLATES),
                "plugins": registry.describe(),
                "plugin_errors": registry.load_errors,
            }

    def install(self, payload):
        if payload.get("trusted") is not True:
            raise ValueError("请先查看源码并确认信任；插件具有本地 Python 进程权限")
        source = payload.get("source")
        if (
            not isinstance(source, str)
            or not source.strip()
            or len(source.encode("utf-8")) > MAX_SOURCE
        ):
            raise ValueError("源码不能为空，且 UTF-8 编码后不能超过 256 KiB")
        with self.workspace._lock:
            path = self.path(payload.get("filename"))
            if path.exists() or self.path(path.name, False).exists():
                raise ValueError("同名插件已存在，请更换文件名；导入不会覆盖现有源码")
            try:
                ast.parse(source, filename=path.name)
                registry = self.workspace.registry.copy()
                registry.load_file(path, source)
                json.dumps(registry.describe(), ensure_ascii=False, allow_nan=False)
            except (Exception, SystemExit) as exc:
                raise ValueError(f"插件加载失败：{type(exc).__name__}: {exc}") from exc
            # Exclusive creation protects a file installed by another writer.
            created = False
            try:
                with path.open("x", encoding="utf-8", newline="") as handle:
                    created = True
                    handle.write(source)
            except OSError as exc:
                if created:
                    path.unlink(missing_ok=True)
                raise ValueError(f"无法保存插件文件：{exc}") from exc
            self.workspace.registry = registry
            return self.describe()

    def toggle(self, payload):
        enabled = payload.get("enabled")
        if type(enabled) is not bool:
            raise ValueError("enabled 必须是布尔值")
        if enabled and payload.get("trusted") is not True:
            raise ValueError("启用将执行 Python 源码，请确认信任")
        with self.workspace._lock:
            source = self.path(payload.get("filename"), not enabled)
            target = self.path(payload.get("filename"), enabled)
            if not source.is_file():
                raise ValueError("插件文件不存在或状态已改变，请刷新列表")
            if target.exists():
                raise ValueError("目标文件已存在，请先检查 plugins 目录中的同名文件")
            registry = self.workspace.registry.copy()
            if enabled:
                if source.stat().st_size > MAX_SOURCE:
                    raise ValueError("Web 启用只支持不超过 256 KiB 的插件")
                try:
                    registry.load_file(target, source.read_text(encoding="utf-8-sig"))
                    json.dumps(registry.describe(), ensure_ascii=False, allow_nan=False)
                except (Exception, SystemExit) as exc:
                    raise ValueError(f"插件加载失败：{type(exc).__name__}: {exc}") from exc
            else:
                registry.remove_file(source)
            source.rename(target)
            self.workspace.registry = registry
            return self.describe()
