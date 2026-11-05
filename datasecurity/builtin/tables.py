from collections import defaultdict, deque
from decimal import Decimal, ROUND_HALF_UP

from datasecurity import Parameter as P, Plugin, PluginSpec, Table

from ._utils import combined_record, names, number, text


class JoinTables(Plugin):
    spec = PluginSpec(
        "tables.join",
        "按键关联",
        "transform",
        "按键连接两张表；重复键按关系连接展开，保留两侧来源",
        inputs=("left", "right"),
        outputs=("data",),
        category="多表处理",
        parameters=(
            P("left_keys", list, "左表键", required=True, widget="fields"),
            P("right_keys", list, "右表键", required=True, widget="fields"),
            P("how", str, "连接方式", default="left", choices=("left", "inner", "full")),
            P("suffix", str, "右表重名后缀", default="_right"),
            P("match_empty", bool, "允许空字符串键相互匹配", default=False),
            P("max_rows", int, "结果行数上限，超过时明确报错", default=1000000),
        ),
    )

    def check_config(self, config):
        names(config["left_keys"])
        names(config["right_keys"])
        if len(config["left_keys"]) != len(config["right_keys"]):
            raise ValueError("左右键数量必须一致")
        if not config["suffix"] or config["max_rows"] < 1:
            raise ValueError("后缀不能为空，行数上限必须为正数")

    def run(self, inputs, config, context):
        left, right = inputs["left"], inputs["right"]
        left.require_columns(config["left_keys"])
        right.require_columns(config["right_keys"])
        columns = list(left.columns)
        right_names = {}
        for column in right.columns:
            candidate = column
            while candidate in columns:
                candidate += config["suffix"]
            columns.append(candidate)
            right_names[column] = candidate
        index = defaultdict(list)
        for position, record in enumerate(right.records):
            key = tuple(record.values[col] for col in config["right_keys"])
            if config["match_empty"] or all(value != "" for value in key):
                index[key].append((position, record))
        records, used = [], set()

        def append(a, b):
            if len(records) >= config["max_rows"]:
                raise ValueError("连接结果超过 max_rows，请检查重复键或提高上限")
            values = {column: a.values[column] if a else "" for column in left.columns}
            values.update(
                {right_names[column]: b.values[column] if b else "" for column in right.columns}
            )
            records.append(
                combined_record(values, [record for record in (a, b) if record is not None])
            )

        for record in left.records:
            context.check_cancelled()
            key = tuple(record.values[col] for col in config["left_keys"])
            matches = (
                index.get(key, [])
                if config["match_empty"] or all(value != "" for value in key)
                else []
            )
            if matches:
                for position, other in matches:
                    used.add(position)
                    append(record, other)
            elif config["how"] != "inner":
                append(record, None)
        if config["how"] == "full":
            for position, record in enumerate(right.records):
                if position not in used:
                    append(None, record)
        return {"data": Table(tuple(columns), tuple(records))}


