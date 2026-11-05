"""Optional original-attachment checks, including a fixture-specific independent packet oracle.

The small oracle only handles the pinned Ethernet/IPv4/TCP captures here. It is not
the application's capture reader and does not replace TShark for arbitrary traffic.
"""

from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re
import shutil
import struct
import tempfile
import unittest

from datasecurity.builtin import create_registry
from datasecurity.core.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "work/contest-round2/input"
PREFIXES = set(
    "734 735 736 737 738 739 747 748 750 751 752 757 758 759 772 778 782 783 784 787 788 795 798 730 731 732 740 745 746 755 756 766 767 771 775 776 785 786 796 733 749 753 773 774 777 780 781 789 790 791 793 799".split()
)


def fixture_http_bodies(path):
    raw = path.read_bytes()
    cursor, flows = 0, defaultdict(dict)
    endian = "<"
    while cursor < len(raw):
        if raw[cursor : cursor + 4] == b"\x0a\x0d\x0d\x0a":
            endian = "<" if raw[cursor + 8 : cursor + 12] == b"\x4d\x3c\x2b\x1a" else ">"
        kind, length = struct.unpack_from(endian + "II", raw, cursor)
        if length < 12 or cursor + length > len(raw):
            raise ValueError("invalid fixture block")
        if kind == 6:
            captured = struct.unpack_from(endian + "I", raw, cursor + 20)[0]
            packet = raw[cursor + 28 : cursor + 28 + captured]
            if packet[12:14] == b"\x08\x00" and len(packet) >= 54:
                ip = packet[14:]
                ip_header = (ip[0] & 15) * 4
                ip_length = int.from_bytes(ip[2:4], "big")
                if ip[9] == 6:
                    tcp = ip[ip_header:ip_length]
                    tcp_header = (tcp[12] >> 4) * 4
                    payload = tcp[tcp_header:]
                    if payload:
                        direction = (ip[12:20], tcp[:4])
                        sequence = int.from_bytes(tcp[4:8], "big")
                        if sequence in flows[direction] and flows[direction][sequence] != payload:
                            raise ValueError("conflicting fixture segment")
                        flows[direction][sequence] = payload
        cursor += length
    bodies = []
    for segments in flows.values():
        content, end = bytearray(), None
        for sequence, payload in sorted(segments.items()):
            if end is not None and sequence > end:
                raise ValueError("fixture stream has a gap")
            skip = max(0, end - sequence) if end is not None else 0
            content.extend(payload[skip:])
            end = max(end or 0, sequence + len(payload))
        for request in re.finditer(rb"(?:POST|PUT|PATCH) [^\r\n]+ HTTP/1\.[01]\r\n", content):
            start = content.find(b"\r\n\r\n", request.start())
            header = content[request.start() : start]
            size = re.search(rb"(?im)^Content-Length:\s*([0-9]+)\s*$", header)
            if start >= 0 and size:
                count = int(size[1])
                body = bytes(content[start + 4 : start + 4 + count])
                if len(body) != count:
                    raise ValueError("fixture body truncated")
                bodies.append(body.decode("utf-8"))
    return bodies


def checksum(value):
    if not re.fullmatch(r"[0-9]{17}[0-9Xx]", value):
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    residue = sum(int(value[i]) * weights[i] for i in range(17)) % 11
    return value[-1].upper() == "10X98765432"[residue]


def valid_phone(value):
    return bool(re.fullmatch("[0-9]{11}", value)) and value[:3] in PREFIXES


