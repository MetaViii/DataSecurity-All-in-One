import random
from collections import Counter
from functools import cmp_to_key

from datasecurity import Parameter as P, Plugin, PluginSpec, Table

from ._utils import names, number, parse_date


class Deduplicate(Plugin):
    spec = PluginSpec(
        "rows.deduplicate",
        "数据去重",
        "transform",
        "按字段去重，保持原顺序；重复分支保留被移除记录",
        inputs=("data",),
        outputs=("unique", "duplicates"),
        category="行处理",
        parameters=(
            P("fields", list, "依据字段，留空比较整行", default=[], widget="fields"),
            P("keep", str, "保留策略", default="first", choices=("first", "last", "none")),
        ),
    )

    def check_config(self, config):
        names(config["fields"], allow_empty=True)

    def run(self, inputs, config, context):
        table = inputs["data"]
        fields = config["fields"] or list(table.columns)
        table.require_columns(fields)
        keys = [tuple(record.values[col] for col in fields) for record in table.records]
        counts = Counter(keys)
        chosen = {}
        for index, key in enumerate(keys):
            context.check_cancelled()
            if key not in chosen or config["keep"] == "last":
                chosen[key] = index
        unique, duplicates = [], []
        for index, (key, record) in enumerate(zip(keys, table.records)):
            keep = counts[key] == 1 if config["keep"] == "none" else chosen[key] == index
            (unique if keep else duplicates).append(record)
        return {"unique": table.with_records(unique), "duplicates": table.with_records(duplicates)}


class SortRows(Plugin):
    spec = PluginSpec(
        "rows.sort",
        "多字段排序",
        "transform",
        "稳定排序；文本、精确数值或日期按字段分别指定",
        inputs=("data",),
        outputs=("data",),
        category="行处理",
        parameters=(
            P(
                "rules",
                list,
                "排序规则",
                default=[{"field": "", "type": "text", "direction": "asc"}],
                widget="sort_rules",
            ),
            P("empty", str, "空字符串位置", default="last", choices=("first", "last")),
        ),
    )

    def check_config(self, config):
        if not config["rules"]:
            raise ValueError("至少需要一条排序规则")
        for rule in config["rules"]:
            if not isinstance(rule, dict) or set(rule) - {"field", "type", "direction", "format"}:
                raise ValueError("排序规则字段无效")
            if not isinstance(rule.get("field"), str) or not rule["field"]:
                raise ValueError("请选择排序字段")
            if rule.get("type", "text") not in {"text", "number", "date"} or rule.get(
                "direction", "asc"
            ) not in {"asc", "desc"}:
                raise ValueError("排序类型或方向无效")

    def run(self, inputs, config, context):
        table = inputs["data"]
        rules = config["rules"]
        table.require_columns(rule["field"] for rule in rules)
        prepared = []
        for record in table.records:
            context.check_cancelled()
            values = []
            for rule in rules:
                value = record.values[rule["field"]]
                try:
                    values.append(
                        None
                        if value == ""
                        else (
                            number(value)
                            if rule.get("type") == "number"
                            else (
                                parse_date(value, rule.get("format", ""))
                                if rule.get("type") == "date"
                                else value
                            )
                        )
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"字段 {rule['field']}，源记录 {record.origins[0].record if record.origins else '?'}：{exc}"
                    ) from exc
            prepared.append((record, values))

        def compare(left, right):
            for a, b, rule in zip(left[1], right[1], rules):
                if a is None or b is None:
                    result = (
                        0
                        if a is b
                        else (-1 if a is None else 1) * (1 if config["empty"] == "first" else -1)
                    )
                else:
                    result = (a > b) - (a < b)
                    if rule.get("direction", "asc") == "desc":
                        result = -result
                if result:
                    return result
            return 0

        return {
            "data": table.with_records(
                record for record, _ in sorted(prepared, key=cmp_to_key(compare))
            )
        }


class SampleRows(Plugin):
    spec = PluginSpec(
        "rows.sample",
        "抽取记录",
        "transform",
        "有意选取部分记录；这会改变正式处理范围",
        inputs=("data",),
        outputs=("data",),
        category="行处理",
        parameters=(
            P("mode", str, "抽取方式", default="head", choices=("head", "random", "stride")),
            P("count", int, "最多保留条数", default=100),
            P("seed", int, "随机种子", default=42),
            P("stride", int, "间隔", default=2),
        ),
    )

    def check_config(self, config):
        if config["count"] < 0 or config["stride"] < 1:
            raise ValueError("count 不能为负，stride 至少为 1")

    def run(self, inputs, config, context):
        table = inputs["data"]
        count = min(config["count"], len(table))
        if config["mode"] == "random":
            indices = sorted(random.Random(config["seed"]).sample(range(len(table)), count))
            records = [table.records[index] for index in indices]
        else:
            records = (
                table.records[:: config["stride"]] if config["mode"] == "stride" else table.records
            )
            records = records[:count]
        return {"data": table.with_records(records)}


class MergeRows(Plugin):
    spec = PluginSpec(
        "rows.merge",
        "追加两张表",
        "transform",
        "按列名纵向追加；union 模式将缺少字段补为空字符串",
        inputs=("left", "right"),
        outputs=("data",),
        category="多表处理",
        parameters=(P("schema", str, "字段策略", default="strict", choices=("strict", "union")),),
    )

    def run(self, inputs, config, context):
        left, right = inputs["left"], inputs["right"]
        if config["schema"] == "strict" and set(left.columns) != set(right.columns):
            raise ValueError("两张表的字段不一致")
        columns = tuple(dict.fromkeys((*left.columns, *right.columns)))
        records = []
        for record in (*left.records, *right.records):
            context.check_cancelled()
            records.append(
                record.rebuild(
                    {col: record.values.get(col, "") for col in columns},
                    node=context.node_id,
                    reason="追加表格并对齐字段",
                )
            )
        return {"data": Table(columns, tuple(records))}


PLUGINS = [Deduplicate, SortRows, SampleRows, MergeRows]
