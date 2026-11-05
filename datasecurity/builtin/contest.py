"""Reusable operations added while solving published, full-size CTF attachments."""

import base64
import csv
import io
import re

from datasecurity import Origin, Parameter as P, Plugin, PluginSpec, Record, Table
from ._files import check_delimiter, check_encoding
from ._utils import names
from .advanced import TemplateText


class RealignColumns(Plugin):
    spec = PluginSpec(
        "columns.realign",
        "按规则复原列位置",
        "transform",
        "每行按正则规则寻找一对一字段分配；无解、歧义或搜索超限的行原样分流，不猜答案",
        inputs=("data",),
        outputs=("valid", "invalid"),
        category="字段处理",
        parameters=(
            P("rules", dict, "结果字段 → 完整匹配正则；字段顺序就是输出顺序", required=True),
            P("fields", list, "参与复原的来源字段；空为全部", default=[], widget="fields"),
            P("max_states", int, "每行最多搜索状态数", default=10000),
        ),
    )

    def check_config(self, c):
        names(c["fields"], allow_empty=True)
        if not c["rules"] or len(c["rules"]) > 20:
            raise ValueError("规则数量应为1到20")
        names(list(c["rules"]))
        for pattern in c["rules"].values():
            if not isinstance(pattern, str):
                raise ValueError("规则必须为正则字符串")
            re.compile(pattern)
        if not 1 <= c["max_states"] <= 1000000:
            raise ValueError("搜索上限应为1到1000000")

    def run(self, inputs, c, context):
        table = inputs["data"]
        fields = c["fields"] or list(table.columns)
        table.require_columns(fields)
        if len(fields) != len(c["rules"]):
            raise ValueError("来源字段数与目标规则数必须一致")
        patterns = {field: re.compile(pattern) for field, pattern in c["rules"].items()}
        valid, invalid = [], []
        for record in table.records:
            context.check_cancelled()
            values = [record.values[field] for field in fields]
            candidates = {
                field: [i for i, value in enumerate(values) if pattern.fullmatch(value)]
                for field, pattern in patterns.items()
            }
            order = sorted(patterns, key=lambda field: len(candidates[field]))
            solutions = {}
            states = 0
            exceeded = False

            def visit(position, used, assigned):
                nonlocal states, exceeded
                context.check_cancelled()
                states += 1
                if states > c["max_states"]:
                    exceeded = True
                    return
                if len(solutions) > 1:
                    return
                if position == len(order):
                    result = tuple(values[assigned[field]] for field in patterns)
                    solutions[result] = dict(zip(patterns, result))
                    return
                field = order[position]
                seen_values = set()
                for index in candidates[field]:
                    # Swapping two identical cells does not change the answer.
                    if index in used or values[index] in seen_values:
                        continue
                    seen_values.add(values[index])
                    assigned[field] = index
                    visit(position + 1, used | {index}, assigned)
                    if exceeded or len(solutions) > 1:
                        break

            visit(0, set(), {})
            if exceeded or len(solutions) != 1:
                reason = (
                    "搜索超过上限"
                    if exceeded
                    else "存在多个不同的字段分配" if solutions else "找不到满足全部规则的分配"
                )
                invalid.append(
                    record.with_issue(node=context.node_id, field=",".join(fields), message=reason)
                )
            else:
                valid.append(
                    record.rebuild(
                        next(iter(solutions.values())),
                        node=context.node_id,
                        reason="正则规则一对一复原列位置",
                    )
                )
        return {
            "valid": Table(tuple(patterns), tuple(valid)),
            "invalid": table.with_records(invalid),
        }


