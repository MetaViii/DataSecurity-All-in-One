"""Explicit offline checks. Passing a checksum does not prove an identity/account exists."""

import base64
import re
from datetime import datetime, date

from datasecurity import Parameter as P, Plugin, PluginSpec
from ._files import check_encoding, atomic_text
from ._utils import names


class IdentityCheck(Plugin):
    spec = PluginSpec(
        "validate.identity",
        "身份证一致性校验",
        "transform",
        "检查18位格式、真实日期、顺序码及校验码，可对照性别和生日；不自动修复",
        inputs=("data",),
        outputs=("valid", "invalid"),
        category="数据校验",
        parameters=(
            P("field", str, "身份证字段", required=True, widget="field"),
            P("gender_field", str, "对照性别字段；空为不对照", default=""),
            P("birth_field", str, "对照生日字段；空为不对照", default=""),
            P("birth_format", str, "对照生日格式", default="%Y-%m-%d"),
            P("male_values", list, "可接受的男性值", default=["男", "male", "M", "1"]),
            P("female_values", list, "可接受的女性值", default=["女", "female", "F", "2"]),
            P("allow_lower_x", bool, "接受小写x校验码", default=True),
            P("check_sequence", bool, "拒绝000顺序码；原题若只校验校验和可关闭", default=True),
            P("check_date", bool, "检查真实出生日期；原题若只校验校验和可关闭", default=True),
            P("check_region_format", bool, "要求地址码首位非0", default=True),
            P("region_codes", list, "六位地址码白名单；空为不验证历史行政区划", default=[]),
            P("reference_date", str, "可选生日截止日期 YYYY-MM-DD", default=""),
        ),
    )

    def check_config(self, c):
        names([c["field"]])
        names(c["male_values"])
        names(c["female_values"])
        if set(c["male_values"]) & set(c["female_values"]):
            raise ValueError("男女取值不能重叠")
        if any(
            not isinstance(v, str) or not re.fullmatch(r"[0-9]{6}", v) for v in c["region_codes"]
        ):
            raise ValueError("地址码必须为六位ASCII数字")
        if c["reference_date"]:
            date.fromisoformat(c["reference_date"])

    def run(self, inputs, c, context):
        table = inputs["data"]
        table.require_columns([c["field"], *filter(None, (c["gender_field"], c["birth_field"]))])
        valid, invalid = [], []
        for record in table.records:
            context.check_cancelled()
            value = record.values[c["field"]]
            try:
                pattern = (
                    (r"[1-9]" if c["check_region_format"] else r"[0-9]")
                    + r"[0-9]{16}"
                    + (r"[0-9Xx]" if c["allow_lower_x"] else r"[0-9X]")
                )
                if not re.fullmatch(pattern, value):
                    raise ValueError("应为18位身份证格式")
                birthday = (
                    datetime.strptime(value[6:14], "%Y%m%d").date()
                    if c["check_date"] or c["birth_field"] or c["reference_date"]
                    else None
                )
                if c["check_sequence"] and value[14:17] == "000":
                    raise ValueError("顺序码不能为000")
                weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
                expected = "10X98765432"[sum(int(x) * w for x, w in zip(value[:17], weights)) % 11]
                if value[-1].upper() != expected:
                    raise ValueError("身份证校验码不匹配")
                if c["region_codes"] and value[:6] not in c["region_codes"]:
                    raise ValueError("地址码未在指定白名单中")
                if c["reference_date"] and birthday > date.fromisoformat(c["reference_date"]):
                    raise ValueError("生日晚于指定截止日期")
                if (
                    c["birth_field"]
                    and datetime.strptime(record.values[c["birth_field"]], c["birth_format"]).date()
                    != birthday
                ):
                    raise ValueError("生日字段与身份证不一致")
                if c["gender_field"]:
                    choices = c["male_values"] if int(value[16]) % 2 else c["female_values"]
                    if record.values[c["gender_field"]] not in choices:
                        raise ValueError("性别字段与身份证不一致")
            except ValueError as exc:
                invalid.append(
                    record.with_issue(node=context.node_id, field=c["field"], message=str(exc))
                )
            else:
                valid.append(record)
        return {"valid": table.with_records(valid), "invalid": table.with_records(invalid)}


class LuhnCheck(Plugin):
    spec = PluginSpec(
        "validate.luhn",
        "Luhn 校验",
        "transform",
        "校验数字串，长度可配置；不验证发卡机构或账户真实性",
        inputs=("data",),
        outputs=("valid", "invalid"),
        category="数据校验",
        parameters=(
            P("field", str, "数字字段", required=True, widget="field"),
            P("min_length", int, "最短位数", default=12),
            P("max_length", int, "最长位数", default=19),
        ),
    )

    def check_config(self, c):
        names([c["field"]])
        if not 2 <= c["min_length"] <= c["max_length"] <= 100:
            raise ValueError("长度范围应在2到100之间")

    def run(self, inputs, c, context):
        table = inputs["data"]
        table.require_columns([c["field"]])
        valid, invalid = [], []
        for record in table.records:
            context.check_cancelled()
            value = record.values[c["field"]]
            digits = [int(x) for x in value] if value.isascii() and value.isdigit() else []
            total = sum(
                (x * 2 - 9 if x * 2 > 9 else x * 2) if i % 2 else x
                for i, x in enumerate(reversed(digits))
            )
            if (
                c["min_length"] <= len(digits) <= c["max_length"]
                and any(digits)
                and total % 10 == 0
            ):
                valid.append(record)
            else:
                invalid.append(
                    record.with_issue(
                        node=context.node_id,
                        field=c["field"],
                        message="长度、数字格式或Luhn校验失败",
                    )
                )
        return {"valid": table.with_records(valid), "invalid": table.with_records(invalid)}


