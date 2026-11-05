"""Inspectable statistics and reference-data correction; no hidden inference."""

import json
from collections import Counter, defaultdict, deque
from datetime import datetime
from decimal import Decimal, localcontext

from datasecurity import Parameter as P, Plugin, PluginSpec, Table, Record
from ._utils import names, number


class Profile(Plugin):
    spec = PluginSpec(
        "profile.summary",
        "数据质量概览",
        "transform",
        "每列的空值、唯一值、数值格式数量、长度和高频值；原表可继续传递",
        inputs=("data",),
        outputs=("data", "summary"),
        category="统计分析",
        parameters=(
            P("fields", list, "分析字段；空为全部", default=[], widget="fields"),
            P("top", int, "高频值数量", default=5),
            P("whitespace_empty", bool, "纯空白视为空", default=True),
        ),
    )

    def check_config(self, c):
        names(c["fields"], allow_empty=True)
        if not 1 <= c["top"] <= 100:
            raise ValueError("高频值数量应为1到100")

    def run(self, inputs, c, context):
        table = inputs["data"]
        fields = c["fields"] or list(table.columns)
        table.require_columns(fields)
        rows = []
        for field in fields:
            counts = Counter()
            empty = numeric = 0
            lengths = []
            for record in table.records:
                context.check_cancelled()
                value = record.values[field]
                counts[value] += 1
                lengths.append(len(value))
                if not (value.strip() if c["whitespace_empty"] else value):
                    empty += 1
                else:
                    try:
                        number(value)
                        numeric += 1
                    except ValueError:
                        pass
            rows.append(
                {
                    "字段": field,
                    "总行数": str(len(table)),
                    "空值数": str(empty),
                    "唯一值数": str(len(counts)),
                    "数值格式数": str(numeric),
                    "最短长度": str(min(lengths, default=0)),
                    "最长长度": str(max(lengths, default=0)),
                    "高频值": json.dumps(counts.most_common(c["top"]), ensure_ascii=False),
                }
            )
        columns = (
            "字段",
            "总行数",
            "空值数",
            "唯一值数",
            "数值格式数",
            "最短长度",
            "最长长度",
            "高频值",
        )
        # Summary rows describe a column, not one source row. Do not invent lineage.
        return {"data": table, "summary": Table(columns, tuple(Record(row) for row in rows))}


class Lookup(Plugin):
    spec = PluginSpec(
        "tables.lookup",
        "字典表校正",
        "transform",
        "以唯一键查参考表，填补或替换目标字段；空键不匹配、重复参考键报错",
        inputs=("data", "reference"),
        outputs=("matched", "unmatched"),
        category="多表处理",
        parameters=(
            P("keys", list, "主表与参考表同名关联字段", required=True, widget="fields"),
            P("mapping", dict, "目标字段 → 参考表字段", required=True, widget="mapping"),
            P("mode", str, "校正方式", default="fill_empty", choices=("fill_empty", "replace")),
            P("whitespace_empty", bool, "纯空白视为空", default=True),
        ),
    )

    def check_config(self, c):
        names(c["keys"])
        if not c["mapping"] or any(not isinstance(v, str) for v in c["mapping"].values()):
            raise ValueError("mapping 必须是非空字段映射")
        names(list(c["mapping"]))
        names(list(dict.fromkeys(c["mapping"].values())))
        if set(c["keys"]) & set(c["mapping"]):
            raise ValueError("不能修改关联键")

    def run(self, inputs, c, context):
        table, reference = inputs["data"], inputs["reference"]
        table.require_columns(c["keys"])
        reference.require_columns([*c["keys"], *c["mapping"].values()])
        index = {}
        for record in reference.records:
            context.check_cancelled()
            key = tuple(record.values[f] for f in c["keys"])
            if any(not v.strip() for v in key):
                continue
            if key in index:
                raise ValueError(f"参考表关联键重复：{key}")
            index[key] = record
        columns = tuple(dict.fromkeys((*table.columns, *c["mapping"])))
        matched, unmatched = [], []
        for record in table.records:
            context.check_cancelled()
            key = tuple(record.values[f] for f in c["keys"])
            found = index.get(key) if all(v.strip() for v in key) else None
            values = {**record.values, **{f: record.values.get(f, "") for f in c["mapping"]}}
            if found is None:
                unmatched.append(
                    record.rebuild(values, node=context.node_id, reason="预留参考字段").with_issue(
                        node=context.node_id, field=",".join(c["keys"]), message="参考表未命中"
                    )
                )
                continue
            for target, source in c["mapping"].items():
                old = values[target].strip() if c["whitespace_empty"] else values[target]
                if c["mode"] == "replace" or not old:
                    values[target] = found.values[source]
            result = record.rebuild(values, node=context.node_id, reason="参考表校正")
            # The reference row supplied values; keep its source as evidence too.
            matched.append(
                Record(
                    result.values,
                    tuple(dict.fromkeys((*result.origins, *found.origins))),
                    result.issues,
                    result.changes,
                )
            )
        return {
            "matched": Table(columns, tuple(matched)),
            "unmatched": Table(columns, tuple(unmatched)),
        }


