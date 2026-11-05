import tempfile
import unittest
from pathlib import Path
from threading import Event

from datasecurity import RunContext, Table
from datasecurity.builtin import create_registry


class AdvancedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.context = RunContext(Path(self.temp.name), node_id="test")
        self.registry = create_registry()

    def table(self, *rows):
        return Table.from_rows(rows[0].keys(), rows)

    def run_node(self, id, config, data=None, **inputs):
        p = self.registry.get(id)
        return p.run(
            {**inputs, **({"data": data} if data is not None else {})},
            p.prepare_config(config),
            self.context,
        )

    def test_dictionary_normalization_and_unmatched_trace(self):
        source = self.table({"v": " A "}, {"v": "?"})
        out = self.run_node(
            "values.map",
            {"field": "v", "mapping": {"a": "甲"}, "strip": True, "ignore_case": True},
            source,
        )
        self.assertEqual(out["matched"].records[0].values["v"], "甲")
        self.assertEqual(out["unmatched"].records[0].values["v"], "?")
        self.assertTrue(out["unmatched"].records[0].issues)
        self.assertEqual(source.records[0].values["v"], " A ")
        with self.assertRaises(ValueError):
            self.run_node(
                "values.map",
                {"field": "v", "mapping": {"a": "甲", "A": "乙"}, "ignore_case": True},
                source,
            )

    def test_coalesce_number_explode_and_unpivot(self):
        source = self.table({"a": "", "b": "x,y"})
        result = self.run_node("values.coalesce", {"fields": ["a", "b"], "output": "pick"}, source)[
            "data"
        ]
        self.assertEqual(result.records[0].values["pick"], "x,y")
        result = self.run_node("rows.explode", {"field": "pick"}, result)["data"]
        result = self.run_node("rows.number", {"output": "n", "width": 3}, result)["data"]
        self.assertEqual([r.values["n"] for r in result.records], ["001", "002"])
        self.assertEqual(result.records[1].origins, source.records[0].origins)
        result = self.run_node("columns.unpivot", {"fields": ["a", "b"]}, result)["data"]
        self.assertEqual(len(result), 4)
        self.assertEqual(result.records[1].values["值"], "x,y")
        with self.assertRaises(ValueError):
            self.run_node("rows.explode", {"field": "b", "max_rows": 1}, source)

    def test_json_pointer_precision_duplicate_keys_and_no_partial_results(self):
        source = self.table(
            {"j": '{"a/b":[{"id":9007199254740993,"n":1.25}]}'}, {"j": '{"a":1,"a":2}'}
        )
        out = self.run_node(
            "json.extract",
            {"field": "j", "mapping": {"id": "/a~1b/0/id", "n": "/a~1b/0/n"}},
            source,
        )
        self.assertEqual(out["valid"].records[0].values["id"], "9007199254740993")
        self.assertEqual(out["invalid"].records[0].values["id"], "")
        self.assertIn("重复键", out["invalid"].records[0].issues[-1].message)

    def test_numbers_rounding_and_atomic_failure(self):
        source = self.table({"a": "1,234.565", "b": "25%"}, {"a": "1,23", "b": "50%"})
        out = self.run_node(
            "number.normalize",
            {"fields": ["a", "b"], "thousands": "comma", "percent": True, "places": 2},
            source,
        )
        self.assertEqual(dict(out["valid"].records[0].values), {"a": "1234.57", "b": "0.25"})
        self.assertEqual(dict(out["invalid"].records[0].values), dict(source.records[1].values))

    def test_template_disallows_expression_and_supports_literal_braces(self):
        source = self.table({"摘要": "abc"})
        out = self.run_node("text.template", {"template": "flag{{{摘要}}}"}, source)["data"]
        self.assertEqual(out.records[0].values["文本结果"], "flag{abc}")
        with self.assertRaises(ValueError):
            self.run_node("text.template", {"template": "{摘要.__class__}"}, source)

    def test_identity_checksum_date_gender_and_ascii(self):
        source = self.table(
            {"id": "11010519491231002x", "sex": "女"},
            {"id": "11010519491231002X", "sex": "男"},
            {"id": "１１０１０５１９４９１２３１００２X", "sex": "女"},
        )
        out = self.run_node("validate.identity", {"field": "id", "gender_field": "sex"}, source)
        self.assertEqual((len(out["valid"]), len(out["invalid"])), (1, 2))
        out = self.run_node(
            "validate.identity", {"field": "id", "reference_date": "1949-12-30"}, source
        )
        self.assertEqual(len(out["valid"]), 0)

    def test_luhn_rejects_corruption_unicode_and_zeros(self):
        source = self.table(
            *(
                {"card": v}
                for v in [
                    "4111111111111111",
                    "4111111111111112",
                    "0000000000000000",
                    "４１１１１１１１１１１１１１１１",
                ]
            )
        )
        out = self.run_node("validate.luhn", {"field": "card"}, source)
        self.assertEqual((len(out["valid"]), len(out["invalid"])), (1, 3))

    def test_xor_non_utf8_intermediate_and_atomic_failure(self):
        source = self.table({"a": "w6k=", "b": "!!!"})
        # The first decoded value succeeds, but the second failure must preserve both.
        out = self.run_node(
            "codec.xor", {"fields": ["a", "b"], "key": "00", "key_format": "hex"}, source
        )
        self.assertEqual(dict(out["invalid"].records[0].values), dict(source.records[0].values))
        out = self.run_node(
            "codec.xor",
            {"fields": ["a"], "key": "ff", "key_format": "hex", "output_format": "hex"},
            source,
        )
        self.assertEqual(out["valid"].records[0].values["a"], "3c56")

    def test_lookup_duplicate_keys_and_provenance(self):
        source = self.table({"id": "01", "name": ""}, {"id": "02", "name": "old"})
        ref = Table.from_rows(["id", "label"], [{"id": "01", "label": "A"}], source="reference.csv")
        out = self.run_node(
            "tables.lookup",
            {"keys": ["id"], "mapping": {"name": "label"}},
            data=source,
            reference=ref,
        )
        self.assertEqual(out["matched"].records[0].values["name"], "A")
        self.assertEqual(len(out["matched"].records[0].origins), 2)
        self.assertEqual(out["unmatched"].records[0].values["name"], "old")
        with self.assertRaises(ValueError):
            self.run_node(
                "tables.lookup",
                {"keys": ["id"], "mapping": {"name": "label"}},
                data=source,
                reference=ref.with_records((*ref.records, *ref.records)),
            )

    def test_profile_counts_empty_and_frequency_and_preserves_data(self):
        source = self.table({"v": " "}, {"v": "01"}, {"v": "01"})
        out = self.run_node("profile.summary", {}, source)
        self.assertIs(out["data"], source)
        row = out["summary"].records[0].values
        self.assertEqual((row["空值数"], row["唯一值数"], row["数值格式数"]), ("1", "2", "2"))

    def test_window_boundary_ties_unsorted_and_distinct(self):
        source = self.table(
            {"g": "x", "t": "2025-01-01T11:00:00", "user": "b"},
            {"g": "x", "t": "2025-01-01T10:00:00", "user": "a"},
            {"g": "x", "t": "2025-01-01T11:00:00", "user": "c"},
            {"g": "x", "t": "bad", "user": "d"},
        )
        out = self.run_node(
            "rows.window_count",
            {"time_field": "t", "group_by": ["g"], "distinct_field": "user"},
            source,
        )
        self.assertEqual([r.values["窗口数量"] for r in out["valid"].records], ["3", "1", "3"])
        self.assertEqual(len(out["invalid"]), 1)

    def test_population_outliers_zero_variance_and_invalid(self):
        source = self.table(*({"v": v} for v in ["100", "100", "100", "1000", "bad"]))
        out = self.run_node("stats.outliers", {"field": "v", "threshold": "1.5"}, source)
        self.assertEqual([r.values["v"] for r in out["outliers"].records], ["1000"])
        self.assertEqual((len(out["normal"]), len(out["invalid"])), (3, 1))

    def test_text_output_preview_guards_atomicity_and_cancel(self):
        source = self.table({"v": "a\nb"})
        with self.assertRaises(ValueError):
            self.run_node("text.write", {"path": "answer.txt", "fields": ["v"]}, source)
        self.assertFalse((self.context.base_dir / "answer.txt").exists())
        self.context.cancel_event = Event()
        self.context.cancel_event.set()
        with self.assertRaises(InterruptedError):
            self.run_node("rows.number", {}, source)

    def test_outlier_population_and_sample_conventions_are_distinct(self):
        source = self.table(*({"v": v} for v in ["0", "0", "0", "10"]))
        population = self.run_node(
            "stats.outliers", {"field": "v", "threshold": "1.6", "ddof": 0}, source
        )
        sample = self.run_node(
            "stats.outliers", {"field": "v", "threshold": "1.6", "ddof": 1}, source
        )
        self.assertEqual(len(population["outliers"]), 1)
        self.assertEqual(len(sample["outliers"]), 0)
