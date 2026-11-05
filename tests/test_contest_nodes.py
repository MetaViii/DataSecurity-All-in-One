import base64
import tempfile
import unittest
from pathlib import Path

from datasecurity import RunContext, Table
from datasecurity.builtin import create_registry


class ContestNodesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = RunContext(self.root, node_id="test", workspace_root=self.root)
        self.registry = create_registry()

    def run_node(self, id, config, table=None):
        plugin = self.registry.get(id)
        return plugin.run(
            {"data": table} if table is not None else {},
            plugin.prepare_config(config),
            self.context,
        )

    def table(self, *rows):
        return Table.from_rows(rows[0].keys(), rows)

    def test_realign_unique_ambiguous_and_duplicate_cells(self):
        source = self.table({"a": "Jane", "b": "001"}, {"a": "123", "b": "456"})
        out = self.run_node(
            "columns.realign", {"rules": {"id": "[0-9]+", "name": "[A-Za-z0-9]+"}}, source
        )
        self.assertEqual(dict(out["valid"].records[0].values), {"id": "001", "name": "Jane"})
        self.assertEqual(dict(out["invalid"].records[0].values), dict(source.records[1].values))
        self.assertIn("多个", out["invalid"].records[0].issues[0].message)
        same = self.table({"a": "same", "b": "same"})
        self.assertEqual(
            len(
                self.run_node("columns.realign", {"rules": {"x": "same", "y": "same"}}, same)[
                    "valid"
                ]
            ),
            1,
        )
        self.assertEqual(out["valid"].records[0].origins, source.records[0].origins)

    def test_realign_limits_never_pick_first_unproven_answer(self):
        out = self.run_node(
            "columns.realign",
            {"rules": {"x": ".*", "y": ".*"}, "max_states": 1},
            self.table({"a": "1", "b": "2"}),
        )
        self.assertEqual(len(out["valid"]), 0)
        self.assertIn("上限", out["invalid"].records[0].issues[0].message)

    def test_log_grouping_preserves_preamble_and_start_lines(self):
        (self.root / "input.log").write_text(
            "noise\nSTART a\nbody\nSTART b\nlast\n", encoding="utf-8"
        )
        out = self.run_node("text.records", {"path": "input.log", "start_pattern": "^START"})
        self.assertEqual(
            [r.values["内容"] for r in out["data"].records], ["START a\nbody", "START b\nlast"]
        )
        self.assertEqual([r.origins[0].line for r in out["data"].records], [2, 4])
        self.assertEqual(out["unmatched"].records[0].values["内容"], "noise")
        with self.assertRaises(ValueError):
            self.run_node(
                "text.records", {"path": "input.log", "start_pattern": "START", "max_chars": 3}
            )

    def test_last_regex_occurrence_does_not_change_first_default(self):
        source = self.table({"v": "password=a password=b"})
        config = {"field": "v", "pattern": r"password=(\w)", "output": "result"}
        self.assertEqual(
            self.run_node("text.extract", config, source)["data"].records[0].values["result"], "a"
        )
        self.assertEqual(
            self.run_node("text.extract", {**config, "occurrence": "last"}, source)["data"]
            .records[0]
            .values["result"],
            "b",
        )

    def test_serialization_exact_quoting_newlines_and_raw_output(self):
        source = self.table({"id": "001", "name": 'a,"b"'})
        out = self.run_node(
            "table.serialize", {"line_ending": "crlf", "trailing_blank_lines": 1}, source
        )["data"]
        expected = 'id,name\r\n001,"a,""b"""\r\n\r\n'
        self.assertEqual(out.records[0].values["提交内容"], expected)
        self.run_node(
            "text.write", {"path": "answer.csv", "fields": ["提交内容"], "raw": True}, out
        )
        self.assertEqual((self.root / "answer.csv").read_bytes(), expected.encode())

    def test_collect_preserves_order_duplicates_and_empty_table(self):
        source = self.table({"id": "002"}, {"id": "001"}, {"id": "002"})
        self.assertEqual(
            self.run_node("rows.collect", {"field": "id"}, source)["data"]
            .records[0]
            .values["拼接结果"],
            "002_001_002",
        )
        self.assertEqual(
            self.run_node("rows.collect", {"field": "id"}, source.with_records([]))["data"]
            .records[0]
            .values["拼接结果"],
            "",
        )

    def test_explicit_identity_checksum_profile(self):
        stem = "11010519491231000"
        weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
        value = stem + "10X98765432"[sum(int(x) * w for x, w in zip(stem, weights)) % 11]
        source = self.table({"id": value})
        self.assertEqual(
            len(self.run_node("validate.identity", {"field": "id"}, source)["invalid"]), 1
        )
        self.assertEqual(
            len(
                self.run_node(
                    "validate.identity", {"field": "id", "check_sequence": False}, source
                )["valid"]
            ),
            1,
        )

    def test_signature_verifies_original_message_and_rejects_tamper_missing_key(self):
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding, rsa
        except ImportError:
            self.skipTest("optional crypto dependency unavailable")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        (self.root / "1.pem").write_bytes(
            key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
        signature = base64.b64encode(
            key.sign(b"hello", padding.PKCS1v15(), hashes.SHA256())
        ).decode()
        source = self.table(
            {"id": "1", "message": "hello", "sig": signature},
            {"id": "1", "message": "changed", "sig": signature},
            {"id": "missing", "message": "hello", "sig": signature},
        )
        out = self.run_node(
            "validate.signature",
            {"message_field": "message", "signature_field": "sig", "key_path": "{id}.pem"},
            source,
        )
        self.assertEqual((len(out["valid"]), len(out["invalid"])), (1, 2))
        self.assertTrue(all(r.issues for r in out["invalid"].records))
        outside = self.table({"id": "../outside", "message": "hello", "sig": signature})
        self.assertIn(
            "工作区",
            self.run_node(
                "validate.signature",
                {"message_field": "message", "signature_field": "sig", "key_path": "{id}.pem"},
                outside,
            )["invalid"]
            .records[0]
            .issues[0]
            .message,
        )
