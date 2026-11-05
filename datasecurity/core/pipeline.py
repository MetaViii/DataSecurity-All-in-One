from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from threading import Event
from typing import Any, Callable

from .errors import ExecutionError, ValidationError
from .models import Table
from .plugin import Plugin, RunContext
from .registry import Registry


@dataclass(frozen=True)
class Step:
    id: str
    plugin: Plugin
    config: dict[str, Any]
    inputs: dict[str, tuple[str, str]]


@dataclass
class RunResult:
    preview: bool
    steps: list[dict]
    tables: dict[str, dict[str, Table]]
    sinks: dict[str, dict[str, Table]]
    context: RunContext

    def summary(self) -> dict:
        return {
            "mode": "preview" if self.preview else "run",
            "data_scope": "full",
            "steps": self.steps,
            "sources": sorted(str(path) for path in self.context.source_paths),
            "written_files": sorted(str(path) for path in self.context.output_paths),
        }

    def previews(self, limit: int) -> dict:
        views = self.sinks or self.tables
        return {
            f"{node}:{port}": {
                "columns": list(table.columns),
                "row_count": len(table),
                "rows": [
                    {"values": dict(record.values), **record.diagnostics()}
                    for record in table.records[:limit]
                ],
            }
            for node, ports in views.items()
            for port, table in ports.items()
        }


