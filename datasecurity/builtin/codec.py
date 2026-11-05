import base64
import hashlib
from urllib.parse import quote, unquote

from datasecurity import Parameter as P, Plugin, PluginSpec

from ._files import check_encoding
from ._utils import map_values, names


class CodecFields(Plugin):
    spec = PluginSpec(
        "codec.fields",
        "字段编解码",
        "transform",
        "编码、解码或生成摘要；失败记录单独分流，文本解码严格检查字符编码",
        inputs=("data",),
        outputs=("valid", "invalid"),
        category="编码与脱敏",
        parameters=(
            P("fields", list, "处理字段", required=True, widget="fields"),
            P(
                "operation",
                str,
                "操作",
                default="base64_decode",
                choices=(
                    "base64_encode",
                    "base64_decode",
                    "hex_encode",
                    "hex_decode",
                    "url_encode",
                    "url_decode",
                    "md5",
                    "sha256",
                    "sha512",
                ),
            ),
            P("encoding", str, "文本字符编码", default="utf-8"),
        ),
    )

    def check_config(self, config):
        names(config["fields"])
        check_encoding(config["encoding"])

    def run(self, inputs, config, context):
        table = inputs["data"]
        table.require_columns(config["fields"])
        operation = config["operation"]
        encoding = config["encoding"]

        def convert(value):
            if operation == "base64_encode":
                return base64.b64encode(value.encode(encoding)).decode("ascii")
            if operation == "base64_decode":
                return base64.b64decode(value, validate=True).decode(encoding)
            if operation == "hex_encode":
                return value.encode(encoding).hex()
            if operation == "hex_decode":
                return bytes.fromhex(value).decode(encoding)
            if operation == "url_encode":
                return quote(value, safe="", encoding=encoding)
            if operation == "url_decode":
                return unquote(value, encoding=encoding, errors="strict")
            return hashlib.new(operation, value.encode(encoding)).hexdigest()

        valid, invalid = [], []
        for record in table.records:
            context.check_cancelled()
            try:
                updates = {}
                for field in config["fields"]:
                    updates[field] = convert(record.values[field])
                valid.append(record.with_updates(updates, node=context.node_id, reason=operation))
            except (ValueError, UnicodeError) as exc:
                invalid.append(
                    record.with_issue(node=context.node_id, field=field, message=str(exc))
                )
        return {"valid": table.with_records(valid), "invalid": table.with_records(invalid)}


class MaskFields(Plugin):
    spec = PluginSpec(
        "text.mask",
        "字段脱敏",
        "transform",
        "保留前后指定字符，其余遮盖；短值全部遮盖",
        inputs=("data",),
        outputs=("data",),
        category="编码与脱敏",
        parameters=(
            P("fields", list, "脱敏字段", required=True, widget="fields"),
            P("keep_start", int, "保留前几位", default=3),
            P("keep_end", int, "保留后几位", default=4),
            P("character", str, "遮盖字符", default="*"),
        ),
    )

    def check_config(self, config):
        names(config["fields"])
        if min(config["keep_start"], config["keep_end"]) < 0 or len(config["character"]) != 1:
            raise ValueError("保留位数不能为负，遮盖字符必须为单字符")

    def run(self, inputs, config, context):
        table = inputs["data"]
        table.require_columns(config["fields"])

        def mask(value):
            start, end = config["keep_start"], config["keep_end"]
            if len(value) <= start + end:
                return config["character"] * len(value)
            return (
                value[:start]
                + config["character"] * (len(value) - start - end)
                + (value[-end:] if end else "")
            )

        return {
            "data": map_values(
                table,
                context,
                lambda row: {**row, **{field: mask(row[field]) for field in config["fields"]}},
                reason="字段脱敏",
            )
        }


PLUGINS = [CodecFields, MaskFields]