class Round2Tests(unittest.TestCase):
    def run_case(self, case):
        if not (INPUT / case).exists():
            self.skipTest("Run python scripts/contest_round2.py --fetch for original attachments")
        definition = json.loads(
            (ROOT / f"examples/ctf_real_{case}.json").read_text(encoding="utf-8")
        )
        return Pipeline(create_registry()).run(definition, base_dir=ROOT / "examples", preview=True)

    def test_original_ycb_csv_and_published_reuse_answer(self):
        result = self.run_case("ycb24_analysis")
        self.assertEqual(len(result.tables["realign"]["valid"]), 10000)
        self.assertEqual(
            result.tables["flag"]["data"].records[0].values["flag"],
            "flag{518a8b1f87c23d94c1be372efd0f0f30}",
        )
        # Ten organizer-supplied example rows supply an independent column-layout check.
        example = INPUT / "ycb24_analysis/example_input.csv"
        definition = json.loads(
            (ROOT / "examples/ctf_real_ycb24_analysis.json").read_text(encoding="utf-8")
        )
        definition["nodes"][0]["config"]["path"] = str(example)
        sample = Pipeline(create_registry()).run(
            definition, base_dir=ROOT / "examples", target="submission_columns", preview=True
        )
        with (example.parent / "example_answer.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            expected = list(csv.DictReader(handle))
        self.assertEqual(
            [dict(r.values) for r in sample.tables["submission_columns"]["data"].records], expected
        )

    def test_zhejiang_csv_all_rows_and_checksum_against_direct_source(self):
        result = self.run_case("zj24_classify1")
        with (INPUT / "zj24_classify1/data.csv").open(encoding="utf-8-sig", newline="") as handle:
            original = list(csv.DictReader(handle))
        expected = []
        for row in original:
            value = row["数据值"]
            category = (
                "身份证号"
                if checksum(value)
                else (
                    "手机号"
                    if valid_phone(value)
                    else (
                        "姓名"
                        if value.isalpha() and all("\u4e00" <= c <= "\u9fff" for c in value)
                        else "未识别"
                    )
                )
            )
            expected.append((category, value))
        actual = result.tables["answer"]["data"]
        self.assertEqual([(r.values["类型"], r.values["数据值"]) for r in actual.records], expected)
        self.assertEqual(
            Counter((r.values["类型"], r.values["数据值"]) for r in actual.records),
            Counter(expected),
        )
        self.assertEqual(len(actual), 20000)
        self.assertEqual(
            Counter(k for k, _ in expected), {"身份证号": 6787, "姓名": 6637, "手机号": 6576}
        )

    @unittest.skipUnless(shutil.which("tshark"), "optional TShark not installed")
    def test_ycb_garbage_rows_against_independent_capture_and_rule_oracle(self):
        result = self.run_case("ycb24_traffic")
        bodies = fixture_http_bodies(INPUT / "ycb24_traffic/data.pcapng")
        self.assertEqual(len(bodies), 8000)
        expected = []
        fields = ["username", "name", "sex", "birth", "idcard", "phone"]
        for body in bodies:
            row = json.loads(body)
            identity = row["idcard"]
            valid = (
                bool(re.fullmatch("[A-Za-z0-9]+", row["username"]))
                and all("\u4e00" <= c <= "\u9fff" for c in row["name"])
                and bool(row["name"])
                and checksum(identity)
                and valid_phone(row["phone"])
            )
            valid = (
                valid
                and row["sex"] == ("男" if int(identity[-2]) % 2 else "女")
                and row["birth"] == identity[6:14]
            )
            if not valid:
                expected.append(tuple(str(row[f]) for f in fields))
        actual = Counter(
            tuple(r.values[f] for f in fields) for r in result.tables["answer"]["data"].records
        )
        self.assertEqual(actual, Counter(expected))
        self.assertEqual(sum(actual.values()), 294)

    @unittest.skipUnless(shutil.which("tshark"), "optional TShark not installed")
    def test_zhejiang_capture_categories_against_independent_body_scan(self):
        result = self.run_case("zj24_classify2")
        bodies = fixture_http_bodies(INPUT / "zj24_classify2/data.pcapng")
        self.assertEqual(len(bodies), 5231)
        expected = []
        for body in bodies:
            for match in re.finditer(
                r"(?<![0-9])[0-9]{6}([- ]?)[0-9]{8}\1[0-9]{3}[0-9Xx](?![0-9])", body
            ):
                value = match[0].replace(" ", "").replace("-", "")
                if checksum(value):
                    expected.append(("idcard", value))
            for match in re.finditer(r"(?<![0-9])[0-9]{3}([- ]?)[0-9]{4}\1[0-9]{4}(?![0-9])", body):
                value = match[0].replace(" ", "").replace("-", "")
                if valid_phone(value):
                    expected.append(("phone", value))
            for token in re.findall(r"[0-9.]+", body):
                octets = token.split(".")
                if len(octets) == 4 and all(
                    p.isascii() and p.isdigit() and len(p) <= 3 and 0 <= int(p) <= 255
                    for p in octets
                ):
                    expected.append(("ip", token))
        actual = Counter(
            (r.values["category"], r.values["value"])
            for r in result.tables["answer"]["data"].records
        )
        self.assertEqual(actual, Counter(expected))
        self.assertEqual(sum(actual.values()), 4221)

    def test_correction_example_and_xlsx_roundtrip_preserve_leading_zero_keys(self):
        definition = json.loads((ROOT / "examples/ctf_correction.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corrected.xlsx"
            definition["nodes"][-1]["config"]["path"] = str(path)
            result = Pipeline(create_registry()).run(definition, base_dir=ROOT / "examples")
            self.assertEqual(len(result.tables["fuzzy"]["review"]), 3)
            self.assertEqual(len(result.tables["patch"]["rejected"]), 0)
            self.assertEqual(result.tables["score"]["summary"].records[0].values["正确率"], "1")
            read = {
                "version": 1,
                "nodes": [{"id": "read", "plugin": "xlsx.read", "config": {"path": str(path)}}],
            }
            restored = Pipeline(create_registry()).run(read, base_dir=ROOT)
            self.assertEqual(
                [dict(r.values) for r in restored.tables["read"]["data"].records],
                [dict(r.values) for r in result.tables["patch"]["data"].records],
            )
            self.assertEqual(restored.tables["read"]["data"].records[0].values["编号"], "0001")
