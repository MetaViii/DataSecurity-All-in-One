"""Behavior checks for data preservation and generic nodes, using synthetic data."""

import tempfile
import unittest
from pathlib import Path
from threading import Event

from datasecurity import RunContext, Table
from datasecurity.builtin import create_registry


class NodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = create_registry()
        self.context = RunContext(self.root, node_id="test")

    def table(self, *rows):
        return Table.from_rows(tuple(dict.fromkeys(key for row in rows for key in row)), rows)

    def run_node(self, name, config, data=None, **inputs):
        plugin = self.registry.get(name)
        return plugin.run(
            {"data": data} if data is not None else inputs,
            plugin.prepare_config(config),
            self.context,
        )

    def test_schema_changes_and_text_operations_keep_original(self):
        source = self.table({"id": "0001", "name": "  Ａ  B  ", "parts": "a:b:c"})
        cleaned = self.run_node(
            "text.clean",
            {"fields": ["name"], "action": "collapse_whitespace", "normalization": "NFKC"},
            source,
        )["data"]
        self.assertEqual(cleaned.records[0].values["name"], "A B")
        split = self.run_node(
            "columns.split",
            {
                "field": "parts",
                "separator": ":",
                "outputs": ["first", "rest"],
                "keep_source": False,
            },
            cleaned,
        )["data"]
        self.assertEqual(split.records[0].values["rest"], "b:c")
        renamed = self.run_node("columns.rename", {"mapping": {"id": "编号"}}, split)["data"]
        selected = self.run_node("columns.select", {"fields": ["编号", "name"]}, renamed)["data"]
        self.assertEqual(selected.columns, ("编号", "name"))
        self.assertEqual(selected.records[0].values["编号"], "0001")
        self.assertEqual(source.records[0].values["name"], "  Ａ  B  ")
        self.assertTrue(
            {"add", "drop", "update"}
            <= {change.operation for change in selected.records[0].changes}
        )
        self.assertEqual(selected.records[0].origins, source.records[0].origins)

    def test_replace_extract_combine_and_fill(self):
        source = self.table({"a": "x12x", "b": "  "})
        result = self.run_node(
            "text.replace", {"fields": ["a"], "search": "x", "replacement": "", "count": 1}, source
        )["data"]
        result = self.run_node(
            "text.extract", {"field": "a", "pattern": r"(\d+)", "output": "digits"}, result
        )["data"]
        result = self.run_node(
            "values.fill", {"fields": ["b"], "value": "empty", "whitespace_empty": True}, result
        )["data"]
        result = self.run_node(
            "columns.combine",
            {
                "fields": ["digits", "b"],
                "separator": "-",
                "output": "combined",
                "drop_sources": True,
            },
            result,
        )["data"]
        self.assertEqual(dict(result.records[0].values), {"a": "12x", "combined": "12-empty"})
        missing = self.run_node("text.extract", {"field": "a", "pattern": "(z)"}, source)["data"]
        self.assertEqual(len(missing.records[0].issues), 1)

    def test_deduplication_strategies_partition_all_records(self):
        source = self.table({"key": "x", "n": "1"}, {"key": "y", "n": "2"}, {"key": "x", "n": "3"})
        for strategy, expected in (("first", ["1", "2"]), ("last", ["2", "3"]), ("none", ["2"])):
            result = self.run_node(
                "rows.deduplicate", {"fields": ["key"], "keep": strategy}, source
            )
            self.assertEqual([r.values["n"] for r in result["unique"].records], expected)
            self.assertEqual(len(result["unique"]) + len(result["duplicates"]), 3)

    def test_sort_decimal_stability_and_empty_position(self):
        source = self.table(
            *({"n": n, "id": str(i)} for i, n in enumerate(["2", "10", "", "2", "-1"]))
        )
        result = self.run_node(
            "rows.sort", {"rules": [{"field": "n", "type": "number", "direction": "desc"}]}, source
        )["data"]
        self.assertEqual([r.values["id"] for r in result.records], ["1", "0", "3", "4", "2"])
        a = self.run_node("rows.sample", {"mode": "random", "count": 3, "seed": 7}, source)["data"]
        b = self.run_node("rows.sample", {"mode": "random", "count": 3, "seed": 7}, source)["data"]
        self.assertEqual(a, b)

    def test_expression_decimal_rounding_and_unsafe_syntax(self):
        source = self.table({"单价": "0.1", "数量": "3"})
        result = self.run_node(
            "columns.calculate", {"expression": "[单价] * [数量] + 0.2", "output": "总价"}, source
        )["data"]
        self.assertEqual(result.records[0].values["总价"], "0.5")
        result = self.run_node(
            "columns.calculate", {"expression": "round(1.005, 2)", "output": "总价"}, source
        )["data"]
        self.assertEqual(result.records[0].values["总价"], "1.01")
        literal = self.run_node(
            "columns.calculate", {"expression": "'[literal]' + [单价]", "output": "x"}, source
        )["data"]
        self.assertEqual(literal.records[0].values["x"], "[literal]0.1")
        for expression in (
            "__import__('os')",
            "x.__class__",
            "open('x')",
            "[x for x in y]",
            "2 ** 999",
        ):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                self.run_node(
                    "columns.calculate", {"expression": expression, "output": "x"}, source
                )

    def test_combined_validation_reports_all_failures(self):
        source = self.table(
            {"id": "x", "age": "oops"}, {"id": "x", "age": "20"}, {"id": "y", "age": "18"}
        )
        result = self.run_node(
            "validate.rules",
            {
                "rules": [
                    {"field": "id", "check": "unique"},
                    {"field": "age", "check": "range", "min": "18", "max": "99"},
                ]
            },
            source,
        )
        self.assertEqual((len(result["valid"]), len(result["invalid"])), (1, 2))
        self.assertEqual(len(result["invalid"].records[0].issues), 2)
        for bad in (
            {"field": "id", "check": "regex"},
            {"field": "age", "check": "range", "min": True},
        ):
            with self.assertRaises(ValueError):
                self.registry.get("validate.rules").prepare_config({"rules": [bad]})
        classified = self.run_node(
            "rows.classify",
            {
                "rules": [
                    {"label": "adult", "conditions": [{"field": "age", "op": "gte", "value": "18"}]}
                ],
                "default": "unknown",
            },
            source,
        )["data"]
        self.assertEqual(
            [r.values["分类"] for r in classified.records], ["unknown", "adult", "adult"]
        )

    def test_codecs_route_errors_without_partial_updates_and_mask_short_values(self):
        source = self.table({"a": "aGk=", "b": "bad!"})
        result = self.run_node(
            "codec.fields", {"fields": ["a", "b"], "operation": "base64_decode"}, source
        )
        self.assertEqual(len(result["invalid"]), 1)
        self.assertEqual(result["invalid"].records[0].values["a"], "aGk=")
        self.assertEqual(result["invalid"].records[0].issues[0].field, "b")
        masked = self.run_node(
            "text.mask", {"fields": ["a"], "keep_start": 3, "keep_end": 4}, source
        )["data"]
        self.assertEqual(masked.records[0].values["a"], "****")

    def test_joins_expand_duplicates_keep_origins_and_do_not_match_empty_keys(self):
        left = self.table({"k": "x", "v": "a"}, {"k": "x", "v": "b"}, {"k": "", "v": "c"})
        right = Table.from_rows(
            ("k", "v"), [{"k": "x", "v": "1"}, {"k": "x", "v": "2"}, {"k": "", "v": "3"}], "right"
        )
        result = self.run_node(
            "tables.join",
            {"left_keys": ["k"], "right_keys": ["k"], "how": "full"},
            left=left,
            right=right,
        )["data"]
        self.assertEqual(len(result), 6)
        self.assertEqual(len(result.records[0].origins), 2)
        self.assertEqual(result.columns, ("k", "v", "k_right", "v_right"))
        with self.assertRaises(ValueError):
            self.run_node(
                "tables.join",
                {"left_keys": ["k"], "right_keys": ["k"], "max_rows": 2},
                left=left,
                right=right,
            )

    def test_merge_aggregate_compare_duplicate_counts(self):
        left = self.table({"g": "x", "n": "0.1"}, {"g": "x", "n": "0.2"})
        right = self.table({"g": "y", "other": "z"})
        merged = self.run_node("rows.merge", {"schema": "union"}, left=left, right=right)["data"]
        self.assertEqual(merged.records[-1].values["n"], "")
        aggregate = self.run_node(
            "group.aggregate",
            {
                "group_by": ["g"],
                "measures": [
                    {"op": "sum", "field": "n", "output": "sum"},
                    {"op": "mean", "field": "n", "output": "mean"},
                ],
            },
            left,
        )["data"]
        self.assertEqual(
            dict(aggregate.records[0].values), {"g": "x", "sum": "0.3", "mean": "0.15"}
        )
        answer = self.table({"k": "a"}, {"k": "a"}, {"k": "b"})
        candidate = self.table({"k": "a"}, {"k": "b"}, {"k": "b"})
        result = self.run_node("tables.compare", {}, answer=answer, candidate=candidate)
        self.assertEqual([len(result[p]) for p in ("matched", "missing", "extra")], [2, 1, 1])
        self.assertEqual(result["summary"].records[0].values["得分"], "0.5")

    def test_datetime_microseconds(self):
        source = self.table({"a": "2026-01-01T00:00:00.100001", "b": "2026-01-01T00:00:00"})
        result = self.run_node(
            "datetime.transform",
            {"field": "a", "other": "b", "operation": "difference_seconds"},
            source,
        )["data"]
        self.assertEqual(result.records[0].values["时间结果"], "0.100001")

    def test_jsonl_precision_missing_null_nested_and_line_origin(self):
        (self.root / "data.jsonl").write_text(
            '\n{"id":"0001","n":0.1234567890123456789,"nested":{"x":1.25},"v":null}\n{"id":"0002"}\n',
            encoding="utf-8",
        )
        table = self.run_node("json.read", {"path": "data.jsonl"})["data"]
        self.assertEqual(table.records[0].values["n"], "0.1234567890123456789")
        self.assertEqual(table.records[0].values["nested"], '{"x":1.25}')
        self.assertEqual(table.records[0].values["v"], "null")
        self.assertEqual(table.records[1].values["v"], "")
        self.assertEqual(table.records[0].origins[0].line, 2)
        self.run_node("json.write", {"path": "out.jsonl", "format": "jsonl"}, table)
        self.assertEqual(len((self.root / "out.jsonl").read_text(encoding="utf-8").splitlines()), 2)

    def test_text_reader_preserves_whitespace_and_physical_line_numbers(self):
        (self.root / "a.log").write_bytes(b"  abc  \r\n\r\nxyz\n")
        table = self.run_node("text.read", {"path": "a.log", "skip_empty": True})["data"]
        self.assertEqual(
            [dict(r.values) for r in table.records],
            [{"行号": "1", "内容": "  abc  "}, {"行号": "3", "内容": "xyz"}],
        )

    def test_xlsx_text_numbers_formulas_and_long_cell_rejection(self):
        from openpyxl import Workbook, load_workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["id", "formula", "code"])
        sheet.append(["123456789012345678", "=1+1", 12])
        sheet["C2"].number_format = "0000"
        workbook.save(self.root / "in.xlsx")
        workbook.close()
        table = self.run_node("xlsx.read", {"path": "in.xlsx"})["data"]
        self.assertEqual(
            dict(table.records[0].values),
            {"id": "123456789012345678", "formula": "=1+1", "code": "0012"},
        )
        for mode in ("reject", "cached"):
            with self.assertRaises(ValueError):
                self.run_node("xlsx.read", {"path": "in.xlsx", "formulas": mode})
        self.run_node("xlsx.write", {"path": "out.xlsx"}, table)
        output = load_workbook(self.root / "out.xlsx")
        try:
            self.assertEqual(output.active["B2"].data_type, "s")
            self.assertEqual(output.active["A2"].value, "123456789012345678")
        finally:
            output.close()
        old = (self.root / "out.xlsx").read_bytes()
        with self.assertRaises(ValueError):
            self.run_node(
                "xlsx.write",
                {"path": "out.xlsx", "overwrite": True},
                self.table({"a": "x" * 32768}),
            )
        self.assertEqual((self.root / "out.xlsx").read_bytes(), old)

    def test_cancellation_and_workspace_boundary(self):
        event = Event()
        event.set()
        self.context.cancel_event = event
        with self.assertRaises(InterruptedError):
            self.run_node("text.clean", {"fields": ["a"]}, self.table({"a": "x"}))
        self.context.workspace_root = self.root
        with self.assertRaises(ValueError):
            self.context.resolve_path("../outside.csv")


if __name__ == "__main__":
    unittest.main()
