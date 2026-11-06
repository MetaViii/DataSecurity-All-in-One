"""Export a validated DAG as a readable, self-contained Python reproduction script."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path, PureWindowsPath
from pprint import pformat
import re
import sys

from datasecurity import __version__
from datasecurity.core.pipeline import Pipeline
from datasecurity.core.registry import Registry

ROOT = Path(__file__).resolve().parent


def _comment(value) -> str:
    return re.sub(r"[\x00-\x1f\x7f\u2028\u2029]", " ", str(value))[:180]


def _literal(source: str) -> str:
    # Most modules fit a raw triple-quoted literal, retaining readable regexes.
    source = source.removeprefix("\ufeff")
    if not source.endswith("\n"):
        source += "\n"
    for quote in ("'''", '"""'):
        if quote not in source:
            return "r" + quote + source + quote
    return pformat(source, width=100)


class _Sources:
    def __init__(self):
        self.sources: dict[str, str] = {}
        self.packages: set[str] = set()
        self.visited: set[str] = set()
        self.external: set[str] = set()
        self.custom_external: set[str] = set()

    def path(self, name):
        relative = name.split(".")[1:]
        path = ROOT.joinpath(*relative)
        return path / "__init__.py" if path.is_dir() else path.with_suffix(".py")

    def add(self, name, source=None, *, local_path=None):
        if name in self.visited:
            return
        self.visited.add(name)
        if source is None:
            source = self.path(name).read_text(encoding="utf-8-sig")
        self.sources[name] = source
        package = (
            name
            if name.startswith("datasecurity") and self.path(name).name == "__init__.py"
            else name.rpartition(".")[0]
        )
        if name.startswith("datasecurity"):
            parts = name.split(".")
            for index in range(1, len(parts)):
                parent = ".".join(parts[:index])
                self.packages.add(parent)
                # Do not import builtin/__init__ and thus the whole node catalog.
                self.sources.setdefault(parent, "")
            if self.path(name).name == "__init__.py":
                self.packages.add(name)
        for node in ast.walk(ast.parse(source)):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    if not package:
                        raise ValueError(f"独立插件 {name} 不能使用相对导入")
                    base = importlib.util.resolve_name("." * node.level + base, package)
                names = [base]
                names.extend(
                    f"{base}.{alias.name}"
                    for alias in node.names
                    if base.startswith("datasecurity")
                    and alias.name != "*"
                    and self.path(f"{base}.{alias.name}").is_file()
                )
            for imported in names:
                if imported == "datasecurity" or imported.startswith("datasecurity."):
                    self.add(imported)
                else:
                    top = imported.split(".")[0]
                    if (
                        local_path
                        and top
                        and (
                            (local_path.parent / f"{top}.py").is_file()
                            or (local_path.parent / top / "__init__.py").is_file()
                        )
                    ):
                        raise ValueError(
                            f"插件 {local_path.name} 依赖本地模块 {top}；请先合并为单文件插件再导出"
                        )
                    if top and top not in sys.stdlib_module_names and top != "__future__":
                        self.external.add(top)
                        if local_path:
                            self.custom_external.add(top)
        if (
            len(self.sources) > 128
            or sum(len(s.encode("utf-8")) for s in self.sources.values()) > 4 * 1024 * 1024
        ):
            raise ValueError("导出源码超过128个模块或4MiB，停止生成")


@dataclass(frozen=True)
class PythonExport:
    script: str
    nodes: int
    modules: int
    inputs: dict
    outputs: dict
    requirements: list[str]
    commands: list[str]
    warnings: list[str]

    def describe(self):
        return {
            "filename": "exp.py",
            "script": self.script,
            "nodes": self.nodes,
            "modules": self.modules,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "requirements": self.requirements,
            "commands": self.commands,
            "warnings": self.warnings,
            "version": __version__,
            "bytes": len(self.script.encode("utf-8")),
            "sha256": hashlib.sha256(self.script.encode("utf-8")).hexdigest(),
        }