class XorFields(Plugin):
    spec = PluginSpec(
        "codec.xor",
        "循环 XOR 还原",
        "transform",
        "显式字节输入/输出与密钥偏移，支持Base64后异或；失败行保持原值",
        inputs=("data",),
        outputs=("valid", "invalid"),
        category="编码与脱敏",
        parameters=(
            P("fields", list, "处理字段", required=True, widget="fields"),
            P("key", str, "已知密钥", required=True),
            P("key_format", str, "密钥格式", default="text", choices=("text", "hex")),
            P("key_offset", int, "密钥循环起始偏移", default=0),
            P("input_format", str, "输入格式", default="base64", choices=("text", "hex", "base64")),
            P("output_format", str, "输出格式", default="text", choices=("text", "hex", "base64")),
            P("encoding", str, "文本字符编码", default="utf-8"),
            P("skip_empty", bool, "空字符串保持为空", default=True),
        ),
    )

    def check_config(self, c):
        names(c["fields"])
        check_encoding(c["encoding"])
        key = (
            bytes.fromhex(c["key"]) if c["key_format"] == "hex" else c["key"].encode(c["encoding"])
        )
        if not key:
            raise ValueError("密钥不能为空")

    def run(self, inputs, c, context):
        table = inputs["data"]
        table.require_columns(c["fields"])
        key = (
            bytes.fromhex(c["key"]) if c["key_format"] == "hex" else c["key"].encode(c["encoding"])
        )
        valid, invalid = [], []
        for record in table.records:
            context.check_cancelled()
            updates = {}
            try:
                for field in c["fields"]:
                    value = record.values[field]
                    if not value and c["skip_empty"]:
                        updates[field] = value
                        continue
                    raw = (
                        base64.b64decode(value, validate=True)
                        if c["input_format"] == "base64"
                        else (
                            bytes.fromhex(value)
                            if c["input_format"] == "hex"
                            else value.encode(c["encoding"])
                        )
                    )
                    result = bytes(
                        x ^ key[(i + c["key_offset"]) % len(key)] for i, x in enumerate(raw)
                    )
                    updates[field] = (
                        base64.b64encode(result).decode("ascii")
                        if c["output_format"] == "base64"
                        else (
                            result.hex()
                            if c["output_format"] == "hex"
                            else result.decode(c["encoding"])
                        )
                    )
            except (ValueError, UnicodeError) as exc:
                invalid.append(
                    record.with_issue(node=context.node_id, field=field, message=str(exc))
                )
            else:
                valid.append(record.with_updates(updates, node=context.node_id, reason="循环XOR"))
        return {"valid": table.with_records(valid), "invalid": table.with_records(invalid)}


class TextWriter(Plugin):
    spec = PluginSpec(
        "text.write",
        "导出提交文本",
        "output",
        "按字段顺序输出纯文本；不加CSV引号，字段中的换行会报错",
        inputs=("data",),
        category="数据输出",
        parameters=(
            P("path", str, "输出文件名", required=True, widget="output_file"),
            P("fields", list, "输出字段及顺序", required=True, widget="fields"),
            P("separator", str, "字段间分隔符", default=","),
            P("header", bool, "包含表头", default=False),
            P("line_ending", str, "换行方式", default="lf", choices=("lf", "crlf")),
            P("encoding", str, "字符编码", default="utf-8"),
            P("overwrite", bool, "允许覆盖", default=False),
            P("raw", bool, "原文模式：仅一行一列，逐字节文本导出，不附加换行", default=False),
        ),
    )

    def check_config(self, c):
        names(c["fields"])
        names([c["path"]])
        check_encoding(c["encoding"])
        if "\n" in c["separator"] or "\r" in c["separator"]:
            raise ValueError("分隔符不能包含换行")

    def run(self, inputs, c, context):
        table = inputs["data"]
        table.require_columns(c["fields"])
        if c["raw"] and (len(c["fields"]) != 1 or len(table) != 1 or c["header"]):
            raise ValueError("原文导出要求一行一列且不写表头")
        path = context.output_path(c["path"], overwrite=c["overwrite"])
        ending = "\n" if c["line_ending"] == "lf" else "\r\n"
        with atomic_text(path, encoding=c["encoding"], newline="") as handle:
            if c["raw"]:
                context.check_cancelled()
                handle.write(table.records[0].values[c["fields"][0]])
                return {}
            if c["header"]:
                if any("\n" in f or "\r" in f for f in c["fields"]):
                    raise ValueError("表头含换行")
                handle.write(c["separator"].join(c["fields"]) + ending)
            for record in table.records:
                context.check_cancelled()
                values = [record.values[f] for f in c["fields"]]
                if any("\n" in v or "\r" in v for v in values):
                    raise ValueError("字段含换行，请先清洗或使用CSV导出")
                handle.write(c["separator"].join(values) + ending)
        return {}


PLUGINS = [IdentityCheck, LuhnCheck, XorFields, TextWriter]
