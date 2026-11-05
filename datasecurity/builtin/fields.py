import re
import unicodedata

from datasecurity import Parameter as P, Plugin, PluginSpec, Table

from ._utils import map_values, names


class SelectColumns(Plugin):
    spec = PluginSpec(
        "columns.select",
        "选择字段",
        "transform",
        "按指定顺序保留字段，或删除指定字段",
        inputs=("data",),
        outputs=("data",),
        category="字段处理",
        parameters=(
            P("fields", list, "字段及顺序", required=True, widget="fields"),
            P("mode", str, "处理方式", default="keep", choices=("keep", "drop")),
        ),
    )

    def check_config(self, config):
        names(config["fields"])

    def run(self, inputs, config, context):
        table = inputs["data"]
        table.require_columns(config["fields"])
        columns = (
            config["fields"]
            if config["mode"] == "keep"
            else [col for col in table.columns if col not in config["fields"]]
        )
        if not columns:
            raise ValueError("至少保留一个字段")
        return {
            "data": map_values(
                table,
                context,
                lambda row: {col: row[col] for col in columns},
                columns=columns,
                reason="选择字段",
            )
        }


class RenameColumns(Plugin):
    spec = PluginSpec(
        "columns.rename",
        "重命名字段",
        "transform",
        "一次完成字段重命名；目标名称不能重复",
        inputs=("data",),
        outputs=("data",),
        category="字段处理",
        parameters=(
            P("mapping", dict, "原字段到新字段的对应关系", required=True, widget="mapping"),
        ),
    )

    def check_config(self, config):
        mapping = config["mapping"]
        if not mapping or any(
            not isinstance(k, str) or not isinstance(v, str) or not k.strip() or not v.strip()
            for k, v in mapping.items()
        ):
            raise ValueError("mapping 必须是非空的字段名映射")

    def run(self, inputs, config, context):
        table = inputs["data"]
        mapping = config["mapping"]
        table.require_columns(mapping)
        columns = [mapping.get(col, col) for col in table.columns]
        if len(set(columns)) != len(columns):
            raise ValueError("重命名后的字段发生冲突")
        return {
            "data": map_values(
                table,
                context,
                lambda row: {mapping.get(col, col): value for col, value in row.items()},
                columns=columns,
                reason="重命名字段",
            )
        }


class CleanText(Plugin):
    spec = PluginSpec(
        "text.clean",
        "文本整理",
        "transform",
        "清理空白、转换大小写或进行明确的 Unicode 规范化",
        inputs=("data",),
        outputs=("data",),
        category="文本处理",
        parameters=(
            P("fields", list, "处理字段", required=True, widget="fields"),
            P(
                "action",
                str,
                "整理方式",
                default="strip",
                choices=(
                    "strip",
                    "lstrip",
                    "rstrip",
                    "upper",
                    "lower",
                    "collapse_whitespace",
                    "remove_whitespace",
                ),
            ),
            P(
                "normalization",
                str,
                "Unicode 规范化",
                default="none",
                choices=("none", "NFC", "NFKC"),
            ),
        ),
    )

    def check_config(self, config):
        names(config["fields"])

    def run(self, inputs, config, context):
        table = inputs["data"]
        table.require_columns(config["fields"])

        def clean(value):
            if config["normalization"] != "none":
                value = unicodedata.normalize(config["normalization"], value)
            action = config["action"]
            if action == "collapse_whitespace":
                return re.sub(r"\s+", " ", value).strip()
            if action == "remove_whitespace":
                return re.sub(r"\s+", "", value)
            return getattr(value, action)()

        return {
            "data": map_values(
                table,
                context,
                lambda row: {**row, **{col: clean(row[col]) for col in config["fields"]}},
                reason="文本整理",
            )
        }


class ReplaceText(Plugin):
    spec = PluginSpec(
        "text.replace",
        "查找替换",
        "transform",
        "替换字面文本或正则匹配，记录每次实际改变",
        inputs=("data",),
        outputs=("data",),
        category="文本处理",
        parameters=(
            P("fields", list, "处理字段", required=True, widget="fields"),
            P("search", str, "查找内容", required=True),
            P("replacement", str, "替换内容", default=""),
            P("regex", bool, "使用正则表达式", default=False),
            P("count", int, "最多替换次数，0 表示全部", default=0),
        ),
    )

    def check_config(self, config):
        names(config["fields"])
        if not config["search"]:
            raise ValueError("查找内容不能为空")
        if config["count"] < 0:
            raise ValueError("count 不能为负数")
        if config["regex"]:
            re.compile(config["search"])

    def run(self, inputs, config, context):
        table = inputs["data"]
        table.require_columns(config["fields"])
        pattern = re.compile(config["search"]) if config["regex"] else None

        def convert(value):
            return (
                pattern.sub(config["replacement"], value, count=config["count"])
                if pattern
                else value.replace(config["search"], config["replacement"], config["count"] or -1)
            )

        return {
            "data": map_values(
                table,
                context,
                lambda row: {**row, **{col: convert(row[col]) for col in config["fields"]}},
                reason="查找替换",
            )
        }


