"""Replay original 2024 Zhejiang/YCB attachments; report evidence without claiming online scores."""

import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from datasecurity.builtin import create_registry
from datasecurity.core.pipeline import Pipeline
from scripts.real_ctf import PHONE, flows as first_flows, n

BASE = ROOT / "work/contest-round2"
SOURCES = {
    "ycb24_analysis": (
        "2024-YCB-Undergraduate",
        "v1.0",
        "Data_Security-data-analy1.zip",
        "e068542b63ce69b13fbf0e8a5ee1bbcfff7b4c39466da0ffaa00fa8cdb6dc34c",
    ),
    "ycb24_traffic": (
        "2024-YCB-Undergraduate",
        "v1.0",
        "Data_Security-data-analy2.zip",
        "fe37c566fd98f9fc39085b82bcf3425d6524fbbd6498c4deb9abcc97fffdc2d1",
    ),
    "zj24_classify1": (
        "2024-zjsdxs-Finals",
        "v0.1",
        "Datasecurity-datasecurity_classify1.zip",
        "07856c23b94e92418381a14a674e2031cc62787c4c5c45704b8ba42435b594dc",
    ),
    "zj24_classify2": (
        "2024-zjsdxs-Finals",
        "v0.1",
        "Datasecurity-datasecurity_classify2.zip",
        "3ba61ed5ed2424f76e450886407c00962d2c75e09264b6d0af76ba53bbb673e7",
    ),
}
IDENTITY = {"check_date": False, "check_sequence": False, "check_region_format": False}
YCB_HEADERS = dict(
    zip(
        ("number", "username", "password", "name", "gender", "birth", "id", "phone"),
        ("编号", "用户名", "密码", "姓名", "性别", "出生日期", "身份证号", "手机号码"),
    )
)