class Pipeline:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    def plan(self, definition: dict) -> list[Step]:
        if not isinstance(definition, dict):
            raise ValidationError("流程配置必须是 JSON 对象")
        unknown = set(definition) - {"version", "name", "description", "plugin_dirs", "nodes", "ui"}
        if unknown:
            raise ValidationError(f"未知流程字段：{', '.join(sorted(unknown))}")
        if type(definition.get("version")) is not int or definition["version"] != 1:
            raise ValidationError("当前只支持 version=1 的流程配置")
        raw_nodes = definition.get("nodes")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise ValidationError("nodes 必须是非空数组")
        nodes: dict[str, Step] = {}
        for raw in raw_nodes:
            if not isinstance(raw, dict) or set(raw) - {"id", "plugin", "config", "inputs"}:
                raise ValidationError("节点只能包含 id、plugin、config、inputs")
            node_id = raw.get("id", "")
            if not isinstance(node_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", node_id):
                raise ValidationError(f"无效的节点 ID：{node_id!r}")
            if node_id in nodes:
                raise ValidationError(f"节点 ID 重复：{node_id}")
            if not isinstance(raw.get("plugin"), str):
                raise ValidationError(f"节点 {node_id} 缺少 plugin")
            plugin = self.registry.get(raw["plugin"])
            config, raw_inputs = raw.get("config", {}), raw.get("inputs", {})
            if not isinstance(config, dict) or not isinstance(raw_inputs, dict):
                raise ValidationError(f"节点 {node_id} 的 config 和 inputs 必须是对象")
            if set(raw_inputs) != set(plugin.spec.inputs):
                raise ValidationError(
                    f"节点 {node_id} 需要输入端口 {plugin.spec.inputs}，实际为 {tuple(raw_inputs)}"
                )
            inputs = {}
            for port, endpoint in raw_inputs.items():
                if not isinstance(endpoint, str) or endpoint.count(":") != 1:
                    raise ValidationError(f"节点 {node_id} 的输入必须是 '节点ID:输出端口'")
                inputs[port] = tuple(endpoint.split(":"))
            try:
                prepared = plugin.prepare_config(config)
            except (ValueError, TypeError, KeyError, re.error) as exc:
                raise ValidationError(f"节点 {node_id} 的参数无效：{exc}") from exc
            nodes[node_id] = Step(node_id, plugin, prepared, inputs)

        dependencies = {}
        for node_id, step in nodes.items():
            dependencies[node_id] = set()
            for parent, port in step.inputs.values():
                if parent not in nodes:
                    raise ValidationError(f"节点 {node_id} 引用了不存在的节点：{parent}")
                if port not in nodes[parent].plugin.spec.outputs:
                    raise ValidationError(f"节点 {node_id} 引用了不存在的输出：{parent}:{port}")
                dependencies[node_id].add(parent)

        ordered: list[Step] = []
        done: set[str] = set()
        pending = list(nodes)
        while pending:
            ready = [node for node in pending if dependencies[node] <= done]
            if not ready:
                raise ValidationError(f"流程存在循环连接：{', '.join(pending)}")
            for node in ready:
                ordered.append(nodes[node])
                done.add(node)
                pending.remove(node)
        # Sinks cannot feed another node. Defer writes until every transform has
        # completed, so a late processing error does not leave earlier exports.
        return [step for step in ordered if step.plugin.spec.kind != "output"] + [
            step for step in ordered if step.plugin.spec.kind == "output"
        ]

    def scope(self, definition: dict, target: str | None) -> dict:
        """Select a node and its ancestors before validating unfinished drafts."""
        if target is None:
            return definition
        raw = definition.get("nodes", [])
        if not isinstance(raw, list) or any(not isinstance(node, dict) for node in raw):
            raise ValidationError("nodes 必须是节点数组")
        if any(not isinstance(node.get("id"), str) for node in raw):
            raise ValidationError("节点需要字符串 ID")
        node_map = {node["id"]: node for node in raw}
        if len(node_map) != len(raw):
            raise ValidationError("节点 ID 不能重复")
        required, pending = set(), [target]
        while pending:
            node_id = pending.pop()
            if node_id in required:
                continue
            if node_id not in node_map:
                raise ValidationError(f"找不到预览节点：{node_id}")
            required.add(node_id)
            inputs = node_map[node_id].get("inputs", {})
            if not isinstance(inputs, dict):
                raise ValidationError(f"节点 {node_id} 的 inputs 必须是对象")
            for endpoint in inputs.values():
                if not isinstance(endpoint, str) or endpoint.count(":") != 1:
                    raise ValidationError("输入必须是 节点ID:端口")
                pending.append(endpoint.split(":", 1)[0])
        return {**definition, "nodes": [node for node in raw if node.get("id") in required]}

    def run(
        self,
        definition: dict,
        *,
        base_dir: Path,
        preview: bool = False,
        target: str | None = None,
        workspace_root: Path | None = None,
        cancel_event: Event | None = None,
        on_step: Callable[[dict], None] | None = None,
    ) -> RunResult:
        if target is not None and not preview:
            raise ValidationError("指定目标节点只适用于预览")
        definition = self.scope(definition, target)
        steps = self.plan(definition)
        context = RunContext(
            base_dir.resolve(), preview, workspace_root=workspace_root, cancel_event=cancel_event
        )
        result = RunResult(preview, [], {}, {}, context)
        for step in steps:
            context.check_cancelled()
            context.node_id = step.id
            inputs = {
                port: result.tables[parent][output]
                for port, (parent, output) in step.inputs.items()
            }
            started = perf_counter()
            if on_step:
                on_step(
                    {
                        "id": step.id,
                        "status": "running",
                        "completed": len(result.steps),
                        "total": len(steps),
                    }
                )
            try:
                if step.plugin.spec.kind == "output":
                    result.sinks[step.id] = inputs
                # Preview never invokes output plugins, including third-party
                # ones. Input/transform plugins must themselves be read-only.
                outputs = (
                    {}
                    if preview and step.plugin.spec.kind == "output"
                    else step.plugin.run(inputs, step.config, context)
                )
                if not isinstance(outputs, dict) or set(outputs) != set(step.plugin.spec.outputs):
                    raise ValueError(f"插件应返回输出端口 {step.plugin.spec.outputs}")
                if any(not isinstance(table, Table) for table in outputs.values()):
                    raise TypeError("插件的每个输出必须是 Table")
                context.check_cancelled()
            except InterruptedError:
                raise
            except Exception as exc:
                raise ExecutionError(step.id, step.plugin.spec.id, exc, result) from exc
            result.tables[step.id] = outputs
            result.steps.append(
                {
                    "id": step.id,
                    "plugin": step.plugin.spec.id,
                    "plugin_version": step.plugin.spec.version,
                    "status": (
                        "preview_only" if preview and step.plugin.spec.kind == "output" else "ok"
                    ),
                    "inputs": {port: len(table) for port, table in inputs.items()},
                    "outputs": {port: len(table) for port, table in outputs.items()},
                    "seconds": round(perf_counter() - started, 6),
                }
            )
            if on_step:
                on_step({**result.steps[-1], "completed": len(result.steps), "total": len(steps)})
        return result
