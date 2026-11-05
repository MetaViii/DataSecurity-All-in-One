"""Offline sample checks, not official contest scores or original-attachment replay."""

import json
import tempfile
import unittest
from pathlib import Path

from datasecurity.builtin import create_registry
from datasecurity.core.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = json.loads((ROOT / "examples/data/ctf_expected.json").read_text(encoding="utf-8"))


class RecipeTests(unittest.TestCase):
    def run_flow(self, name):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        definition = json.loads((ROOT / f"examples/ctf_{name}.json").read_text(encoding="utf-8"))
        registry = create_registry()
        for node in definition["nodes"]:
            if registry.get(node["plugin"]).spec.kind == "output":
                node["config"]["path"] = str(Path(temp.name) / Path(node["config"]["path"]).name)
        result = Pipeline(registry).run(definition, base_dir=ROOT / "examples")
        return result

    def test_xor_exact_cells_and_invalid_original(self):
        r = self.run_flow("xor")
        self.assertEqual(
            [dict(row.values) for row in r.tables["decode"]["valid"].records], EXPECTED["xor"]
        )
        self.assertEqual(r.tables["decode"]["invalid"].records[0].values["username"], "***bad***")

    def test_identity_order_and_rejection(self):
        r = self.run_flow("identity")
        for port in ["valid", "invalid"]:
            self.assertEqual(
                [row.values["编号"] for row in r.tables["check"][port].records],
                EXPECTED[f"identity_{port}"],
            )

    def test_order_windows_amount_and_checksum(self):
        r = self.run_flow("orders")
        self.assertEqual(
            [row.values["一小时用户数"] for row in r.tables["window"]["valid"].records],
            EXPECTED["orders_counts"],
        )
        self.assertEqual(
            [row.values["订单"] for row in r.tables["amount"]["outliers"].records],
            EXPECTED["orders_amount"],
        )
        self.assertEqual(
            [row.values["订单"] for row in r.tables["card"]["invalid"].records],
            EXPECTED["orders_invalid"],
        )

    def test_lookup_exact_submission_bytes_and_unmatched(self):
        r = self.run_flow("lookup")
        answer = next(path for path in r.context.output_paths if path.name == "lookup_answer.txt")
        self.assertEqual(answer.read_bytes(), EXPECTED["lookup_text"].encode())
        self.assertEqual(
            [row.values["编号"] for row in r.tables["lookup"]["unmatched"].records], ["003"]
        )
