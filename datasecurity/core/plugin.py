from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any

from .errors import ValidationError
from .models import Table

_MISSING = object()


@dataclass(frozen=True)
class Parameter:
    name: str
    type: type
    description: str
    required: bool = False
    default: Any = _MISSING
    choices: tuple[Any, ...] = ()
    widget: str = ""

    def describe(self) -> dict:
        result = {
            "name": self.name,
            "type": self.type.__name__,
            "description": self.description,
            "required": self.required,
        }
        if self.default is not _MISSING:
            result["default"] = self.default
        if self.choices:
            result["choices"] = list(self.choices)
        if self.widget:
            result["widget"] = self.widget
        return result


@dataclass(frozen=True)
class PluginSpec:
    id: str
    name: str
    kind: str
    description: str
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    parameters: tuple[Parameter, ...] = ()
    version: str = "1"
    category: str = ""

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_.-]*", self.id):
            raise ValueError(f"无效的插件 ID：{self.id}")
        if self.kind not in {"input", "transform", "output"}:
            raise ValueError(f"无效的插件类型：{self.kind}")
        if self.kind == "input" and (self.inputs or not self.outputs):
            raise ValueError("输入插件必须没有输入端口，且至少有一个输出端口")
        if self.kind == "transform" and (not self.inputs or not self.outputs):
            raise ValueError("处理插件必须声明输入和输出端口")
        if self.kind == "output" and (not self.inputs or self.outputs):
            raise ValueError("输出插件必须声明输入端口，且没有输出端口")
        for ports in (self.inputs, self.outputs):
            if len(set(ports)) != len(ports) or any(
                not re.fullmatch(r"[a-z][a-z0-9_]*", port) for port in ports
            ):
                raise ValueError("端口名称不能重复，且只能使用小写字母、数字和下划线")
        names = [parameter.name for parameter in self.parameters]
        if len(set(names)) != len(names):
            raise ValueError("插件参数名称不能重复")

    def describe(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "version": self.version,
            "description": self.description,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "parameters": [parameter.describe() for parameter in self.parameters],
            "category": self.category,
        }


@dataclass
class RunContext:
    base_dir: Path
    preview: bool = False
    node_id: str = ""
    source_paths: set[Path] = field(default_factory=set)
    output_paths: set[Path] = field(default_factory=set)
    workspace_root: Path | None = None
    cancel_event: Event | None = None

    def resolve_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        resolved = (path if path.is_absolute() else self.base_dir / path).resolve()
        if self.workspace_root is not None and not resolved.is_relative_to(
            self.workspace_root.resolve()
        ):
            raise ValueError("Web 模式的文件路径必须位于工作区内")
        return resolved

    def check_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise InterruptedError("任务已取消")

    def output_path(self, value: str, *, overwrite: bool) -> Path:
        if self.preview:
            raise ValueError("预览模式不能写入输出文件")
        path = self.resolve_path(value)
        if path in self.source_paths:
            raise ValueError(f"输出不能覆盖输入文件：{path}")
        if path in self.output_paths:
            raise ValueError(f"多个输出节点使用了同一路径：{path}")
        if path.exists() and not overwrite:
            raise FileExistsError(f"输出文件已存在，请指定 overwrite=true：{path}")
        self.output_paths.add(path)
        return path


class Plugin:
    spec: PluginSpec

    def prepare_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        import copy

        definitions = {parameter.name: parameter for parameter in self.spec.parameters}
        unknown = set(raw) - set(definitions)
        if unknown:
            raise ValidationError(f"未知参数：{', '.join(sorted(unknown))}")
        config = {}
        for name, parameter in definitions.items():
            if name in raw:
                value = raw[name]
            elif parameter.default is not _MISSING:
                value = copy.deepcopy(parameter.default)
            elif parameter.required:
                raise ValidationError(f"缺少参数：{name}")
            else:
                continue
            # bool is an int subclass; exact types avoid accepting true as 1.
            if type(value) is not parameter.type:
                raise ValidationError(f"参数 {name} 必须是 {parameter.type.__name__}")
            if parameter.choices and value not in parameter.choices:
                raise ValidationError(f"参数 {name} 必须是 {parameter.choices} 中的一个")
            config[name] = value
        self.check_config(config)
        return config

    def check_config(self, config: dict[str, Any]) -> None:
        """Override for ranges, nested rules and other plugin-specific checks."""

    def run(
        self, inputs: dict[str, Table], config: dict[str, Any], context: RunContext
    ) -> dict[str, Table]:
        raise NotImplementedError
