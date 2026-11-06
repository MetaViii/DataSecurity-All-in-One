"""Standard-library runtime appended to generated exp.py; not the application entry point."""

import argparse
import copy
import importlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys


class _EmbeddedModules(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in SOURCES:
            return importlib.util.spec_from_loader(fullname, self, is_package=fullname in PACKAGES)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        name = module.__name__
        # Virtual filenames keep tracebacks identifiable without unpacking files.
        filename = f"{__file__}::{name}"
        module.__file__ = filename
        exec(compile(SOURCES[name], filename, "exec"), module.__dict__)


def _load_runtime():
    existing = sys.modules.get("datasecurity")
    if existing is not None and not isinstance(existing.__loader__, _EmbeddedModules):
        raise RuntimeError("请用独立 Python 进程执行此脚本，避免混用已导入的 datasecurity")
    if existing is None:
        sys.meta_path.insert(0, _EmbeddedModules())
    modules = {
        name: importlib.import_module(name)
        for name in {"datasecurity", *(ref[0] for ref in PLUGIN_REFS.values())}
    }
    modules["_plugins"] = {
        plugin_id: getattr(modules[name], class_name)()
        for plugin_id, (name, class_name) in PLUGIN_REFS.items()
    }
    return modules


def _configuration(input_overrides, output_dir, overwrite, modules):
    configs = copy.deepcopy(CONFIG)
    for key, value in input_overrides.items():
        if key not in INPUT_FILES:
            raise ValueError(f"未知输入参数 {key}，可用项：{', '.join(INPUT_FILES)}")
        node, parameter = INPUT_FILES[key]["node"], INPUT_FILES[key]["parameter"]
        configs[node][parameter] = value
    output_dir = Path(output_dir).resolve()
    for node, filename in OUTPUT_FILES.items():
        configs[node]["path"] = str(output_dir / filename)
        if "overwrite" in configs[node]:
            configs[node]["overwrite"] = overwrite
    # Validate every config before reading data or invoking any output plugin.
    for node, plugin_id in NODE_PLUGINS.items():
        try:
            configs[node] = modules["_plugins"][plugin_id].prepare_config(configs[node])
        except Exception as exc:
            raise ValueError(f"节点 {node} ({plugin_id}) 参数无效：{exc}") from exc
    return configs


def _run_step(node, plugin_id, inputs, config, context, preview, steps, modules):
    context.node_id = node
    plugin = modules["_plugins"][plugin_id]
    try:
        outputs = (
            {} if preview and plugin.spec.kind == "output" else plugin.run(inputs, config, context)
        )
        if not isinstance(outputs, dict) or set(outputs) != set(plugin.spec.outputs):
            raise ValueError(f"插件应返回输出端口 {plugin.spec.outputs}")
        table_type = modules["datasecurity"].Table
        if any(not isinstance(value, table_type) for value in outputs.values()):
            raise TypeError("每个输出必须是 Table")
    except Exception as exc:
        raise RuntimeError(f"节点 {node} ({plugin_id}) 执行失败：{exc}") from exc
    steps.append(
        {
            "id": node,
            "plugin": plugin_id,
            "inputs": {port: len(value) for port, value in inputs.items()},
            "outputs": {port: len(value) for port, value in outputs.items()},
            "status": "preview_only" if preview and plugin.spec.kind == "output" else "ok",
        }
    )
    return outputs


def _summary(context, steps, preview):
    return {
        "flow": FLOW_NAME,
        "preview": preview,
        "steps": steps,
        "sources": sorted(str(path) for path in context.source_paths),
        "written_files": sorted(str(path) for path in context.output_paths),
    }


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=FLOW_NAME + "：独立复现脚本")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="相对输入路径的基准目录，默认脚本所在目录",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "output",
        help="结果目录，默认脚本旁的 output；显式相对路径以终端目录为基准",
    )
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="节点.参数=路径",
        help="覆盖一个输入文件或路径模板，可重复指定",
    )
    parser.add_argument("--preview", action="store_true", help="完整计算，跳过输出节点")
    parser.add_argument("--overwrite", action="store_true", help="允许替换已存在的输出文件")
    parser.add_argument("--json", action="store_true", help="输出 JSON 运行摘要")
    args = parser.parse_args(argv)
    overrides = {}
    for item in args.input:
        key, separator, value = item.partition("=")
        if not separator or not value:
            parser.error("--input 应填写 节点.参数=路径，路径不能为空")
        if key in overrides:
            parser.error(f"重复的输入覆盖：{key}")
        overrides[key] = value
    try:
        result = solve(
            base_dir=args.base_dir,
            output_dir=args.output_dir,
            input_overrides=overrides,
            preview=args.preview,
            overwrite=args.overwrite,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("预览完成（未写入输出文件）" if args.preview else "流程执行完成")
            for step in result["steps"]:
                counts = step["outputs"] or step["inputs"]
                print(f"  {step['id']}: " + ", ".join(f"{p}={n}行" for p, n in counts.items()))
            for path in result["written_files"]:
                print(f"  已写入 {path}")
        return 0
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
