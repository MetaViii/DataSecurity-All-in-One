import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from datasecurity import RunContext, Table
from datasecurity.builtin import create_registry


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = RunContext(self.root, node_id="test", workspace_root=self.root)
        self.registry = create_registry()

    def run_node(self, id, config, **inputs):
        plugin = self.registry.get(id)
        return plugin.run(inputs, plugin.prepare_config(config), self.context)

    def test_regex_boundaries_capture_groups_overlap_and_source(self):
        source = Table.from_rows(
            ("body",), [{"body": "bad2127.0.0.1 x127.0.0.1x 123456"}, {"body": "nothing"}]
        )
        config = {
            "field": "body",
            "rules": [
                {"label": "ip", "pattern": r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])"},
                {"label": "digits", "pattern": r" (123456)", "group": 1},
                {"label": "short", "pattern": "234"},
            ],
        }
        output = self.run_node("text.find_all", config, data=source)
        self.assertEqual(
            [(r.values["category"], r.values["value"]) for r in output["data"].records],
            [("ip", "127.0.0.1"), ("digits", "123456")],
        )
        self.assertEqual(output["data"].records[0].origins, source.records[0].origins)
        self.assertEqual(len(output["unmatched"]), 1)
        self.assertEqual(
            len(self.run_node("text.find_all", {**config, "overlap": "all"}, data=source)["data"]),
            3,
        )
        with self.assertRaisesRegex(ValueError, "max_matches"):
            self.run_node("text.find_all", {**config, "max_matches": 1}, data=source)

    @unittest.skipUnless(shutil.which("tshark"), "optional TShark not installed")
    def test_real_tshark_reassembles_split_body_and_retains_bad_encoding(self):
        body = json.dumps({"name": "测试"}, ensure_ascii=False).encode()
        request = (
            b"POST /ingest HTTP/1.1\r\nHost: test\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\n\r\n"
            + body
        )
        bad = b"POST /bad HTTP/1.1\r\nHost: test\r\nContent-Length: 1\r\n\r\n\xff"
        chunks = [
            (request[:-3], 1000, 12345),
            (request[-3:], 1000 + len(request) - 3, 12345),
            (bad, 2000, 12346),
        ]
        capture = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
        for index, (payload, seq, port) in enumerate(chunks):
            eth = bytes.fromhex("00112233445566778899aabb0800")
            ip = struct.pack(
                "!BBHHHBBH4s4s",
                0x45,
                0,
                40 + len(payload),
                index,
                0x4000,
                64,
                6,
                0,
                b"\x0a\x00\x00\x01",
                b"\x0a\x00\x00\x02",
            )
            tcp = struct.pack("!HHIIBBHHH", port, 80, seq, 1, 0x50, 0x18, 65535, 0, 0)
            packet = eth + ip + tcp + payload
            capture += struct.pack("<IIII", index + 1, 0, len(packet), len(packet)) + packet
        (self.root / "capture.pcap").write_bytes(capture)
        output = self.run_node("pcap.http", {"path": "capture.pcap"})
        self.assertEqual(len(output["data"]), 1)
        self.assertEqual(output["data"].records[0].values["正文"], body.decode())
        self.assertEqual(output["data"].records[0].values["URI"], "/ingest")
        self.assertEqual(len(output["invalid"]), 1)
        self.assertEqual(output["invalid"].records[0].values["正文"], "ff")