class Outliers(Plugin):
    spec = PluginSpec(
        "stats.outliers",
        "分组金额异常",
        "transform",
        "按分组计算均值/标准差，可选总体或样本口径；严格超过阈值分流，小组不足最小样本不判异常",
        inputs=("data",),
        outputs=("normal", "outliers", "invalid"),
        category="统计分析",
        parameters=(
            P("field", str, "数值字段", required=True, widget="field"),
            P("group_by", list, "分组字段；空为整体", default=[], widget="fields"),
            P("threshold", str, "标准差倍数", default="3"),
            P("min_count", int, "最小样本量", default=3),
            P("ddof", int, "方差自由度；0为总体，1为样本", default=0, choices=(0, 1)),
        ),
    )

    def check_config(self, c):
        names([c["field"]])
        names(c["group_by"], allow_empty=True)
        if number(c["threshold"]) <= 0 or c["min_count"] < 2:
            raise ValueError("倍数必须大于0，最小样本量至少2")

    def run(self, inputs, c, context):
        table = inputs["data"]
        table.require_columns([c["field"], *c["group_by"]])
        groups = defaultdict(list)
        bad = {}
        numbers = {}
        for i, r in enumerate(table.records):
            context.check_cancelled()
            try:
                value = number(r.values[c["field"]])
                if len(value.as_tuple().digits) > 100 or abs(value.adjusted()) > 100:
                    raise ValueError("统计数值精度或指数超过100")
            except ValueError as exc:
                bad[i] = r.with_issue(node=context.node_id, field=c["field"], message=str(exc))
            else:
                numbers[i] = value
                groups[tuple(r.values[f] for f in c["group_by"])].append(i)
        flagged = set()
        with localcontext() as dc:
            dc.prec = 256
            for indexes in groups.values():
                context.check_cancelled()
                if len(indexes) < c["min_count"]:
                    continue
                mean = sum(numbers[i] for i in indexes) / len(indexes)
                variance = sum((numbers[i] - mean) ** 2 for i in indexes) / (
                    len(indexes) - c["ddof"]
                )
                boundary = number(c["threshold"]) ** 2 * variance
                for i in indexes:
                    context.check_cancelled()
                    if (numbers[i] - mean) ** 2 > boundary:
                        flagged.add(i)
        return {
            "normal": table.with_records(
                r for i, r in enumerate(table.records) if i not in bad and i not in flagged
            ),
            "outliers": table.with_records(
                r.with_issue(
                    node=context.node_id, field=c["field"], message="偏离分组均值超过指定标准差倍数"
                )
                for i, r in enumerate(table.records)
                if i in flagged
            ),
            "invalid": table.with_records(bad.values()),
        }


class WindowCount(Plugin):
    spec = PluginSpec(
        "rows.window_count",
        "时间窗口计数",
        "transform",
        "按键统计闭区间[t-窗口,t]内的记录数或不同取值数；同一时刻一起计入，输出保持原顺序",
        inputs=("data",),
        outputs=("valid", "invalid"),
        category="统计分析",
        parameters=(
            P("time_field", str, "ISO时间字段", required=True, widget="field"),
            P("group_by", list, "分组字段", required=True, widget="fields"),
            P("seconds", int, "窗口秒数", default=3600),
            P("distinct_field", str, "不同值计数字段；空为记录数", default=""),
            P("output", str, "新增计数字段", default="窗口数量"),
        ),
    )

    def check_config(self, c):
        names([c["time_field"], c["output"]])
        names(c["group_by"])
        if not 1 <= c["seconds"] <= 31536000:
            raise ValueError("窗口范围为1秒到365天")

    def run(self, inputs, c, context):
        table = inputs["data"]
        table.require_columns(
            [c["time_field"], *c["group_by"], *filter(None, [c["distinct_field"]])]
        )
        if c["output"] in table.columns:
            raise ValueError("计数字段已存在")
        groups = defaultdict(list)
        results = {}
        invalid = {}
        awareness = None
        for i, r in enumerate(table.records):
            context.check_cancelled()
            try:
                dt = datetime.fromisoformat(r.values[c["time_field"]].replace("Z", "+00:00"))
                aware = dt.utcoffset() is not None
                if awareness is not None and awareness != aware:
                    raise ValueError("同一表不可混用带时区与无时区时间")
                awareness = aware
            except ValueError as exc:
                invalid[i] = str(exc)
            else:
                groups[tuple(r.values[f] for f in c["group_by"])].append((dt, i))
        for items in groups.values():
            items.sort()
            window = deque()
            counts = Counter()
            cursor = 0
            while cursor < len(items):
                context.check_cancelled()
                end = cursor + 1
                moment = items[cursor][0]
                while end < len(items) and items[end][0] == moment:
                    end += 1
                for dt, i in items[cursor:end]:
                    value = (
                        table.records[i].values[c["distinct_field"]] if c["distinct_field"] else ""
                    )
                    window.append((dt, value))
                    counts[value] += 1
                while window and (moment - window[0][0]).total_seconds() > c["seconds"]:
                    _, value = window.popleft()
                    counts[value] -= 1
                    if not counts[value]:
                        del counts[value]
                count = len(counts) if c["distinct_field"] else len(window)
                for _, i in items[cursor:end]:
                    results[i] = str(count)
                cursor = end
        valid, bad = [], []
        for i, r in enumerate(table.records):
            context.check_cancelled()
            result = r.rebuild(
                {**r.values, c["output"]: results.get(i, "")},
                node=context.node_id,
                reason="时间窗口计数",
            )
            if i in invalid:
                bad.append(
                    result.with_issue(
                        node=context.node_id, field=c["time_field"], message=invalid[i]
                    )
                )
            else:
                valid.append(result)
        columns = (*table.columns, c["output"])
        return {"valid": Table(columns, tuple(valid)), "invalid": Table(columns, tuple(bad))}


PLUGINS = [Profile, Lookup, Outliers, WindowCount]