def fetch():
    manifest = {}
    for case, (repo, release, filename, expected_hash) in SOURCES.items():
        url = f"https://github.com/CTF-Archives/{repo}/releases/download/{release}/{filename}"
        request = urllib.request.Request(
            url, headers={"User-Agent": "DataSecurity-Original-Replay/1"}
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected_hash:
            raise ValueError(f"{case}附件与固定哈希不一致，停止下载")
        folder = BASE / "input" / case
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(data)) as outer:
            nested = [i for i in outer.infolist() if i.filename.endswith(".zip")]
            if len(nested) != 1 or nested[0].file_size > 32 * 1024 * 1024:
                raise ValueError("原附件压缩包结构改变")
            with zipfile.ZipFile(io.BytesIO(outer.read(nested[0]))) as archive:
                selected = {}
                for info in archive.infolist():
                    basename = info.filename.rsplit("/", 1)[-1]
                    target = None
                    if basename in {"data.csv", "data.pcapng"}:
                        target = basename
                    elif basename == "person_data.csv" and info.file_size > 100000:
                        target = "data.csv"
                    elif basename == "person_data.csv":
                        target = "example_input.csv"
                    elif basename == "person_data2.csv":
                        target = "example_answer.csv"
                    elif basename.endswith(".pdf") and info.file_size < 150000:
                        target = "rules.pdf"
                    if target is None:
                        continue
                    if info.file_size > 64 * 1024 * 1024 or target in selected:
                        raise ValueError("原附件包含重复目标或过大文件")
                    content = archive.read(info)
                    (folder / target).write_bytes(content)
                    selected[target] = {
                        "archive_path": info.filename,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "bytes": len(content),
                    }
        manifest[case] = {"url": url, "archive_sha256": expected_hash, "files": selected}
        print(f"downloaded {case}: {len(selected)} data/rule files")
    (BASE / "sources.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def select(id, upstream, fields):
    return n(id, "columns.select", {"fields": fields}, data=upstream)


def write(id, upstream, case, filename="submission.csv"):
    plugin = "json.write" if filename.endswith(".jsonl") else "csv.write"
    config = {"path": f"../work/contest-round2/results/{case}/{filename}", "overwrite": True}
    if plugin == "json.write":
        config.update(format="jsonl", diagnostics=True)
    return n(id, plugin, config, data=upstream)


def flows():
    path = "../work/contest-round2/input/"
    analysis = copy.deepcopy(first_flows()["analysis"])
    analysis[0]["config"]["path"] = path + "ycb24_analysis/data.csv"
    for node in analysis:
        if node["plugin"] == "text.write":
            node["config"]["path"] = node["config"]["path"].replace(
                "real-ctf/results", "contest-round2/results/ycb24_analysis"
            )
            if node["id"] == "answer":
                node["config"]["path"] = node["config"]["path"].replace(
                    "submission.csv", "canonical-reference.csv"
                )
            else:
                node["config"]["path"] = node["config"]["path"].replace(
                    "flag.txt", "reuse-reference-flag.txt"
                )
    analysis.extend(
        [
            n("submission_columns", "columns.rename", {"mapping": YCB_HEADERS}, data="sort:data"),
            n(
                "save_submission",
                "csv.write",
                {
                    "path": "../work/contest-round2/results/ycb24_analysis/submission.csv",
                    "line_ending": "crlf",
                    "overwrite": True,
                },
                data="submission_columns:data",
            ),
        ]
    )

    rules = [
        {"label": label, "conditions": [{"field": "数据值", "op": "regex", "value": pattern}]}
        for label, pattern in [
            ("姓名", r"^[\u4e00-\u9fff]+$"),
            ("身份证号", r"^[0-9]{17}[0-9Xx]$"),
            ("手机号", "^" + PHONE + "$"),
        ]
    ]
    classify1 = [
        n("read", "csv.read", {"path": path + "zj24_classify1/data.csv"}),
        n("source_order", "rows.number", {"output": "原始序号"}, data="read:data"),
        n(
            "classify",
            "rows.classify",
            {"rules": rules, "default": "未识别", "output": "类型"},
            data="source_order:data",
        ),
        n(
            "identity_rows",
            "rows.filter",
            {"conditions": [{"field": "类型", "op": "eq", "value": "身份证号"}]},
            data="classify:data",
        ),
        n(
            "checksum",
            "validate.identity",
            {"field": "数据值", **IDENTITY},
            data="identity_rows:matched",
        ),
        n(
            "known",
            "rows.filter",
            {"conditions": [{"field": "类型", "op": "ne", "value": "未识别"}]},
            data="identity_rows:unmatched",
        ),
        n("merge", "rows.merge", {}, left="checksum:valid", right="known:matched"),
        n(
            "restore_order",
            "rows.sort",
            {"rules": [{"field": "原始序号", "type": "number", "direction": "asc"}]},
            data="merge:data",
        ),
        select("answer", "restore_order:data", ["类型", "数据值"]),
        write("save", "answer:data", "zj24_classify1"),
        write("reject_id", "checksum:invalid", "zj24_classify1", "rejected_identity.jsonl"),
        write("reject_type", "known:unmatched", "zj24_classify1", "unclassified.jsonl"),
    ]
    fields = ["username", "name", "sex", "birth", "idcard", "phone"]
    traffic = [
        n("read", "pcap.http", {"path": path + "ycb24_traffic/data.pcapng"}),
        n(
            "json",
            "json.extract",
            {"field": "正文", "mapping": {f: "/" + f for f in fields}},
            data="read:data",
        ),
        select("columns", "json:valid", [*fields, "帧号"]),
        n(
            "rules",
            "validate.rules",
            {
                "rules": [
                    {"field": "username", "check": "regex", "pattern": "[A-Za-z0-9]+"},
                    {"field": "name", "check": "regex", "pattern": r"[\u4e00-\u9fff]+"},
                    {"field": "sex", "check": "enum", "values": ["男", "女"]},
                    {"field": "birth", "check": "regex", "pattern": "[0-9]{8}"},
                    {"field": "idcard", "check": "regex", "pattern": "[0-9]{17}[0-9Xx]"},
                    {"field": "phone", "check": "regex", "pattern": PHONE},
                ]
            },
            data="columns:data",
        ),
        n(
            "identity",
            "validate.identity",
            {"field": "idcard", "gender_field": "sex", **IDENTITY},
            data="rules:valid",
        ),
        n(
            "id_birth",
            "text.extract",
            {
                "field": "idcard",
                "pattern": "^[0-9]{6}([0-9]{8})",
                "group": 1,
                "output": "身份证生日",
            },
            data="identity:valid",
        ),
        n(
            "birth",
            "validate.rules",
            {"rules": [{"field": "birth", "check": "equals_field", "other": "身份证生日"}]},
            data="id_birth:data",
        ),
        select("bad_birth", "birth:invalid", [*fields, "帧号"]),
        n("merge1", "rows.merge", {}, left="rules:invalid", right="identity:invalid"),
        n("merge2", "rows.merge", {}, left="merge1:data", right="bad_birth:data"),
        n(
            "restore_order",
            "rows.sort",
            {"rules": [{"field": "帧号", "type": "number", "direction": "asc"}]},
            data="merge2:data",
        ),
        select("answer", "restore_order:data", fields),
        write("save", "answer:data", "ycb24_traffic"),
        write("json_errors", "json:invalid", "ycb24_traffic", "json_errors.jsonl"),
        write("decode_errors", "read:invalid", "ycb24_traffic", "decode_errors.jsonl"),
    ]
    ipv4 = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[0-9]{1,2})(?:\.(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[0-9]{1,2})){3}"
    classify2 = [
        n("read", "pcap.http", {"path": path + "zj24_classify2/data.pcapng"}),
        n(
            "find",
            "text.find_all",
            {
                "field": "正文",
                "rules": [
                    {
                        "label": "idcard",
                        "pattern": r"(?<![0-9])(?:[0-9]{17}[0-9Xx]|[0-9]{6} [0-9]{8} [0-9]{3}[0-9Xx]|[0-9]{6}-[0-9]{8}-[0-9]{3}[0-9Xx])(?![0-9])",
                    },
                    {
                        "label": "phone",
                        "pattern": r"(?<![0-9])(?:[0-9]{11}|[0-9]{3} [0-9]{4} [0-9]{4}|[0-9]{3}-[0-9]{4}-[0-9]{4})(?![0-9])",
                    },
                    {
                        "label": "ip",
                        "pattern": r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])",
                    },
                ],
            },
            data="read:data",
        ),
        n(
            "normalize",
            "text.replace",
            {"fields": ["value"], "search": "[- ]", "replacement": "", "regex": True},
            data="find:data",
        ),
        n(
            "ids",
            "rows.filter",
            {"conditions": [{"field": "category", "op": "eq", "value": "idcard"}]},
            data="normalize:data",
        ),
        n("checksum", "validate.identity", {"field": "value", **IDENTITY}, data="ids:matched"),
        n(
            "phones",
            "rows.filter",
            {"conditions": [{"field": "category", "op": "eq", "value": "phone"}]},
            data="ids:unmatched",
        ),
        n(
            "phone_check",
            "validate.regex",
            {"field": "value", "pattern": PHONE},
            data="phones:matched",
        ),
        n(
            "ip_check",
            "validate.regex",
            {"field": "value", "pattern": ipv4},
            data="phones:unmatched",
        ),
        n("merge1", "rows.merge", {}, left="checksum:valid", right="phone_check:valid"),
        n("merge2", "rows.merge", {}, left="merge1:data", right="ip_check:valid"),
        n(
            "restore_order",
            "rows.sort",
            {
                "rules": [
                    {"field": "记录位置", "type": "number", "direction": "asc"},
                    {"field": "起始字符", "type": "number", "direction": "asc"},
                ]
            },
            data="merge2:data",
        ),
        select("answer", "restore_order:data", ["category", "value"]),
        write("save", "answer:data", "zj24_classify2"),
        write("decode_errors", "read:invalid", "zj24_classify2", "decode_errors.jsonl"),
        write("bad_id", "checksum:invalid", "zj24_classify2", "invalid_identity.jsonl"),
        write("bad_phone", "phone_check:invalid", "zj24_classify2", "invalid_phone.jsonl"),
        write("bad_ip", "ip_check:invalid", "zj24_classify2", "invalid_ip.jsonl"),
    ]
    return {
        "ycb24_analysis": analysis,
        "zj24_classify1": classify1,
        "ycb24_traffic": traffic,
        "zj24_classify2": classify2,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--case", choices=list(SOURCES), action="append")
    args = parser.parse_args()
    if args.fetch:
        fetch()
    registry, reports = create_registry(), {}
    titles = {
        "ycb24_analysis": "羊城杯2024：原始CSV列复原",
        "ycb24_traffic": "羊城杯2024：HTTP数据清洗（提交垃圾数据）",
        "zj24_classify1": "浙江2024决赛：两万行数据分类",
        "zj24_classify2": "浙江2024决赛：流量识别与格式还原",
    }
    for case, nodes in flows().items():
        definition = {
            "version": 1,
            "name": "真实题：" + titles[case],
            "description": {
                "ycb24_analysis": "10000行字段错位复原，保留原赛中文表头；原附示例核对通过。",
                "ycb24_traffic": "8000条请求提取与规则清洗，输出垃圾数据；尚无官方正确率。",
                "zj24_classify1": "20000行姓名、身份证与手机号分类，保持原行序；尚无官方正确率。",
                "zj24_classify2": "明文HTTP正文识别与变形格式还原，保留拒绝项；尚无官方正确率。",
            }[case],
            "nodes": nodes,
        }
        (ROOT / f"examples/ctf_real_{case}.json").write_text(
            json.dumps(definition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if args.case and case not in args.case:
            continue
        if not (BASE / "input" / case).exists():
            raise SystemExit("缺少原附件，请先执行 python scripts/contest_round2.py --fetch")
        started = time.perf_counter()
        result = Pipeline(registry).run(definition, base_dir=ROOT / "examples")
        report = {
            "evidence": "完整原附件按公开规范生成提交；未获官方正确率",
            "seconds": round(time.perf_counter() - started, 3),
            "ports": {
                id: {port: len(table) for port, table in ports.items()}
                for id, ports in result.tables.items()
            },
            "artifacts": {
                p.name: {
                    "bytes": p.stat().st_size,
                    "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                }
                for p in sorted(result.context.output_paths)
            },
        }
        if case == "ycb24_analysis":
            flag = result.tables["flag"]["data"].records[0].values["flag"]
            report.update(
                flag=flag,
                matches_published_reuse_answer=flag == "flag{518a8b1f87c23d94c1be372efd0f0f30}",
            )
            report["evidence"] = (
                "原始CSV与广工复用数据仅行尾不同；英文列名规范下匹配复用题公布摘要。羊城杯submission.csv按原示例输出中文表头，未在线判定"
            )
            if not report["matches_published_reuse_answer"]:
                raise ValueError("原始CSV复原结果与已验证复用题不一致")
        reports[case] = report
        print(case, json.dumps(report, ensure_ascii=True))
    (BASE / "verification.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
