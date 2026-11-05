"""Optional full-size original attachment regression. No downloads during tests."""

import importlib.util
import json
from pathlib import Path
import unittest

from datasecurity.builtin import create_registry
from datasecurity.core.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[1]


class RealCTFTests(unittest.TestCase):
    def test_original_attachments_match_three_published_flags(self):
        if not (ROOT / "work/real-ctf/input/log/apache2/error.log").exists():
            self.skipTest("Run python scripts/real_ctf.py --fetch to enable original attachments")
        if importlib.util.find_spec("cryptography") is None:
            self.skipTest("Optional cryptography dependency unavailable")
        expected = {
            "analysis": "518a8b1f87c23d94c1be372efd0f0f30",
            "cleaning": "93767ebcb98095b0cd05b04d9b42e845",
            "log": "de95bf79eace2722b90fbecc35cab2ed",
        }
        for name, digest in expected.items():
            with self.subTest(case=name):
                definition = json.loads(
                    (ROOT / f"examples/ctf_real_{name}.json").read_text(encoding="utf-8")
                )
                result = Pipeline(create_registry()).run(
                    definition, base_dir=ROOT / "examples", preview=True
                )
                self.assertEqual(
                    result.tables["flag"]["data"].records[0].values["flag"], f"flag{{{digest}}}"
                )
                if name == "analysis":
                    self.assertEqual(len(result.tables["realign"]["valid"]), 10000)
                if name == "cleaning":
                    self.assertEqual(len(result.tables["sort"]["data"]), 100)
                if name == "log":
                    self.assertEqual(len(result.tables["identity"]["valid"]), 2000)

    def test_strict_log_rule_documents_the_one_row_disagreement(self):
        if not (ROOT / "work/real-ctf/input/log/apache2/error.log").exists():
            self.skipTest("original log not downloaded")
        definition = json.loads(
            (ROOT / "examples/ctf_real_log_strict.json").read_text(encoding="utf-8")
        )
        result = Pipeline(create_registry()).run(
            definition, base_dir=ROOT / "examples", preview=True
        )
        self.assertEqual(len(result.tables["identity"]["valid"]), 1999)
        self.assertEqual(
            result.tables["flag"]["data"].records[0].values["flag"],
            "flag{7558fbfa35dca8de48fe793f13f11419}",
        )
