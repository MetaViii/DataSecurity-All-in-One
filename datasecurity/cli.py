from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from datasecurity import __version__
from datasecurity.builtin import create_registry
from datasecurity.core.errors import ExecutionError, ValidationError
from datasecurity.core.pipeline import Pipeline


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"JSON 中存在重复字段：{key}")
        result[key] = value
    return result


def _load_definition(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as handle:
        definition = json.load(handle, object_pairs_hook=_unique_keys)
    if not isinstance(definition, dict):
        raise ValidationError("流程文件必须包含 JSON 对象")
    return definition


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DataSecurity-All-in-One：本地数据处理插件框架")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    plugins = commands.add_parser("plugins", help="列出插件与参数")
    plugins.add_argument("--id", help="查看指定插件的完整参数")
    serve = commands.add_parser("serve", help="启动本地 Web 工作台")
    serve.add_argument(
        "--workspace", type=Path, default=Path.cwd(), help="允许读写的工作区，默认当前目录"
    )
    serve.add_argument("--port", type=_positive_int, default=8765)
    serve.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    for command in (plugins,):
        command.add_argument(
            "--plugin-dir", action="append", default=[], help="加载目录下的 .py 插件；可重复指定"
        )
        command.add_argument("--json", action="store_true", help="输出 JSON")
    for name in ("validate", "run", "export-python"):
        command = commands.add_parser(
            name,
            help={
                "validate": "检查流程配置",
                "run": "执行流程",
                "export-python": "导出独立 exp.py",
            }[name],
        )
        command.add_argument("flow", type=Path, help="JSON 流程文件")
        command.add_argument(
            "--plugin-dir", action="append", default=[], help="额外插件目录，路径相对于当前工作目录"
        )
        command.add_argument("--json", action="store_true", help="输出机器可读的执行摘要")
        if name == "export-python":
            command.add_argument("--output", type=Path, default=Path("exp.py"), help="脚本保存路径")
            command.add_argument("--force", action="store_true", help="允许替换已存在的脚本")
        if name == "run":
            command.add_argument(
                "--base-dir", type=Path, help="输入输出相对路径的基准目录；默认流程文件所在目录"
            )
            command.add_argument(
                "--preview", action="store_true", help="完整计算并展示样本，不执行输出插件"
            )
            command.add_argument(
                "--limit",
                type=_positive_int,
                default=5,
                help="预览每个结果分支的展示条数，不限制实际计算",
            )
    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows pipes may otherwise use the local ANSI code page. Keep CLI JSON
    # and Chinese diagnostics readable when redirected or captured by a tool.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    if args.command == "serve":
        try:
            import uvicorn
            from datasecurity.web.app import create_app
        except ModuleNotFoundError:
            print('缺少 Web 依赖，请执行：python -m pip install -e ".[web]"', file=sys.stderr)
            return 2
        if args.port > 65535:
            print("端口必须小于等于 65535", file=sys.stderr)
            return 2
        if not args.no_browser:
            from threading import Timer
            import webbrowser

            Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
        uvicorn.run(create_app(args.workspace), host="127.0.0.1", port=args.port, log_level="info")
        return 0
    try:
        definition = None
        registry = create_registry()
        if args.command != "plugins":
            flow_path = args.flow.resolve()
            definition = _load_definition(flow_path)
            plugin_dirs = definition.get("plugin_dirs", [])
            if not isinstance(plugin_dirs, list) or any(
                not isinstance(item, str) for item in plugin_dirs
            ):
                raise ValidationError("plugin_dirs 必须是字符串数组")
            for directory in plugin_dirs:
                registry.discover((flow_path.parent / directory).resolve())
        for directory in args.plugin_dir:
            registry.discover(Path(directory))
        for error in registry.load_errors:
            print(f"插件加载提示：{error}", file=sys.stderr)

        if args.command == "plugins":
            if args.id:
                print(
                    json.dumps(registry.get(args.id).spec.describe(), ensure_ascii=False, indent=2)
                )
            elif args.json:
                print(
                    json.dumps(
                        {"plugins": registry.describe(), "load_errors": registry.load_errors},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                for plugin in registry.describe():
                    print(f"{plugin['id']:<22} {plugin['kind']:<10} {plugin['name']}")
            return 0

        pipeline = Pipeline(registry)
        if args.command == "export-python":
            from datasecurity.exporter import export_python
            from datasecurity.builtin._files import atomic_text

            target = args.output.resolve()
            if target == flow_path:
                raise ValueError("脚本不能覆盖输入流程文件")
            if target.exists() and not args.force:
                raise ValueError("脚本已存在，更换路径或使用 --force")
            exported = export_python(definition, registry)
            with atomic_text(target, encoding="utf-8", newline="\n") as handle:
                handle.write(exported.script)
            metadata = exported.describe()
            metadata.pop("script")
            metadata["path"] = str(target)
            print(
                json.dumps(metadata, ensure_ascii=False, indent=2)
                if args.json
                else f"已导出独立脚本：{target}"
            )
            return 0
        if args.command == "validate":
            steps = pipeline.plan(definition)
            payload = {"valid": True, "order": [step.id for step in steps]}
            print(
                json.dumps(payload, ensure_ascii=False, indent=2)
                if args.json
                else "配置通过；执行顺序：" + " → ".join(payload["order"])
            )
            return 0

        result = pipeline.run(
            definition, base_dir=args.base_dir or flow_path.parent, preview=args.preview
        )
        payload = result.summary()
        if args.preview:
            payload["previews"] = result.previews(args.limit)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("预览完成：完整计算，未执行输出插件。" if args.preview else "流程执行完成。")
            for step in result.steps:
                counts = step["outputs"] or step["inputs"]
                print(
                    f"  {step['id']}: "
                    + ", ".join(f"{port}={count} 条" for port, count in counts.items())
                )
            if args.preview:
                print(json.dumps(payload["previews"], ensure_ascii=False, indent=2))
            else:
                for path in payload["written_files"]:
                    print(f"  已写入 {path}")
        return 0
    except (OSError, ValueError, TypeError, ExecutionError) as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