class ExtractText(Plugin):
    spec = PluginSpec(
        "text.extract",
        "正则提取",
        "transform",
        "提取第一个匹配的捕获组；未匹配时填写空字符串并记录问题",
        inputs=("data",),
        outputs=("data",),
        category="文本处理",
        parameters=(
            P("field", str, "来源字段", required=True, widget="field"),
            P("pattern", str, "提取正则", required=True),
            P("group", int, "捕获组序号，0 表示完整匹配", default=1),
            P("output", str, "结果字段", default="提取结果"),
            P(
                "occurrence",
                str,
                "多个匹配时取首个或末个",
                default="first",
                choices=("first", "last"),
            ),
        ),
    )

    def check_config(self, config):
        pattern = re.compile(config["pattern"])
        if not 0 <= config["group"] <= pattern.groups:
            raise ValueError("捕获组序号超出范围")
        if not config["output"].strip():
            raise ValueError("结果字段不能为空")

    def run(self, inputs, config, context):
        table = inputs["data"]
        table.require_columns((config["field"],))
        pattern = re.compile(config["pattern"])
        columns = tuple(dict.fromkeys((*table.columns, config["output"])))
        records = []
        for record in table.records:
            context.check_cancelled()
            if config["occurrence"] == "first":
                match = pattern.search(record.values[config["field"]])
            else:
                match = None
                for candidate in pattern.finditer(record.values[config["field"]]):
                    context.check_cancelled()
                    match = candidate
            result = (match.group(config["group"]) or "") if match else ""
            updated = record.rebuild(
                {**record.values, config["output"]: result}, node=context.node_id, reason="正则提取"
            )
            if not match:
                updated = updated.with_issue(
                    node=context.node_id, field=config["field"], message="正则未匹配"
                )
            records.append(updated)
        return {"data": Table(columns, tuple(records))}


class SplitColumn(Plugin):
    spec = PluginSpec(
        "columns.split",
        "拆分字段",
        "transform",
        "按字面分隔符拆分；最后一列保留剩余内容，缺少的列补空字符串",
        inputs=("data",),
        outputs=("data",),
        category="字段处理",
        parameters=(
            P("field", str, "来源字段", required=True, widget="field"),
            P("separator", str, "分隔符", default=","),
            P("outputs", list, "结果字段名", default=["第1列", "第2列"], widget="names"),
            P("keep_source", bool, "保留原字段", default=True),
        ),
    )

    def check_config(self, config):
        names(config["outputs"])
        if len(config["outputs"]) < 2 or not config["separator"]:
            raise ValueError("需要至少两个结果字段和非空分隔符")

    def run(self, inputs, config, context):
        table = inputs["data"]
        field = config["field"]
        table.require_columns((field,))
        base = [col for col in table.columns if config["keep_source"] or col != field]
        if set(base) & set(config["outputs"]):
            raise ValueError("拆分结果与现有字段重名")
        columns = [*base, *config["outputs"]]

        def convert(row):
            parts = row[field].split(config["separator"], len(config["outputs"]) - 1)
            parts += [""] * (len(config["outputs"]) - len(parts))
            return {**{col: row[col] for col in base}, **dict(zip(config["outputs"], parts))}

        return {"data": map_values(table, context, convert, columns=columns, reason="拆分字段")}


class CombineColumns(Plugin):
    spec = PluginSpec(
        "columns.combine",
        "合并字段",
        "transform",
        "按指定顺序连接字段内容，写入一个结果字段",
        inputs=("data",),
        outputs=("data",),
        category="字段处理",
        parameters=(
            P("fields", list, "合并顺序", required=True, widget="fields"),
            P("separator", str, "连接符", default=" "),
            P("output", str, "结果字段", default="合并结果"),
            P("drop_sources", bool, "删除参与合并的原字段", default=False),
        ),
    )

    def check_config(self, config):
        names(config["fields"])
        if not config["output"].strip():
            raise ValueError("结果字段不能为空")

    def run(self, inputs, config, context):
        table = inputs["data"]
        table.require_columns(config["fields"])
        columns = [
            col
            for col in table.columns
            if not config["drop_sources"] or col not in config["fields"]
        ]
        columns = list(dict.fromkeys((*columns, config["output"])))

        def convert(row):
            result = config["separator"].join(row[col] for col in config["fields"])
            return {**{col: row[col] for col in columns if col in row}, config["output"]: result}

        return {"data": map_values(table, context, convert, columns=columns, reason="合并字段")}


class FillValues(Plugin):
    spec = PluginSpec(
        "values.fill",
        "填充空值",
        "transform",
        "填充空字符串；可选择把纯空白字符串也视为空值",
        inputs=("data",),
        outputs=("data",),
        category="字段处理",
        parameters=(
            P("fields", list, "处理字段", required=True, widget="fields"),
            P("value", str, "填充值", default=""),
            P("whitespace_empty", bool, "纯空白也视为空值", default=False),
        ),
    )

    def check_config(self, config):
        names(config["fields"])

    def run(self, inputs, config, context):
        table = inputs["data"]
        table.require_columns(config["fields"])

        def convert(row):
            changes = {
                col: config["value"]
                for col in config["fields"]
                if not (row[col].strip() if config["whitespace_empty"] else row[col])
            }
            return {**row, **changes}

        return {"data": map_values(table, context, convert, reason="填充空值")}


PLUGINS = [
    SelectColumns,
    RenameColumns,
    CleanText,
    ReplaceText,
    ExtractText,
    SplitColumn,
    CombineColumns,
    FillValues,
]