class Aggregate(Plugin):
    spec = PluginSpec(
        "group.aggregate",
        "分组统计",
        "transform",
        "分组计数、求和、均值、最值和去重计数；数值使用 Decimal",
        inputs=("data",),
        outputs=("data",),
        category="统计分析",
        parameters=(
            P("group_by", list, "分组字段，留空统计全表", default=[], widget="fields"),
            P(
                "measures",
                list,
                "统计项",
                default=[{"op": "count", "field": "", "output": "数量"}],
                widget="aggregate_rules",
            ),
            P("ignore_empty", bool, "数值统计与去重计数忽略空字符串", default=True),
            P("decimal_places", int, "均值保留小数位，采用四舍五入", default=6),
        ),
    )

    def check_config(self, config):
        names(config["group_by"], allow_empty=True)
        if not 0 <= config["decimal_places"] <= 16 or not config["measures"]:
            raise ValueError("均值位数需为 0～16，且至少有一个统计项")
        outputs = list(config["group_by"])
        for measure in config["measures"]:
            if not isinstance(measure, dict) or set(measure) - {"op", "field", "output"}:
                raise ValueError("统计项格式无效")
            if measure.get("op") not in {"count", "sum", "mean", "min", "max", "distinct_count"}:
                raise ValueError("不支持的统计方式")
            if not isinstance(measure.get("output"), str) or not measure["output"].strip():
                raise ValueError("统计项需要结果名称")
            if measure["op"] != "count" and not measure.get("field"):
                raise ValueError("统计项需要字段")
            outputs.append(measure["output"])
        if len(set(outputs)) != len(outputs):
            raise ValueError("统计结果字段重名")

    def run(self, inputs, config, context):
        table = inputs["data"]
        table.require_columns(
            [
                *config["group_by"],
                *(item["field"] for item in config["measures"] if item["op"] != "count"),
            ]
        )
        groups = defaultdict(list)
        for record in table.records:
            context.check_cancelled()
            groups[tuple(record.values[col] for col in config["group_by"])].append(record)
        if not groups and not config["group_by"]:
            groups[()] = []
        columns = (*config["group_by"], *(item["output"] for item in config["measures"]))
        records = []
        for key, members in groups.items():
            values = dict(zip(config["group_by"], key))
            for measure in config["measures"]:
                operation = measure["op"]
                if operation == "count":
                    result = str(len(members))
                else:
                    raw = [record.values[measure["field"]] for record in members]
                    raw = [value for value in raw if value != ""] if config["ignore_empty"] else raw
                    if operation == "distinct_count":
                        result = str(len(set(raw)))
                    else:
                        numbers = [number(value) for value in raw]
                        if not numbers:
                            result = ""
                        elif operation == "sum":
                            result = text(sum(numbers, Decimal(0)))
                        elif operation in {"min", "max"}:
                            result = text(min(numbers) if operation == "min" else max(numbers))
                        else:
                            mean = (sum(numbers, Decimal(0)) / len(numbers)).quantize(
                                Decimal(1).scaleb(-config["decimal_places"]), rounding=ROUND_HALF_UP
                            )
                            result = text(mean)
                values[measure["output"]] = result
            records.append(combined_record(values, members))
        return {"data": Table(tuple(columns), tuple(records))}


class CompareTables(Plugin):
    spec = PluginSpec(
        "tables.compare",
        "答案对比",
        "transform",
        "按完整记录及重复次数比较；输出命中、缺失、多余和一份评分摘要",
        inputs=("answer", "candidate"),
        outputs=("summary", "matched", "missing", "extra"),
        category="统计分析",
        parameters=(
            P("fields", list, "比较字段，留空要求两表字段集合一致", default=[], widget="fields"),
        ),
    )

    def check_config(self, config):
        names(config["fields"], allow_empty=True)

    def run(self, inputs, config, context):
        answer, candidate = inputs["answer"], inputs["candidate"]
        fields = config["fields"] or list(answer.columns)
        if not config["fields"] and set(answer.columns) != set(candidate.columns):
            raise ValueError("两张表字段不一致，请明确指定比较字段")
        answer.require_columns(fields)
        candidate.require_columns(fields)
        available = defaultdict(deque)
        for position, record in enumerate(answer.records):
            available[tuple(record.values[col] for col in fields)].append((position, record))
        used, matched, extra = set(), [], []
        for record in candidate.records:
            context.check_cancelled()
            key = tuple(record.values[col] for col in fields)
            if available[key]:
                position, original = available[key].popleft()
                used.add(position)
                matched.append(
                    combined_record({col: record.values[col] for col in fields}, (original, record))
                )
            else:
                extra.append(record)
        missing = [record for position, record in enumerate(answer.records) if position not in used]
        denominator = len(matched) + len(missing) + len(extra)
        score = Decimal(len(matched)) / denominator if denominator else Decimal(1)
        summary = Table.from_rows(
            ("正确", "缺失", "多余", "得分", "口径"),
            [
                {
                    "正确": str(len(matched)),
                    "缺失": str(len(missing)),
                    "多余": str(len(extra)),
                    "得分": text(score.quantize(Decimal("0.000001"))),
                    "口径": "正确/(正确+缺失+多余)，空集对空集为1",
                }
            ],
            source=f"compare:{context.node_id}",
        )
        return {
            "summary": summary,
            "matched": Table(tuple(fields), tuple(matched)),
            "missing": answer.with_records(missing),
            "extra": candidate.with_records(extra),
        }


PLUGINS = [JoinTables, Aggregate, CompareTables]