class TextRecords(Plugin):
    spec = PluginSpec(
        "text.records",
        "读取多行日志记录",
        "input",
        "起始正则命中时开始新记录，合并后续行；开头未分组行单独保留，限制单条记录大小",
        outputs=("data", "unmatched"),
        category="数据输入",
        parameters=(
            P("path", str, "日志路径", required=True, widget="input_file"),
            P("start_pattern", str, "一条记录的起始正则", required=True),
            P("encoding", str, "字符编码", default="utf-8-sig"),
            P("max_chars", int, "单条记录最大字符数", default=1000000),
        ),
    )

    def check_config(self, c):
        names([c["path"], c["start_pattern"]])
        re.compile(c["start_pattern"])
        check_encoding(c["encoding"])
        if c["max_chars"] < 1:
            raise ValueError("记录字符数上限必须为正")

    def run(self, inputs, c, context):
        path = context.resolve_path(c["path"])
        context.source_paths.add(path)
        pattern = re.compile(c["start_pattern"])
        records, unmatched, buffer = [], [], []
        start = count = 0

        def flush():
            if buffer:
                records.append(
                    Record(
                        {"内容": "\n".join(buffer)}, (Origin(str(path), len(records) + 1, start),)
                    )
                )

        with path.open(encoding=c["encoding"]) as handle:
            for line_number, line in enumerate(handle, 1):
                context.check_cancelled()
                value = line.rstrip("\r\n")
                if pattern.search(value):
                    flush()
                    buffer = []
                    start = line_number
                    count = 0
                if start:
                    count += len(value) + 1
                    if count > c["max_chars"]:
                        raise ValueError(f"第{start}行开始的记录超过max_chars")
                    buffer.append(value)
                else:
                    unmatched.append(
                        Record({"内容": value}, (Origin(str(path), line_number, line_number),))
                    )
        flush()
        return {
            "data": Table(("内容",), tuple(records)),
            "unmatched": Table(("内容",), tuple(unmatched)),
        }


class SerializeTable(Plugin):
    spec = PluginSpec(
        "table.serialize",
        "生成精确提交内容",
        "transform",
        "按当前行序与所选列序生成一段CSV或纯文本，明确表头、换行、尾部空行；可再接摘要或原文导出",
        inputs=("data",),
        outputs=("data",),
        category="编码与脱敏",
        parameters=(
            P("fields", list, "字段顺序；空为全部", default=[], widget="fields"),
            P("format", str, "序列化方式", default="csv", choices=("csv", "text")),
            P("delimiter", str, "字段分隔符", default=","),
            P("header", bool, "包含表头", default=True),
            P("line_ending", str, "换行符", default="lf", choices=("lf", "crlf")),
            P("trailing_blank_lines", int, "额外尾部空行数", default=0),
            P("output", str, "结果列", default="提交内容"),
        ),
    )

    def check_config(self, c):
        names(c["fields"], allow_empty=True)
        names([c["output"]])
        check_delimiter(c["delimiter"])
        if not 0 <= c["trailing_blank_lines"] <= 10:
            raise ValueError("额外空行数应为0到10")

    def run(self, inputs, c, context):
        table = inputs["data"]
        fields = c["fields"] or list(table.columns)
        table.require_columns(fields)
        ending = "\n" if c["line_ending"] == "lf" else "\r\n"
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, delimiter=c["delimiter"], lineterminator=ending)

        def write(values):
            if c["format"] == "csv":
                writer.writerow(values)
            else:
                if any("\r" in v or "\n" in v for v in values):
                    raise ValueError("纯文本字段含换行")
                stream.write(c["delimiter"].join(values) + ending)

        if c["header"]:
            write(fields)
        for record in table.records:
            context.check_cancelled()
            write([record.values[f] for f in fields])
        stream.write(ending * c["trailing_blank_lines"])
        # Avoid copying all per-cell changes into one enormous aggregate record.
        return {"data": Table((c["output"],), (Record({c["output"]: stream.getvalue()}),))}


class CollectRows(Plugin):
    spec = PluginSpec(
        "rows.collect",
        "按顺序拼接行",
        "transform",
        "将一列按当前行顺序拼成一个值，用于编号列表和提交摘要；不自动排序或去重",
        inputs=("data",),
        outputs=("data",),
        category="行处理",
        parameters=(
            P("field", str, "来源字段", required=True, widget="field"),
            P("separator", str, "行间连接符", default="_"),
            P("output", str, "结果字段", default="拼接结果"),
        ),
    )

    def check_config(self, c):
        names([c["field"]])
        names([c["output"]])

    def run(self, inputs, c, context):
        table = inputs["data"]
        table.require_columns([c["field"]])
        values = []
        for r in table.records:
            context.check_cancelled()
            values.append(r.values[c["field"]])
        return {
            "data": Table((c["output"],), (Record({c["output"]: c["separator"].join(values)}),))
        }


