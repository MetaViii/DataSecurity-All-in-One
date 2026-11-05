"""Download pinned public contest data, run our pipelines, compare author-published flags.

Never imports or runs downloaded Python. Run from the repository root:
    python scripts/real_ctf.py --fetch
    python scripts/real_ctf.py
"""

import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from datasecurity.builtin import create_registry
from datasecurity.core.pipeline import Pipeline

CASES = {
    "analysis": {
        "repo": "GDUTMeow-Challenges/Challenge-Data-Analysis",
        "commit": "7fa5eaa86687769074ee261b9467dabee29f0078",
        "archive_sha256": "2fa3542ba28e6f36d32dc33ff3ad45d43aa04244826415705ee3dc2f073f2142",
        "expected": "518a8b1f87c23d94c1be372efd0f0f30",
    },
    "cleaning": {
        "repo": "GDUTMeow-Challenges/Challenge-DataCleaning",
        "commit": "9b7c093568c7f09f66eec548dd8c5719dc867315",
        "archive_sha256": "7c208a8477a5447f16f6157f96e2eb48eae8296fd76b14f95cc3668b31d6d8cc",
        "expected": "93767ebcb98095b0cd05b04d9b42e845",
    },
    "log": {
        "repo": "GDUTMeow-Challenges/Challenge-Data-from-Log",
        "commit": "f4a3d564dbb1c46a84f227e2dd34bc0f2272ebc4",
        "url": "https://github.com/GDUTMeow-Challenges/Challenge-Data-from-Log/releases/download/attachment/Data-from-Log.zip",
        "archive_sha256": "4241e5bbcedea691799ed84b507a5ec2dec07cb13f08ec14c67a77b3f3ae96ce",
        "expected": "de95bf79eace2722b90fbecc35cab2ed",
    },
}
PREFIXES = "734 735 736 737 738 739 747 748 750 751 752 757 758 759 772 778 782 783 784 787 788 795 798 730 731 732 740 745 746 755 756 766 767 771 775 776 785 786 796 733 749 753 773 774 777 780 781 789 790 791 793 799".split()
PHONE = "(?:" + "|".join(PREFIXES) + ")[0-9]{8}"