def export_python(definition: dict, registry: Registry) -> PythonExport:
    """Validate without reading attachments or invoking a node's run method."""
    plan = Pipeline(registry).plan(definition)
    sources = _Sources()
    sources.add("datasecurity")
    configs, refs, inputs, outputs, versions = {}, {}, {}, {}, {}
    requirements, commands, warnings = [], [], []
    labels = (
        definition.get("ui", {}).get("labels", {}) if isinstance(definition.get("ui"), dict) else {}
    )
    if not isinstance(labels, dict):
        labels = {}
    for step in plan:
        cls = type(step.plugin)
        name = cls.__module__
        if cls.__qualname__ != cls.__name__:
            raise ValueError(f"插件 {step.plugin.spec.id} 的类不是模块顶层类，无法导出")
        if name.startswith("datasecurity.builtin."):
            sources.add(name)
        else:
            path = next(
                (p for p, ids in registry.file_plugins.items() if step.plugin.spec.id in ids), None
            )
            if (
                path is None
                or name not in sys.modules
                or getattr(sys.modules[name], cls.__name__, None) is not cls
            ):
                raise ValueError(
                    f"插件 {step.plugin.spec.id} 没有可导出的单文件源码，请通过插件管理加载"
                )
            sources.add(name, registry.file_sources[path], local_path=path)
            warning = "自定义插件仅内嵌其已加载的单文件源码；第三方库及额外资源需自行提供。"
            if warning not in warnings:
                warnings.append(warning)
        refs[step.plugin.spec.id] = (name, cls.__name__)
        versions[step.plugin.spec.id] = step.plugin.spec.version
        configs[step.id] = dict(step.config)
        for parameter in step.plugin.spec.parameters:
            if parameter.widget in {"input_file", "input_file_template"} and step.config.get(
                parameter.name
            ):
                inputs[f"{step.id}.{parameter.name}"] = {
                    "node": step.id,
                    "parameter": parameter.name,
                    "path": step.config[parameter.name],
                    "template": parameter.widget == "input_file_template",
                }
        if step.plugin.spec.kind == "output" and "path" in step.config:
            filename = PureWindowsPath(step.config["path"]).name
            if (
                not filename
                or filename in {".", ".."}
                or re.search(r'[<>:"/\\|?*\x00-\x1f]', filename)
            ):
                raise ValueError(f"输出节点 {step.id} 的文件名无效")
            if filename.casefold() in {value.casefold() for value in outputs.values()}:
                raise ValueError("导出脚本的输出文件名不能重复，请先修改输出节点")
            outputs[step.id] = filename
            configs[step.id]["path"] = filename
            if "overwrite" in configs[step.id]:
                configs[step.id]["overwrite"] = False
        if (
            step.plugin.spec.id in {"xlsx.read", "xlsx.write"}
            and "openpyxl>=3.1,<4" not in requirements
        ):
            requirements.append("openpyxl>=3.1,<4")
        if step.plugin.spec.id == "validate.signature":
            requirements.append("cryptography>=42,<52")
        if step.plugin.spec.id == "pcap.http" and "tshark" not in commands:
            commands.append("tshark")

    builtin_optional = {"openpyxl", "cryptography"}
    for name, requirement in {
        "openpyxl": "openpyxl>=3.1,<4",
        "cryptography": "cryptography>=42,<52",
    }.items():
        if name in sources.custom_external:
            requirements.append(requirement)
    external = sorted(sources.external - builtin_optional)
    if external:
        warnings.append("另需可导入的第三方模块（安装包名称可能不同）：" + ", ".join(external))
    requirements = sorted(set(requirements))
    flow_name = definition.get("name") or "未命名流程"
    if not isinstance(flow_name, str):
        raise ValueError("流程名称必须是字符串")
    json.dumps(configs, ensure_ascii=False, allow_nan=False)
    lines = [
        "#!/usr/bin/env python3",
        "# -*- coding: utf-8 -*-",
        "from __future__ import annotations",
        "",
        f"# {_comment(flow_name)} — DataSecurity {__version__} 独立复现脚本",
        "# Python 3.11+；不需要安装 DataSecurity、FastAPI 或前端。",
        "# 用法：python exp.py --base-dir 附件根目录 --output-dir output",
        "# 附件/公钥等资源不内嵌；默认以脚本目录解析相对输入路径。",
        "# 输出统一放入 output，默认不覆盖；--preview 跳过输出节点。",
    ]
    if requirements:
        lines.append(
            "# 安装依赖：python -m pip install " + " ".join(f'"{r}"' for r in requirements)
        )
    if commands:
        lines.append("# 外部程序需位于 PATH：" + ", ".join(commands))
    lines.extend("# 注意：" + _comment(warning) for warning in warnings)
    lines.extend(
        [
            "",
            f"FLOW_NAME = {flow_name!r}",
            "",
            "# 可编辑参数；正则、换行、编码等均为实际配置。",
            "CONFIG = " + pformat(configs, width=100, sort_dicts=False),
            "",
            "# 可用 --input 节点.参数=路径 覆盖输入，不必改处理代码。",
            "INPUT_FILES = " + pformat(inputs, width=100, sort_dicts=False),
            "OUTPUT_FILES = " + pformat(outputs, width=100, sort_dicts=False),
            "PLUGIN_REFS = " + pformat(refs, width=100, sort_dicts=False),
            "NODE_PLUGINS = " + repr({step.id: step.plugin.spec.id for step in plan}),
            "PLUGIN_VERSIONS = " + pformat(versions, width=100, sort_dicts=False),
            "",
            "",
            "def solve(*, base_dir=None, output_dir=None, input_overrides=None, preview=False, overwrite=False):",
            "    modules = _load_runtime()",
            "    base_dir = Path(base_dir or Path(__file__).resolve().parent).resolve()",
            "    output_dir = output_dir or Path(__file__).resolve().parent / 'output'",
            "    config = _configuration(input_overrides or {}, output_dir, overwrite, modules)",
            "    context = modules['datasecurity'].RunContext(base_dir, preview=preview)",
            "    tables, steps = {}, []",
        ]
    )
    for index, step in enumerate(plan, 1):
        title = labels.get(step.id, step.plugin.spec.name)
        connections = (
            "{"
            + ", ".join(
                f"{port!r}: tables[{parent!r}][{output!r}]"
                for port, (parent, output) in step.inputs.items()
            )
            + "}"
        )
        lines.extend(
            [
                "",
                f"    # {index}. {_comment(title)} ({step.id} / {step.plugin.spec.id})",
                f"    tables[{step.id!r}] = _run_step(",
                f"        {step.id!r}, {step.plugin.spec.id!r}, {connections},",
                f"        config[{step.id!r}], context, preview, steps, modules)",
            ]
        )
    lines.extend(
        [
            "",
            "    return _summary(context, steps, preview)",
            "",
            "",
            "# ---- 内嵌处理源码：与节点使用相同实现，可逐模块审计 ----",
            "SOURCES = {}",
            "PACKAGES = " + repr(tuple(sorted(sources.packages))),
            "",
        ]
    )
    for name, source in sorted(sources.sources.items()):
        lines.extend([f"# 模块：{name}", f"SOURCES[{name!r}] = " + _literal(source), ""])
    lines.extend(
        [
            "# ---- 独立运行入口（仅使用标准库） ----",
            (ROOT / "_export_runtime.py").read_text(encoding="utf-8"),
        ]
    )
    script = "\n".join(lines)
    compile(script, "exp.py", "exec")
    return PythonExport(
        script, len(plan), len(sources.sources), inputs, outputs, requirements, commands, warnings
    )
