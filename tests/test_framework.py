from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from datasecurity import Origin, Plugin, PluginSpec, Record, Table
from datasecurity.builtin import create_registry
from datasecurity.cli import main
from datasecurity.core.errors import ExecutionError, ValidationError
from datasecurity.core.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[1]


def node(node_id, plugin, config=None, **inputs):
    return {"id": node_id, "plugin": plugin, "config": config or {}, "inputs": inputs}


def flow(*nodes):
    return {"version": 1, "nodes": list(nodes)}


class FrameworkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="datasecurity-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.registry = create_registry()
        self.pipeline = Pipeline(self.registry)

    def source(
        self,
        text="编号,姓名,性别\n0001,测试甲,男\n0002,A,女\n",
        *,
        encoding="utf-8",
        name="input.csv",
    ):
        path = self.root / name
        path.write_text(text, encoding=encoding, newline="")
        return path

    def run_flow(self, definition, *, preview=False):
        return self.pipeline.run(definition, base_dir=self.root, preview=preview)

    def test_records_are_immutable_and_updates_keep_an_audit(self):
        source_values = {"编号": "0001", "备注": "abc"}
        record = Record(source_values, (Origin("input.csv", 7, 9),))
        source_values["备注"] = "outside mutation"
        self.assertEqual(record.values["备注"], "abc")
        with self.assertRaises(TypeError):
            record.values["备注"] = "mutation"
        changed = record.with_updates({"备注": "ABC"}, node="upper", reason="转为大写")
        self.assertEqual(record.values["备注"], "abc")
        self.assertEqual(changed.origins, record.origins)
        self.assertEqual((changed.changes[0].before, changed.changes[0].after), ("abc", "ABC"))

    def test_csv_round_trip_preserves_bom_zeros_quotes_newlines_and_empty_values(self):
        self.source(
            '编号,备注,空值\r\n0001,"逗号,和""引号""",\r\n0002,"多行\r\n备注",NULL\r\n',
            encoding="utf-8-sig",
        )
        definition = flow(
            node("read", "csv.read", {"path": "input.csv"}),
            node("save", "csv.write", {"path": "out.csv", "line_ending": "crlf"}, data="read:data"),
        )
        result = self.run_flow(definition)
        table = result.tables["read"]["data"]
        self.assertEqual(table.records[0].values["编号"], "0001")
        self.assertEqual(table.records[0].values["备注"], '逗号,和"引号"')
        self.assertEqual(table.records[0].values["空值"], "")
        self.assertEqual(table.records[1].values["空值"], "NULL")
        self.assertEqual(table.records[1].origins[0].line, 3)
        with (self.root / "out.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows, [dict(record.values) for record in table.records])

    def test_csv_read_and_write_honor_gbk(self):
        self.source("编号,备注\n0001,中文\n", encoding="gbk")
        self.run_flow(
            flow(
                node("read", "csv.read", {"path": "input.csv", "encoding": "gbk"}),
                node("save", "csv.write", {"path": "out.csv", "encoding": "gbk"}, data="read:data"),
            )
        )
        self.assertIn("中文".encode("gbk"), (self.root / "out.csv").read_bytes())

    def test_bad_csv_does_not_silently_drop_or_overwrite_fields(self):
        for text in ("a,a\n1,2\n", "a,b\n1\n", 'a,b\n1,"unclosed\n', "", "a,\n1,2\n"):
            with self.subTest(text=text):
                self.source(text)
                with self.assertRaises(ExecutionError):
                    self.run_flow(flow(node("read", "csv.read", {"path": "input.csv"})))

    def test_regex_validation_routes_all_records_and_keeps_failure_origin(self):
        self.source()
        result = self.run_flow(
            flow(
                node("read", "csv.read", {"path": "input.csv"}),
                node(
                    "check",
                    "validate.regex",
                    {"field": "姓名", "pattern": "[\u4e00-\u9fff]{2,4}"},
                    data="read:data",
                ),
            )
        )
        valid, invalid = result.tables["check"]["valid"], result.tables["check"]["invalid"]
        self.assertEqual((len(valid), len(invalid)), (1, 1))
        self.assertEqual(invalid.records[0].origins[0].record, 2)
        self.assertEqual(invalid.records[0].issues[0].field, "姓名")
        self.assertFalse(result.tables["read"]["data"].records[1].issues)

    def test_multi_condition_filter_supports_and_or_and_complement(self):
        self.source()
        conditions = [
            {"field": "性别", "op": "eq", "value": "男"},
            {"field": "姓名", "op": "length", "max": 1},
        ]
        for match, expected in (("all", (0, 2)), ("any", (2, 0))):
            with self.subTest(match=match):
                result = self.run_flow(
                    flow(
                        node("read", "csv.read", {"path": "input.csv"}),
                        node(
                            "filter",
                            "rows.filter",
                            {"conditions": conditions, "match": match},
                            data="read:data",
                        ),
                    )
                )
                ports = result.tables["filter"]
                self.assertEqual((len(ports["matched"]), len(ports["unmatched"])), expected)

    def test_preview_never_calls_output_plugin_or_creates_output_directory(self):
        class ForbiddenOutput(Plugin):
            spec = PluginSpec("test.output", "test", "output", "test", inputs=("data",))

            def run(self, inputs, config, context):
                raise AssertionError("预览绝不能调用此方法")

        self.registry.register(ForbiddenOutput())
        self.source()
        result = self.run_flow(
            flow(
                node("read", "csv.read", {"path": "input.csv"}),
                node("save", "csv.write", {"path": "new/output.csv"}, data="read:data"),
                node("forbidden", "test.output", data="read:data"),
            ),
            preview=True,
        )
        self.assertFalse((self.root / "new").exists())
        self.assertEqual(result.previews(1)["save:data"]["row_count"], 2)
        self.assertFalse(result.context.output_paths)

    def test_preview_limit_does_not_limit_computation_or_full_export(self):
        path = self.root / "input.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["编号", "类别"])
            writer.writerows(
                (f"{index:06}", "保留" if index % 10 == 0 else "其他") for index in range(10_005)
            )
        definition = flow(
            node("read", "csv.read", {"path": "input.csv"}),
            node(
                "filter",
                "rows.filter",
                {"conditions": [{"field": "类别", "op": "eq", "value": "保留"}]},
                data="read:data",
            ),
            node("save", "csv.write", {"path": "out.csv"}, data="filter:matched"),
        )
        preview = self.run_flow(definition, preview=True)
        self.assertEqual(preview.previews(2)["save:data"]["row_count"], 1_001)
        self.assertEqual(len(preview.previews(2)["save:data"]["rows"]), 2)
        self.assertFalse((self.root / "out.csv").exists())
        self.run_flow(definition)
        with (self.root / "out.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1_001)
        self.assertEqual(rows[-1]["编号"], "010000")

    def test_pipeline_orders_nodes_and_rejects_cycles_bad_ports_and_unknown_config(self):
        read = node("read", "csv.read", {"path": "input.csv"})
        check = node(
            "check", "validate.regex", {"field": "姓名", "pattern": ".+"}, data="read:data"
        )
        save = node("save", "csv.write", {"path": "out.csv"}, data="check:valid")
        self.assertEqual(
            [step.id for step in self.pipeline.plan(flow(save, check, read))],
            ["read", "check", "save"],
        )
        broken_definitions = [
            flow(read, read),
            flow(read, node("save", "csv.write", {"path": "out.csv"}, data="read:missing")),
            flow(node("read", "csv.read", {"path": "input.csv", "typo": True})),
            flow(node("read", "csv.read", {"path": "input.csv", "skip_blank_lines": 1})),
            flow(
                node(
                    "check", "validate.regex", {"field": "姓名", "pattern": "["}, data="read:data"
                ),
                read,
            ),
            flow(
                node("a", "validate.regex", {"field": "姓名", "pattern": ".*"}, data="b:valid"),
                node("b", "validate.regex", {"field": "姓名", "pattern": ".*"}, data="a:valid"),
            ),
        ]
        for definition in broken_definitions:
            with self.subTest(definition=definition), self.assertRaises(ValidationError):
                self.pipeline.plan(definition)

    def test_named_inputs_do_not_depend_on_connection_order(self):
        class Pair(Plugin):
            spec = PluginSpec(
                "test.pair",
                "test",
                "transform",
                "test",
                inputs=("left", "right"),
                outputs=("data",),
            )

            def run(self, inputs, config, context):
                left, right = inputs["left"].records[0], inputs["right"].records[0]
                record = Record(
                    {"left": left.values["value"], "right": right.values["value"]},
                    left.origins + right.origins,
                )
                return {"data": Table(("left", "right"), (record,))}

        self.registry.register(Pair())
        self.source("value\nLEFT\n", name="left.csv")
        self.source("value\nRIGHT\n", name="right.csv")
        definition = flow(
            node("pair", "test.pair", right="right:data", left="left:data"),
            node("right", "csv.read", {"path": "right.csv"}),
            node("left", "csv.read", {"path": "left.csv"}),
        )
        record = self.run_flow(definition).tables["pair"]["data"].records[0]
        self.assertEqual(dict(record.values), {"left": "LEFT", "right": "RIGHT"})
        self.assertEqual(len(record.origins), 2)

    def test_late_transform_failure_does_not_leave_an_earlier_export(self):
        class Fail(Plugin):
            spec = PluginSpec(
                "test.fail", "test", "transform", "test", inputs=("data",), outputs=("data",)
            )

            def run(self, inputs, config, context):
                raise ValueError("故意失败")

        self.registry.register(Fail())
        self.source()
        with self.assertRaisesRegex(ExecutionError, "故意失败"):
            self.run_flow(
                flow(
                    node("read", "csv.read", {"path": "input.csv"}),
                    node("save", "csv.write", {"path": "out.csv"}, data="read:data"),
                    node("fail", "test.fail", data="read:data"),
                )
            )
        self.assertFalse((self.root / "out.csv").exists())

    def test_outputs_protect_sources_and_require_explicit_overwrite(self):
        source = self.source()
        original = source.read_bytes()
        for output, overwrite in (("input.csv", True), ("exists.csv", False)):
            (self.root / "exists.csv").write_text("keep", encoding="utf-8")
            with self.subTest(output=output), self.assertRaises(ExecutionError):
                self.run_flow(
                    flow(
                        node("read", "csv.read", {"path": "input.csv"}),
                        node(
                            "save",
                            "csv.write",
                            {"path": output, "overwrite": overwrite},
                            data="read:data",
                        ),
                    )
                )
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual((self.root / "exists.csv").read_text(encoding="utf-8"), "keep")

    def test_failed_encoding_preserves_existing_target_and_cleans_temporary(self):
        self.source()
        target = self.root / "out.csv"
        target.write_text("previous result", encoding="utf-8")
        with self.assertRaises(ExecutionError):
            self.run_flow(
                flow(
                    node("read", "csv.read", {"path": "input.csv"}),
                    node(
                        "save",
                        "csv.write",
                        {"path": "out.csv", "encoding": "ascii", "overwrite": True},
                        data="read:data",
                    ),
                )
            )
        self.assertEqual(target.read_text(encoding="utf-8"), "previous result")
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_local_plugin_discovery_isolates_bad_files_and_tracks_changes(self):
        directory = self.root / "plugins"
        directory.mkdir()
        (directory / "good.py").write_text(
            (ROOT / "plugins/add_prefix.py").read_text(encoding="utf-8"), encoding="utf-8"
        )
        (directory / "broken.py").write_text(
            "raise RuntimeError('broken plugin')", encoding="utf-8"
        )
        self.registry.discover(directory)
        self.assertEqual(len(self.registry.load_errors), 1)
        self.source()
        result = self.run_flow(
            flow(
                node("read", "csv.read", {"path": "input.csv"}),
                node(
                    "prefix",
                    "example.add_prefix",
                    {"field": "姓名", "prefix": "["},
                    data="read:data",
                ),
                node(
                    "save",
                    "json.write",
                    {"path": "out.json", "diagnostics": True},
                    data="prefix:data",
                ),
            )
        )
        exported = json.loads((self.root / "out.json").read_text(encoding="utf-8"))
        self.assertEqual(exported[0]["changes"][0]["before"], "测试甲")
        self.assertEqual(exported[0]["values"]["姓名"], "[测试甲")
        self.assertEqual(result.tables["read"]["data"].records[0].values["姓名"], "测试甲")

    def test_cli_uses_flow_relative_paths_and_reports_invalid_config(self):
        self.source()
        path = self.root / "flow.json"
        path.write_text(
            json.dumps(flow(node("read", "csv.read", {"path": "input.csv"}))), encoding="utf-8"
        )
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["run", str(path), "--preview", "--limit", "1", "--json"])
        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["previews"]["read:data"]["row_count"], 2)
        path.write_text('{"version":1,"version":2,"nodes":[]}', encoding="utf-8")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["validate", str(path)]), 2)

    def test_example_pipeline_has_expected_branch_counts(self):
        definition = json.loads((ROOT / "examples/clean_people.json").read_text(encoding="utf-8"))
        result = self.pipeline.run(definition, base_dir=ROOT / "examples", preview=True)
        self.assertEqual(len(result.tables["check_phone"]["invalid"]), 1)
        self.assertEqual(len(result.tables["filter"]["matched"]), 2)
        self.assertEqual(len(result.tables["filter"]["unmatched"]), 2)


if __name__ == "__main__":
    unittest.main()