def fetch():
    base = ROOT / "work/real-ctf/input"
    manifest = {}
    for name, case in CASES.items():
        url = case.get("url") or f'https://codeload.github.com/{case["repo"]}/zip/{case["commit"]}'
        request = urllib.request.Request(
            url, headers={"User-Agent": "DataSecurity-CTF-Reproduction/1"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            archive = response.read(32 * 1024 * 1024 + 1)
        if len(archive) > 32 * 1024 * 1024:
            raise ValueError("下载超过32MiB")
        digest = hashlib.sha256(archive).hexdigest()
        if digest != case["archive_sha256"]:
            raise ValueError(f"{name} 附件哈希改变，停止以待人工检查")
        files = {}
        targetroot = (base / name).resolve()
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                relative = info.filename if name == "log" else info.filename.split("/", 1)[1]
                keep = relative in {
                    "README.md",
                    "Writeup.md",
                    "person_data.csv",
                    "polluted.csv",
                    "original.csv",
                    "apache2/error.log",
                } or re.fullmatch(r"cert/[0-9]+\.pem", relative)
                if not keep:
                    continue
                path = (targetroot / relative).resolve()
                if not path.is_relative_to(targetroot) or info.file_size > 64 * 1024 * 1024:
                    raise ValueError("附件路径或大小无效")
                data = z.read(info)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                files[relative] = hashlib.sha256(data).hexdigest()
        manifest[name] = {**case, "download_url": url, "files": files}
        print(f"downloaded {name}: {len(files)} files, archive sha256={digest}")
    (base.parent / "sources.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def n(id, plugin, config=None, **inputs):
    return {"id": id, "plugin": plugin, "config": config or {}, "inputs": inputs}


def ending(upstream, fields=None, *, serialized=True):
    nodes = []
    if serialized:
        nodes.append(
            n(
                "serialize",
                "table.serialize",
                {"fields": fields or [], "line_ending": "crlf", "trailing_blank_lines": 0},
                data=upstream,
            )
        )
        upstream = "serialize:data"
        field = "提交内容"
        nodes.append(
            n(
                "answer",
                "text.write",
                {
                    "path": "../work/real-ctf/results/submission.csv",
                    "fields": [field],
                    "raw": True,
                    "overwrite": True,
                },
                data=upstream,
            )
        )
    else:
        field = "拼接结果"
    nodes.append(
        n("digest", "codec.fields", {"fields": [field], "operation": "md5"}, data=upstream)
    )
    nodes.append(
        n(
            "flag",
            "text.template",
            {"template": "flag{{{" + field + "}}}", "output": "flag"},
            data="digest:valid",
        )
    )
    nodes.append(
        n(
            "save_flag",
            "text.write",
            {"path": "../work/real-ctf/results/flag.txt", "fields": ["flag"], "overwrite": True},
            data="flag:data",
        )
    )
    return nodes


def flows():
    base = "../work/real-ctf/input/"
    analysis = [
        n("read", "csv.read", {"path": base + "analysis/person_data.csv"}),
        n(
            "realign",
            "columns.realign",
            {
                "rules": {
                    "number": r"[0-9]{1,5}",
                    "username": r"[A-Za-z0-9]+",
                    "password": r"[a-f0-9]{32}",
                    "name": r"[\u4e00-\u9fff]+",
                    "gender": "男|女",
                    "birth": r"[0-9]{8}",
                    "id": r"[0-9]{17}[0-9Xx]",
                    "phone": PHONE,
                }
            },
            data="read:data",
        ),
        n(
            "sort",
            "rows.sort",
            {"rules": [{"field": "number", "type": "number", "direction": "asc"}]},
            data="realign:valid",
        ),
    ]
    analysis += ending("sort:data")
    cleaning = [
        n("read", "csv.read", {"path": base + "cleaning/polluted.csv"}),
        n(
            "rules",
            "validate.rules",
            {
                "rules": [
                    {"field": "姓名", "check": "regex", "pattern": r"[^A-Za-z0-9]*"},
                    {"field": "性别", "check": "enum", "values": ["男", "女"]},
                    {"field": "用户名", "check": "regex", "pattern": r"[A-Za-z][A-Za-z0-9]*"},
                ]
            },
            data="read:data",
        ),
        n(
            "identity",
            "validate.identity",
            {
                "field": "身份证号",
                "gender_field": "性别",
                "check_sequence": False,
                "check_date": False,
                "check_region_format": False,
                "allow_lower_x": False,
            },
            data="rules:valid",
        ),
        n(
            "message",
            "text.template",
            {"template": "{用户名}_{密码}_{身份证号}", "output": "待验消息"},
            data="identity:valid",
        ),
        n(
            "signature",
            "validate.signature",
            {
                "message_field": "待验消息",
                "signature_field": "签名",
                "key_path": base + "cleaning/cert/{序号}.pem",
            },
            data="message:data",
        ),
        n("bad_rules", "columns.select", {"fields": ["序号"]}, data="rules:invalid"),
        n("bad_identity", "columns.select", {"fields": ["序号"]}, data="identity:invalid"),
        n("bad_signature", "columns.select", {"fields": ["序号"]}, data="signature:invalid"),
        n("merge1", "rows.merge", {}, left="bad_rules:data", right="bad_identity:data"),
        n("merge2", "rows.merge", {}, left="merge1:data", right="bad_signature:data"),
        n(
            "sort",
            "rows.sort",
            {"rules": [{"field": "序号", "type": "number", "direction": "asc"}]},
            data="merge2:data",
        ),
        n("collect", "rows.collect", {"field": "序号", "separator": "_"}, data="sort:data"),
    ]
    cleaning += ending("collect:data", serialized=False)
    log = [
        n(
            "read",
            "text.records",
            {"path": base + "log/apache2/error.log", "start_pattern": "username="},
        ),
        n(
            "password",
            "text.extract",
            {
                "field": "内容",
                "pattern": r"\\xe6[^\n]*?:\s(.*?)\\n",
                "group": 1,
                "occurrence": "last",
                "output": "password",
            },
            data="read:data",
        ),
        n(
            "clean_password",
            "text.replace",
            {"fields": ["password"], "search": r"[\\ ]", "replacement": "", "regex": True},
            data="password:data",
        ),
        n(
            "url",
            "codec.fields",
            {"fields": ["内容"], "operation": "url_decode"},
            data="clean_password:data",
        ),
    ]
    upstream = "url:valid"
    for field, pattern in [
        ("username", r"(?:^|[ &])username=([^&\s]*)"),
        ("name", r"&name=([^&\s]*)"),
        ("idcard", r"&idcard=([^&\s]*)"),
        ("phone", r"&phone=([^&\s]*)"),
    ]:
        log.append(
            n(
                "extract_" + field,
                "text.extract",
                {"field": "内容", "pattern": pattern, "output": field},
                data=upstream,
            )
        )
        upstream = "extract_" + field + ":data"
    log.append(
        n(
            "rules",
            "validate.rules",
            {
                "rules": [
                    {"field": "username", "check": "regex", "pattern": r"[A-Za-z0-9]+"},
                    {"field": "name", "check": "regex", "pattern": r"[\u4e00-\u9fff]+"},
                    {"field": "phone", "check": "regex", "pattern": PHONE},
                    {"field": "password", "check": "required"},
                ]
            },
            data=upstream,
        )
    )
    log.append(
        n(
            "identity",
            "validate.identity",
            {
                "field": "idcard",
                "check_sequence": False,
                "check_date": False,
                "check_region_format": False,
                "allow_lower_x": False,
            },
            data="rules:valid",
        )
    )
    log.append(
        n(
            "select",
            "columns.select",
            {"fields": ["username", "password", "name", "idcard", "phone"]},
            data="identity:valid",
        )
    )
    log.append(
        n(
            "mask_names",
            "text.replace",
            {
                "fields": ["username", "name"],
                "search": r"(?<=^.).$|(?<=.).(?=.)",
                "replacement": "*",
                "regex": True,
            },
            data="select:data",
        )
    )
    log.append(
        n(
            "mask_id_prefix",
            "text.replace",
            {"fields": ["idcard"], "search": r"^.{6}", "replacement": "******", "regex": True},
            data="mask_names:data",
        )
    )
    log.append(
        n(
            "mask_id_suffix",
            "text.replace",
            {"fields": ["idcard"], "search": r".{8}$", "replacement": "********", "regex": True},
            data="mask_id_prefix:data",
        )
    )
    log.append(
        n(
            "mask_phone",
            "text.mask",
            {"fields": ["phone"], "keep_start": 3, "keep_end": 4},
            data="mask_id_suffix:data",
        )
    )
    log.append(
        n(
            "password_digest",
            "codec.fields",
            {"fields": ["password"], "operation": "md5"},
            data="mask_phone:data",
        )
    )
    log += ending("password_digest:valid")
    return {"analysis": analysis, "cleaning": cleaning, "log": log}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="下载固定版本原附件；不运行附件脚本")
    parser.add_argument("--case", choices=list(CASES), action="append")
    args = parser.parse_args()
    if args.fetch:
        fetch()
    registry = create_registry()
    results = {}
    for name, nodes in flows().items():
        title = {
            "analysis": "真实题：字段错位复原（10000行）",
            "cleaning": "真实题：规则与RSA验签",
            "log": "真实题：Apache日志恢复与脱敏",
        }[name]
        definition = {
            "version": 1,
            "name": title,
            "description": "广工2025网安卫士公开原附件；请先运行 python scripts/real_ctf.py --fetch，来源与结果见real-ctf.md",
            "nodes": nodes,
        }
        for item in nodes:
            if item["plugin"] == "text.write":
                item["config"]["path"] = item["config"]["path"].replace(
                    "results/", f"results/{name}/"
                )
        (ROOT / f"examples/ctf_real_{name}.json").write_text(
            json.dumps(definition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if name == "log":
            strict = copy.deepcopy(definition)
            strict["name"] = "真实题：日志脱敏（严格密码规则对照）"
            strict["description"] = (
                "对照题面仅字母数字密码规则；会比公开参考解答少1条，详见real-ctf.md"
            )
            rule_node = next(item for item in strict["nodes"] if item["id"] == "rules")
            rule_node["config"]["rules"][-1] = {
                "field": "password",
                "check": "regex",
                "pattern": r"[A-Za-z0-9]+",
            }
            for item in strict["nodes"]:
                if item["plugin"] == "text.write":
                    item["config"]["path"] = item["config"]["path"].replace(
                        "results/log/", "results/log_strict/"
                    )
            (ROOT / "examples/ctf_real_log_strict.json").write_text(
                json.dumps(strict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        if args.case and name not in args.case:
            continue
        input_dir = ROOT / "work/real-ctf/input" / name
        if not input_dir.exists():
            raise SystemExit("缺少原附件，请先加 --fetch 下载")
        started = time.perf_counter()
        result = Pipeline(registry).run(definition, base_dir=ROOT / "examples")
        flag = result.tables["flag"]["data"].records[0].values["flag"]
        expected = f'flag{{{CASES[name]["expected"]}}}'
        output = {
            "flag": flag,
            "expected": expected,
            "matches": flag == expected,
            "seconds": round(time.perf_counter() - started, 3),
            "source": {key: value for key, value in CASES[name].items() if key != "expected"},
            "ports": {
                node: {port: len(table) for port, table in ports.items()}
                for node, ports in result.tables.items()
                if registry.get(next(x["plugin"] for x in nodes if x["id"] == node)).spec.kind
                != "output"
            },
        }
        results[name] = output
        print(name, json.dumps(output, ensure_ascii=True))
    path = ROOT / "work/real-ctf/verification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    if not all(r["matches"] for r in results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
