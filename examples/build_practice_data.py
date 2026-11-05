"""Rebuild tiny fictional fixtures, never download or execute a contest attachment.

Run from any directory: python examples/build_practice_data.py
The expected answers are hand specified, separate from the processing pipeline.
"""

import base64
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def write_csv(name, rows):
    with (DATA / name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def node(id, plugin, config=None, **inputs):
    return {"id": id, "plugin": plugin, "config": config or {}, "inputs": inputs}


def flow(name, title, description, nodes):
    for item in nodes:
        if item["plugin"] == "json.write" and item["config"]["path"].endswith(".jsonl"):
            item["config"]["format"] = "jsonl"
    (ROOT / f"{name}.json").write_text(
        json.dumps(
            {"version": 1, "name": title, "description": description, "nodes": nodes},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main():
    key = b"a1a60171273e74a6"

    def encrypt(value):
        return base64.b64encode(
            bytes(x ^ key[(i + 1) % len(key)] for i, x in enumerate(value.encode()))
        ).decode()

    plain = [{"username": "demo_a", "city": "杭州"}, {"username": "demo_b", "city": "宁波"}]
    write_csv(
        "ctf_encoded.csv",
        [
            *({k: encrypt(v) for k, v in r.items()} for r in plain),
            {"username": "***bad***", "city": encrypt("上海")},
        ],
    )
    flow(
        "ctf_xor",
        "演练：字段编码还原",
        "参考浙江2025初赛 dsEnData；已知密钥，虚构数据含一行损坏密文",
        [
            node("read", "csv.read", {"path": "data/ctf_encoded.csv"}),
            node(
                "decode",
                "codec.xor",
                {"fields": ["username", "city"], "key": key.decode(), "key_offset": 1},
                data="read:data",
            ),
            node(
                "write",
                "csv.write",
                {"path": "../work/practice/xor_answer.csv", "overwrite": True},
                data="decode:valid",
            ),
            node(
                "reject",
                "json.write",
                {"path": "../work/practice/xor_reject.jsonl", "overwrite": True},
                data="decode:invalid",
            ),
        ],
    )
    write_csv(
        "ctf_identity.csv",
        [
            {"编号": "001", "证件": " 110105-19491231-002x ", "性别": "女", "生日": "1949-12-31"},
            {"编号": "002", "证件": "11010519491231002X", "性别": "男", "生日": "1949-12-31"},
            {"编号": "003", "证件": "110105194912310020", "性别": "女", "生日": "1949-12-31"},
            {"编号": "004", "证件": "not-an-id", "性别": "女", "生日": "1949-12-31"},
            {"编号": "005", "证件": "110105 19491231 002X", "性别": "女", "生日": "1949-12-31"},
        ],
    )
    flow(
        "ctf_identity",
        "演练：证件清洗与一致性校验",
        "参考羊城2025 dataIdSort的格式识别；加入生日与性别对照练习，使用标准示例号码",
        [
            node("read", "csv.read", {"path": "data/ctf_identity.csv"}),
            node(
                "clean",
                "text.replace",
                {"fields": ["证件"], "search": r"[\s-]", "replacement": "", "regex": True},
                data="read:data",
            ),
            node(
                "check",
                "validate.identity",
                {"field": "证件", "gender_field": "性别", "birth_field": "生日"},
                data="clean:data",
            ),
            node(
                "write",
                "csv.write",
                {"path": "../work/practice/identity_answer.csv", "overwrite": True},
                data="check:valid",
            ),
            node(
                "reject",
                "json.write",
                {
                    "path": "../work/practice/identity_reject.jsonl",
                    "overwrite": True,
                    "diagnostics": True,
                },
                data="check:invalid",
            ),
        ],
    )
    # Public payment test numbers, fictional users and a deliberately corrupted checksum.
    write_csv(
        "ctf_orders.csv",
        [
            {
                "订单": "A",
                "用户": "demo1",
                "卡号": "4111111111111111",
                "金额": "100",
                "品类": "演示",
                "时间": "2025-01-01T10:00:00",
            },
            {
                "订单": "B",
                "用户": "demo2",
                "卡号": "4111111111111111",
                "金额": "100",
                "品类": "演示",
                "时间": "2025-01-01T10:30:00",
            },
            {
                "订单": "C",
                "用户": "demo1",
                "卡号": "4111111111111111",
                "金额": "100",
                "品类": "演示",
                "时间": "2025-01-01T11:30:01",
            },
            {
                "订单": "D",
                "用户": "demo3",
                "卡号": "4111111111111111",
                "金额": "1000",
                "品类": "演示",
                "时间": "2025-01-01T12:00:00",
            },
            {
                "订单": "E",
                "用户": "demo4",
                "卡号": "4111111111111112",
                "金额": "100",
                "品类": "演示",
                "时间": "2025-01-01T12:05:00",
            },
        ],
    )
    flow(
        "ctf_orders",
        "演练：订单异常调查",
        "参考浙江2025决赛规则：Luhn、时间窗口跨用户计数、分组金额异常；非完整官方判分",
        [
            node("read", "csv.read", {"path": "data/ctf_orders.csv"}),
            node("card", "validate.luhn", {"field": "卡号"}, data="read:data"),
            node(
                "window",
                "rows.window_count",
                {
                    "time_field": "时间",
                    "group_by": ["卡号"],
                    "distinct_field": "用户",
                    "output": "一小时用户数",
                },
                data="card:valid",
            ),
            node(
                "classify",
                "rows.classify",
                {
                    "rules": [
                        {
                            "label": "需调查",
                            "conditions": [{"field": "一小时用户数", "op": "gt", "value": "1"}],
                            "match": "all",
                        }
                    ],
                    "default": "未触发窗口规则",
                    "output": "窗口提示",
                },
                data="window:valid",
            ),
            node(
                "amount",
                "stats.outliers",
                {"field": "金额", "group_by": ["品类"], "threshold": "1.5"},
                data="classify:data",
            ),
            node(
                "write",
                "csv.write",
                {"path": "../work/practice/orders_answer.csv", "overwrite": True},
                data="classify:data",
            ),
            node(
                "outlier",
                "csv.write",
                {"path": "../work/practice/orders_amount.csv", "overwrite": True},
                data="amount:outliers",
            ),
            node(
                "reject",
                "json.write",
                {"path": "../work/practice/orders_reject.jsonl", "overwrite": True},
                data="card:invalid",
            ),
        ],
    )
    write_csv(
        "ctf_dirty.csv",
        [
            {"编号": "001", "部门": "ops", "电话": "13800000001"},
            {"编号": "002", "部门": "", "电话": "13900000002"},
            {"编号": "003", "部门": "?", "电话": "13700000003"},
        ],
    )
    write_csv(
        "ctf_reference.csv",
        [{"编号": "001", "标准部门": "运维"}, {"编号": "002", "标准部门": "开发"}],
    )
    flow(
        "ctf_lookup",
        "演练：参考表纠错与提交",
        "虚构CSV纠错练习：明确字典关联、未命中审查、手机号脱敏、纯文本提交和质量概览",
        [
            node("read", "csv.read", {"path": "data/ctf_dirty.csv"}),
            node("reference", "csv.read", {"path": "data/ctf_reference.csv"}),
            node(
                "lookup",
                "tables.lookup",
                {"keys": ["编号"], "mapping": {"部门": "标准部门"}, "mode": "replace"},
                data="read:data",
                reference="reference:data",
            ),
            node("mask", "text.mask", {"fields": ["电话"]}, data="lookup:matched"),
            node("profile", "profile.summary", {}, data="read:data"),
            node(
                "write",
                "text.write",
                {
                    "path": "../work/practice/lookup_answer.txt",
                    "fields": ["编号", "部门", "电话"],
                    "separator": "\t",
                    "overwrite": True,
                },
                data="mask:data",
            ),
            node(
                "reject",
                "json.write",
                {"path": "../work/practice/lookup_reject.jsonl", "overwrite": True},
                data="lookup:unmatched",
            ),
        ],
    )
    expected = {
        "xor": plain,
        "identity_valid": ["001", "005"],
        "identity_invalid": ["002", "003", "004"],
        "orders_valid": ["A", "B", "C", "D"],
        "orders_counts": ["1", "2", "1", "2"],
        "orders_amount": ["D"],
        "orders_invalid": ["E"],
        "lookup_text": "001\t运维\t138****0001\n002\t开发\t139****0002\n",
    }
    (DATA / "ctf_expected.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
