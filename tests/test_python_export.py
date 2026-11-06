"""Run exported programs in isolated Python processes, without the project on sys.path."""

import contextlib
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from datasecurity.builtin import create_registry
from datasecurity.cli import main
from datasecurity.core.pipeline import Pipeline
from datasecurity.exporter import export_python
from tests.test_framework import flow, node

ROOT = Path(__file__).resolve().parents[1]


class PythonExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = create_registry()

    def execute(self, exported, *args, site=False, cwd=None):
        script = self.root / "exp.py"
        script.write_text(exported.script, encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-I", *([] if site else ["-S"]), str(script), *map(str, args)],
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )

    def test_multibranch_csv_is_independent_and_byte_identical(self):
        (self.root / "input.csv").write_text(
            '编号,手机号,备注\n0001,13812345678,"中文,逗号"\n0002,23812345678,\n0003,1381234567a,空\n',
            encoding="utf-8",
            newline="",
        )
        definition = flow(
            node(
                "save_bad",
                "csv.write",
                {"path": "expected/bad.csv", "line_ending": "crlf"},
                data="phone:invalid",
            ),
            node("read", "csv.read", {"path": "input.csv"}),
            node(
                "phone",
                "validate.regex",
                {"field": "手机号", "pattern": "1[0-9]{10}"},
                data="read:data",
            ),
            node(
                "save_good",
                "csv.write",
                {"path": "expected/good.csv", "line_ending": "crlf"},
                data="phone:valid",
            ),
        )
        exported = export_python(definition, self.registry)
        self.assertFalse((self.root / "expected").exists())
        Pipeline(self.registry).run(definition, base_dir=self.root)
        result = self.execute(exported, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["steps"][1]["outputs"], {"valid": 1, "invalid": 2})
        self.assertEqual(
            [s["id"] for s in summary["steps"]], ["read", "phone", "save_bad", "save_good"]
        )
        for name in ("good.csv", "bad.csv"):
            self.assertEqual(
                (self.root / "expected" / name).read_bytes(),
                (self.root / "output" / name).read_bytes(),
            )
        self.assertEqual(exported.run_command, "python exp.py data.csv --output-dir output")
        ambiguous = self.execute(exported, "input.csv", "answer.csv")
        self.assertEqual(ambiguous.returncode, 2)
        self.assertIn("恰好一个文件输出", ambiguous.stderr)
        self.assertFalse((self.root / "answer.csv").exists())
        direct = self.execute(exported, "input.csv", "--output-dir", self.root / "all-outputs")
        self.assertEqual(direct.returncode, 0, direct.stderr)
        for name in ("good.csv", "bad.csv"):
            self.assertEqual(
                (self.root / "expected" / name).read_bytes(),
                (self.root / "all-outputs" / name).read_bytes(),
            )

    def test_positional_csv_uses_terminal_directory_without_installed_packages(self):
        terminal = self.root / "终端 空格"
        terminal.mkdir()
        source = terminal / "输入 数据.csv"
        source.write_text(
            '编号,手机号,备注\n0001,13812345678,"中文,逗号"\n0002,23812345678,错误\n',
            encoding="utf-8",
            newline="",
        )
        definition = flow(
            node("read", "csv.read", {"path": "old-workspace/missing.csv"}),
            node(
                "phone",
                "validate.regex",
                {"field": "手机号", "pattern": "1[0-9]{10}"},
                data="read:data",
            ),
            node("save", "csv.write", {"path": "old-workspace/answer.csv"}, data="phone:valid"),
        )
        exported = export_python(definition, self.registry)
        self.assertEqual(exported.run_command, "python exp.py data.csv output.csv")
        self.assertEqual(exported.describe()["run_command"], exported.run_command)
        self.assertEqual(exported.requirements, [])
        self.assertEqual(exported.commands, [])
        # The baseline and exported script use the same nodes, but the script
        # lives outside the terminal directory and has no site-packages.
        definition["nodes"][0]["config"]["path"] = source.name
        definition["nodes"][-1]["config"]["path"] = "expected.csv"
        Pipeline(self.registry).run(definition, base_dir=terminal)
        result = self.execute(exported, source.name, "结果 数据.csv", "--json", cwd=terminal)
        self.assertEqual(result.returncode, 0, result.stderr)
        target = terminal / "结果 数据.csv"
        self.assertEqual(target.read_bytes(), (terminal / "expected.csv").read_bytes())
        self.assertEqual(json.loads(result.stdout)["written_files"], [str(target)])
        self.assertIn("0001", target.read_text(encoding="utf-8"))
        self.assertFalse((self.root / "output").exists())
        self.assertFalse((self.root / "old-workspace").exists())

    def test_positional_preview_overwrite_and_path_protection(self):
        source = self.root / "data.csv"
        source.write_text("编号\n0001\n", encoding="utf-8", newline="")
        exported = export_python(
            flow(
                node("read", "csv.read", {"path": "missing.csv"}),
                node("save", "csv.write", {"path": "answer.csv"}, data="read:data"),
            ),
            self.registry,
        )
        preview = self.execute(exported, "data.csv", "output.csv", "--preview", "--json")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(json.loads(preview.stdout)["written_files"], [])
        target = self.root / "output.csv"
        self.assertFalse(target.exists())
        self.assertEqual(self.execute(exported, "data.csv", "output.csv").returncode, 0)
        target.write_text("保留旧结果", encoding="utf-8")
        again = self.execute(exported, "data.csv", "output.csv")
        self.assertEqual(again.returncode, 2)
        self.assertIn("已存在", again.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), "保留旧结果")
        overwritten = self.execute(exported, "data.csv", "output.csv", "--overwrite")
        self.assertEqual(overwritten.returncode, 0, overwritten.stderr)
        self.assertEqual(target.read_bytes(), source.read_bytes())
        original = source.read_bytes()
        protected = self.execute(exported, "data.csv", "data.csv", "--overwrite")
        self.assertEqual(protected.returncode, 2)
        self.assertIn("不能覆盖输入", protected.stderr)
        self.assertEqual(source.read_bytes(), original)
        own_script = self.execute(exported, "data.csv", "exp.py", "--overwrite")
        self.assertEqual(own_script.returncode, 2)
        self.assertIn("脚本本身", own_script.stderr)
        self.assertEqual((self.root / "exp.py").read_text(encoding="utf-8"), exported.script)

    def test_positional_conflicts_and_ambiguous_inputs_are_rejected(self):
        exported = export_python(
            flow(
                node("read", "csv.read", {"path": "missing.csv"}),
                node("save", "csv.write", {"path": "answer.csv"}, data="read:data"),
            ),
            self.registry,
        )
        for args, message in (
            (("data.csv", "--input", "read.path=another.csv"), "重复的输入覆盖"),
            (("data.csv", "output.csv", "--output-dir", "result"), "不能同时指定"),
        ):
            with self.subTest(args=args):
                result = self.execute(exported, *args)
                self.assertEqual(result.returncode, 2)
                self.assertIn(message, result.stderr)
        multiple = export_python(
            flow(
                node("first", "csv.read", {"path": "missing.csv"}),
                node("second", "csv.read", {"path": "also-missing.csv"}),
                node("save", "csv.write", {"path": "answer.csv"}, data="first:data"),
            ),
            self.registry,
        )
        self.assertIn("--base-dir", multiple.run_command)
        result = self.execute(multiple, "data.csv", "output.csv")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--input 节点.参数=路径", result.stderr)
        self.assertFalse((self.root / "output").exists())

    def test_input_override_preview_and_overwrite(self):
        source = self.root / "替换附件.csv"
        source.write_text("编号\n0001\n", encoding="utf-8")
        exported = export_python(
            flow(
                node("read", "csv.read", {"path": "not-present.csv"}),
                node("save", "csv.write", {"path": "answer.csv"}, data="read:data"),
            ),
            self.registry,
        )
        flags = ("--input", f"read.path={source}", "--output-dir", self.root / "chosen", "--json")
        result = self.execute(exported, *flags, "--preview")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["written_files"], [])
        self.assertFalse((self.root / "chosen").exists())
        self.assertEqual(self.execute(exported, *flags).returncode, 0)
        again = self.execute(exported, *flags)
        self.assertEqual(again.returncode, 2)
        self.assertIn("已存在", again.stderr)
        self.assertEqual(self.execute(exported, *flags, "--overwrite").returncode, 0)
        self.assertIn("未知输入参数", self.execute(exported, "--input", "typo.path=x").stderr)

    def test_custom_plugin_snapshot_and_shared_instance(self):
        path = self.root / "custom.py"
        path.write_text(
            """from datasecurity import Plugin, PluginSpec
class Counter(Plugin):
    spec = PluginSpec("local.counter", "计数", "transform", "测试状态保持", inputs=("data",), outputs=("data",))
    def __init__(self):
        self.count = 0
    def run(self, inputs, config, context):
        self.count += 1
        table = inputs["data"]
        return {"data": table.with_records(record.with_updates({"次数": str(self.count)}, node=context.node_id, reason="计数") for record in table.records)}
PLUGINS = [Counter]
""",
            encoding="utf-8",
        )
        self.registry.load_file(path)
        cloned = self.registry.copy()
        self.assertEqual(cloned.file_sources, self.registry.file_sources)
        path.write_text(
            'raise RuntimeError("export must not run changed plugin source")', encoding="utf-8"
        )
        (self.root / "data.csv").write_text("次数\n0\n", encoding="utf-8")
        exported = export_python(
            flow(
                node("read", "csv.read", {"path": "data.csv"}),
                node("first", "local.counter", data="read:data"),
                node("second", "local.counter", data="first:data"),
                node("save", "json.write", {"path": "result.json"}, data="second:data"),
            ),
            cloned,
        )
        self.assertNotIn("export must not run changed", exported.script)
        result = self.execute(exported)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.root / "output/result.json").read_text(encoding="utf-8"))
        self.assertEqual(data, [{"次数": "2"}])
        cloned.remove_file(path)
        self.assertNotIn(path, cloned.file_sources)

    def test_invalid_flow_duplicate_outputs_and_literal_injection(self):
        with self.assertRaisesRegex(ValueError, "字段列表"):
            export_python(
                flow(
                    node("source", "csv.read", {"path": "missing.csv"}),
                    node("read", "columns.select", {"fields": []}, data="source:data"),
                ),
                self.registry,
            )
        with self.assertRaisesRegex(ValueError, "不能重复"):
            export_python(
                flow(
                    node("read", "csv.read", {"path": "missing.csv"}),
                    node("a", "csv.write", {"path": "a/result.csv"}, data="read:data"),
                    node("b", "csv.write", {"path": "b/RESULT.csv"}, data="read:data"),
                ),
                self.registry,
            )
        definition = flow(node("read", "csv.read", {"path": "missing.csv"}))
        definition["name"] = "name\n__import__('pathlib').Path('INJECTED').touch()"
        definition["ui"] = {"labels": {"read": "读取\n__import__('os').system('bad')"}}
        exported = export_python(definition, self.registry)
        result = self.execute(exported, "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "INJECTED").exists())

    def test_cli_exports_without_reading_inputs_and_protects_existing_script(self):
        source = self.root / "flow.json"
        target = self.root / "exp.py"
        source.write_text(
            json.dumps(flow(node("read", "csv.read", {"path": "missing.csv"}))), encoding="utf-8"
        )
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["export-python", str(source), "--output", str(target)]), 0)
            original = target.read_bytes()
            self.assertEqual(main(["export-python", str(source), "--output", str(target)]), 2)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(
                main(["export-python", str(source), "--output", str(source), "--force"]), 2
            )

    def test_local_helper_import_is_explicitly_rejected(self):
        path = self.root / "custom.py"
        path.write_text(
            """from datasecurity import Plugin, PluginSpec
class Local(Plugin):
    spec = PluginSpec("local.helper", "本地模块", "input", "不能遗漏依赖", outputs=("data",))
    def run(self, inputs, config, context):
        import helper
        return {"data": helper.read()}
PLUGINS = [Local]
""",
            encoding="utf-8",
        )
        (self.root / "helper.py").write_text("def read(): pass\n", encoding="utf-8")
        self.registry.load_file(path)
        with self.assertRaisesRegex(ValueError, "依赖本地模块 helper"):
            export_python(flow(node("read", "local.helper")), self.registry)

    def test_correction_xlsx_roundtrip(self):
        try:
            from openpyxl import load_workbook
        except ImportError:
            self.skipTest("openpyxl is optional")
        definition = json.loads((ROOT / "examples/ctf_correction.json").read_text(encoding="utf-8"))
        exported = export_python(definition, self.registry)
        self.assertEqual(exported.requirements, ["openpyxl>=3.1,<4"])
        result = self.execute(exported, "--base-dir", ROOT / "examples", site=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        workbook = load_workbook(self.root / "output/corrected.xlsx", read_only=True)
        try:
            actual = list(workbook.active.values)
        finally:
            workbook.close()
        with (ROOT / "examples/data/correction_answer.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            expected = [tuple(row) for row in csv.reader(handle)]
        self.assertEqual(actual, expected)
        self.assertEqual(actual[1][0], "0001")

    def test_custom_optional_dependency_is_declared(self):
        path = self.root / "custom.py"
        path.write_text(
            '''from datasecurity import Plugin, PluginSpec, Table
class Local(Plugin):
    spec = PluginSpec("local.xlsx", "依赖声明", "input", "可选依赖不能遗漏", outputs=("data",))
    def run(self, inputs, config, context):
        import openpyxl
        return {"data": Table.from_rows(("a",), [])}
PLUGINS = [Local]
# Both triple quote styles: \'\'\' and """
''',
            encoding="utf-8",
        )
        self.registry.load_file(path)
        exported = export_python(flow(node("read", "local.xlsx")), self.registry)
        self.assertEqual(exported.requirements, ["openpyxl>=3.1,<4"])
        compile(exported.script, "exp.py", "exec")