class VerifySignature(Plugin):
    spec = PluginSpec(
        "validate.signature",
        "RSA签名校验",
        "transform",
        "按逐行公钥路径验证消息签名；缺失公钥、签名格式错误或验签失败均附原因分流",
        inputs=("data",),
        outputs=("valid", "invalid"),
        category="数据校验",
        parameters=(
            P("message_field", str, "待验消息字段", required=True, widget="field"),
            P("signature_field", str, "签名字段", required=True, widget="field"),
            P(
                "key_path",
                str,
                "公钥PEM路径模板，例如 cert/{序号}.pem",
                required=True,
                widget="input_file_template",
            ),
            P("hash", str, "摘要算法", default="sha256", choices=("sha256", "sha384", "sha512")),
            P("padding", str, "签名填充", default="pkcs1v15", choices=("pkcs1v15", "pss")),
            P("signature_format", str, "签名编码", default="base64", choices=("base64", "hex")),
            P("encoding", str, "消息文本编码", default="utf-8"),
        ),
    )

    def check_config(self, c):
        names([c["message_field"]])
        names([c["signature_field"]])
        names([c["key_path"]])
        TemplateText.parts(c["key_path"])
        check_encoding(c["encoding"])

    def run(self, inputs, c, context):
        try:
            from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding, rsa
        except ImportError as exc:
            raise ValueError('验签需要安装可选依赖：pip install -e ".[crypto]"') from exc
        table = inputs["data"]
        parts = TemplateText.parts(c["key_path"])
        table.require_columns(
            [
                c["message_field"],
                c["signature_field"],
                *(f for _, f, _, _ in parts if f is not None),
            ]
        )
        valid, invalid = [], []
        cache = {}
        hash_type = {"sha256": hashes.SHA256, "sha384": hashes.SHA384, "sha512": hashes.SHA512}[
            c["hash"]
        ]
        for record in table.records:
            context.check_cancelled()
            try:
                value = "".join(
                    literal + (record.values[field] if field is not None else "")
                    for literal, field, _, _ in parts
                )
                path = context.resolve_path(value)
                context.source_paths.add(path)
                if path not in cache:
                    if path.stat().st_size > 1024 * 1024:
                        raise ValueError("公钥文件超过1MiB")
                    key = serialization.load_pem_public_key(path.read_bytes())
                    if not isinstance(key, rsa.RSAPublicKey):
                        raise ValueError("公钥不是RSA公钥")
                    if len(cache) >= 256:
                        cache.clear()
                    cache[path] = key
                raw = record.values[c["signature_field"]]
                signature = (
                    base64.b64decode(raw, validate=True)
                    if c["signature_format"] == "base64"
                    else bytes.fromhex(raw)
                )
                algorithm = hash_type()
                scheme = (
                    padding.PKCS1v15()
                    if c["padding"] == "pkcs1v15"
                    else padding.PSS(mgf=padding.MGF1(algorithm), salt_length=padding.PSS.AUTO)
                )
                cache[path].verify(
                    signature,
                    record.values[c["message_field"]].encode(c["encoding"]),
                    scheme,
                    algorithm,
                )
            except (InvalidSignature, UnsupportedAlgorithm, ValueError, OSError) as exc:
                invalid.append(
                    record.with_issue(
                        node=context.node_id,
                        field=c["signature_field"],
                        message="签名不匹配" if isinstance(exc, InvalidSignature) else str(exc),
                    )
                )
            else:
                valid.append(record)
        return {"valid": table.with_records(valid), "invalid": table.with_records(invalid)}


PLUGINS = [RealignColumns, TextRecords, SerializeTable, CollectRows, VerifySignature]
