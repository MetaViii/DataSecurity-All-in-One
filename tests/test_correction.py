import unittest
from pathlib import Path

from datasecurity import RunContext, Table
from datasecurity.builtin import create_registry


def table(*rows):
    return Table.from_rows(tuple(rows[0]) if rows else ("id", "value"), rows)


class CorrectionTests(unittest.TestCase):
    def test_threshold_uses_exact_fraction_before_display_rounding(self):
        expected = table(
            {"id": "1", "value": "a"}, {"id": "2", "value": "b"}, {"id": "3", "value": "c"}
        )
        output = self.run_node(
            "tables.score",
            {"threshold": "0.33333333333333333333333333332"},
            answer=expected,
            candidate=table({"id": "1", "value": "a"}),
        )
        self.assertEqual(output["summary"].records[0].values["达标"], "是")

    def setUp(self):
        self.registry = create_registry()
        self.context = RunContext(Path.cwd(), node_id="test")

    def run_node(self, id, config, **inputs):
        plugin = self.registry.get(id)
        return plugin.run(inputs, plugin.prepare_config(config), self.context)

    def test_keyed_cell_scoring_counts_wrong_missing_and_extra(self):
        expected = table(
            {"id": "01", "name": "A", "n": "10"},
            {"id": "02", "name": "B", "n": "20"},
            {"id": "03", "name": "C", "n": "30"},
        )
        candidate = table(
            {"id": "02", "name": "B", "n": "20"},
            {"id": "01", "name": "A", "n": "11"},
            {"id": "04", "name": "D", "n": "40"},
        )
        output = self.run_node(
            "tables.score",
            {"mode": "keyed", "keys": ["id"], "metric": "cell", "threshold": "0.375"},
            answer=expected,
            candidate=candidate,
        )
        summary = output["summary"].records[0].values
        self.assertEqual(summary["正确率"], "0.375")
        self.assertEqual(summary["达标"], "是")
        self.assertEqual(summary["正确行"], "1")
        self.assertEqual(
            (len(output["missing"]), len(output["extra"]), len(output["differences"])), (1, 1, 5)
        )
        mismatch = output["differences"].records[0]
        self.assertEqual(mismatch.values["标准值"], "10")
        self.assertEqual(mismatch.values["提交值"], "11")
        self.assertEqual(len(mismatch.origins), 2)

    def test_multiset_preserves_duplicates_and_penalizes_wrong_rows(self):
        expected = table(
            {"id": "01", "value": "A"}, {"id": "01", "value": "A"}, {"id": "02", "value": "B"}
        )
        candidate = table(
            {"id": "01", "value": "A"},
            {"id": "01", "value": "A"},
            {"id": "01", "value": "A"},
            {"id": "03", "value": "C"},
        )
        output = self.run_node("tables.score", {}, answer=expected, candidate=candidate)
        self.assertEqual(output["summary"].records[0].values["正确率"], "0.4")
        self.assertEqual(len(output["fields"]), 0)
        with self.assertRaisesRegex(ValueError, "唯一"):
            self.run_node(
                "tables.score",
                {"mode": "keyed", "keys": ["id"]},
                answer=expected,
                candidate=candidate,
            )

    def test_scoring_position_empty_and_explicit_normalization(self):
        expected = table({"id": "001", "value": "A"})
        candidate = table({"id": "001", "value": " a "})
        output = self.run_node(
            "tables.score",
            {"mode": "position", "strip": True, "ignore_case": True},
            answer=expected,
            candidate=candidate,
        )
        self.assertEqual(output["summary"].records[0].values["正确率"], "1")
        self.assertEqual(candidate.records[0].values["value"], " a ")
        empty = Table(expected.columns, ())
        self.assertEqual(
            self.run_node("tables.score", {}, answer=empty, candidate=empty)["summary"]
            .records[0]
            .values["正确率"],
            "1",
        )
        self.assertEqual(
            self.run_node("tables.score", {}, answer=empty, candidate=candidate)["summary"]
            .records[0]
            .values["正确率"],
            "0",
        )
        leading = table({"id": "1", "value": "A"})
        self.assertEqual(
            self.run_node(
                "tables.score",
                {"mode": "keyed", "keys": ["id"]},
                answer=expected,
                candidate=leading,
            )["summary"]
            .records[0]
            .values["正确率"],
            "0",
        )

    def test_fuzzy_suggests_by_default_and_only_applies_unique_best(self):
        source = table(
            {"id": "001", "value": "运惟"},
            {"id": "002", "value": "开发"},
            {"id": "003", "value": ""},
        )
        reference = table({"标准": "运维"}, {"标准": "开发"})
        config = {"field": "value", "reference_field": "标准"}
        suggested = self.run_node("tables.fuzzy_lookup", config, data=source, reference=reference)
        self.assertEqual(suggested["data"].records[0].values["value"], "运惟")
        self.assertEqual(len(suggested["review"]), 2)
        fixed = self.run_node(
            "tables.fuzzy_lookup", {**config, "apply": True}, data=source, reference=reference
        )
        self.assertEqual([r.values["value"] for r in fixed["data"].records], ["运维", "开发", ""])
        self.assertEqual(len(fixed["data"].records[0].changes), 1)
        self.assertEqual(len(fixed["review"]), 1)

    def test_fuzzy_ties_groups_and_comparison_limit(self):
        source = table({"id": "1", "value": "abx", "group": "x"})
        reference = table(
            {"标准": "abc", "group": "x"},
            {"标准": "abd", "group": "x"},
            {"标准": "abx", "group": "y"},
        )
        config = {"field": "value", "reference_field": "标准", "group_by": ["group"], "apply": True}
        output = self.run_node("tables.fuzzy_lookup", config, data=source, reference=reference)
        self.assertEqual(len(output["review"]), 1)
        self.assertEqual(output["data"].records[0].values["value"], "abx")
        self.assertTrue(all(r.values["唯一最优"] == "否" for r in output["suggestions"].records))
        with self.assertRaisesRegex(ValueError, "max_comparisons"):
            self.run_node(
                "tables.fuzzy_lookup",
                {**config, "max_comparisons": 1},
                data=source,
                reference=reference,
            )

    def test_fuzzy_normalization_does_not_collapse_distinct_reference_values(self):
        source = table({"id": "1", "value": " a "})
        reference = table({"标准": "Ａ"}, {"标准": "A"})
        output = self.run_node(
            "tables.fuzzy_lookup",
            {
                "field": "value",
                "reference_field": "标准",
                "normalization": "NFKC",
                "ignore_case": True,
                "apply": True,
            },
            data=source,
            reference=reference,
        )
        self.assertEqual(len(output["review"]), 1)
        self.assertEqual(output["data"].records[0].values["value"], " a ")

    def test_patch_rolls_back_entire_row_if_one_original_value_is_stale(self):
        source = table({"id": "001", "a": "old", "b": "current"})
        patches = table(
            {"id": "001", "字段": "a", "原值": "old", "新值": "new", "理由": "检查"},
            {"id": "001", "字段": "b", "原值": "stale", "新值": "new", "理由": "检查"},
        )
        output = self.run_node("table.patch", {"keys": ["id"]}, data=source, patches=patches)
        self.assertEqual(dict(output["data"].records[0].values), dict(source.records[0].values))
        self.assertEqual(len(output["rejected"]), 2)

    def test_patch_preserves_keys_empty_values_and_audit_reason(self):
        source = table({"id": "001", "value": "old"}, {"id": "1", "value": "other"})
        patches = table(
            {"id": "001", "字段": "value", "原值": "old", "新值": "", "理由": "已核实应为空"},
            {"id": "missing", "字段": "value", "原值": "old", "新值": "x", "理由": "检查"},
        )
        output = self.run_node("table.patch", {"keys": ["id"]}, data=source, patches=patches)
        self.assertEqual([r.values["value"] for r in output["data"].records], ["", "other"])
        self.assertEqual(output["data"].records[0].changes[0].reason, "已核实应为空")
        self.assertEqual(len(output["rejected"]), 1)
        with self.assertRaises(ValueError):
            self.run_node(
                "table.patch",
                {"keys": ["id"]},
                data=table({"id": "1", "value": "a"}, {"id": "1", "value": "b"}),
                patches=patches,
            )

    def test_duplicate_or_key_patches_never_overwrite(self):
        source = table({"id": "001", "value": "old"})
        row = {"id": "001", "字段": "value", "原值": "old", "新值": "new", "理由": "check"}
        output = self.run_node(
            "table.patch", {"keys": ["id"]}, data=source, patches=table(row, row)
        )
        self.assertEqual(len(output["rejected"]), 2)
        output = self.run_node(
            "table.patch",
            {"keys": ["id"]},
            data=source,
            patches=table({**row, "字段": "id", "原值": "001"}),
        )
        self.assertEqual(len(output["rejected"]), 1)


if __name__ == "__main__":
    unittest.main()
