"""Explicit correction and local scoring. Reference answers never supply hidden repairs."""

import json
import unicodedata
from collections import defaultdict, deque
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

from datasecurity import Parameter as P, Plugin, PluginSpec, Record, Table
from ._utils import combined_record, names, number, text


def unique_index(table, keys):
    """Refuse ambiguous alignment instead of silently taking the first row."""
    table.require_columns(keys)
    result = {}
    for record in table.records:
        key = tuple(record.values[f] for f in keys)
        if any(not value.strip() for value in key) or key in result:
            raise ValueError("关联键为空或重复，无法唯一定位记录")
        result[key] = record
    return result


def ratio(correct, total):
    return Decimal(correct) / total if total else Decimal(1)


class ScoreTable(Plugin):
    spec = PluginSpec(
        "tables.score",
        "提交正确率与逐格差异",
        "transform",
        "按整行重复次数、唯一键或行位置评分；明确缺失、多余和逐格差异，需要独立标准答案",
        inputs=("answer", "candidate"),
        outputs=("summary", "differences", "fields", "missing", "extra"),
        category="统计分析",
        parameters=(
            P(
                "mode",
                str,
                "multiset按整行及重复次数；keyed按唯一键；position按当前行位置",
                default="multiset",
                choices=("multiset", "keyed", "position"),
            ),
            P(
                "keys",
                list,
                "keyed模式的唯一定位字段；键值始终精确匹配",
                default=[],
                widget="fields",
            ),
            P(
                "fields",
                list,
                "评分字段；空为标准表全部非键字段，且要求两表列集合相同",
                default=[],
                widget="fields",
            ),
            P(
                "metric",
                str,
                "用于阈值判断的指标；multiset只支持整行",
                default="row",
                choices=("row", "cell"),
            ),
            P("threshold", str, "达标阈值0到1，包含等号；例如0.95", default="0.95"),
            P("strip", bool, "比较值时去除首尾空白，不改原表", default=False),
            P("ignore_case", bool, "比较值时忽略大小写，不改原表", default=False),
        ),
    )

    def check_config(self, c):
        names(c["keys"], allow_empty=True)
        names(c["fields"], allow_empty=True)
        if not 0 <= number(c["threshold"]) <= 1:
            raise ValueError("阈值应在0到1之间")
        if (c["mode"] == "keyed") != bool(c["keys"]):
            raise ValueError("仅keyed模式需要非空keys")
        if c["mode"] == "multiset" and c["metric"] != "row":
            raise ValueError("multiset无法对错误行逐格配对，请选择整行指标")

    def run(self, inputs, c, context):
        answer, candidate = inputs["answer"], inputs["candidate"]
        fields = c["fields"] or [f for f in answer.columns if f not in c["keys"]]
        names(fields)
        if not c["fields"] and set(answer.columns) != set(candidate.columns):
            raise ValueError("两表字段不一致，请明确指定评分字段")
        answer.require_columns(fields)
        candidate.require_columns(fields)

        def normalized(value):
            value = value.strip() if c["strip"] else value
            return value.casefold() if c["ignore_case"] else value

        missing, extra, differences = [], [], []
        correct_rows = correct_cells = 0
        per_field = {f: 0 for f in fields}

        def difference(location, field, expected, actual, state, records):
            values = {
                "定位": location,
                "字段": field,
                "标准值": expected,
                "提交值": actual,
                "状态": state,
            }
            differences.append(combined_record(values, records))

        if c["mode"] == "multiset":
            available = defaultdict(deque)
            for position, record in enumerate(answer.records):
                context.check_cancelled()
                key = tuple(normalized(record.values[f]) for f in fields)
                available[key].append((position, record))
            used = set()
            for position, record in enumerate(candidate.records, 1):
                context.check_cancelled()
                key = tuple(normalized(record.values[f]) for f in fields)
                if available[key]:
                    used.add(available[key].popleft()[0])
                    correct_rows += 1
                else:
                    extra.append(record)
                    difference(
                        str(position),
                        "",
                        "",
                        json.dumps(dict(record.values), ensure_ascii=False),
                        "多余",
                        (record,),
                    )
            for position, record in enumerate(answer.records):
                if position not in used:
                    missing.append(record)
                    difference(
                        str(position + 1),
                        "",
                        json.dumps(dict(record.values), ensure_ascii=False),
                        "",
                        "缺失",
                        (record,),
                    )
            correct_cells = None  # No defensible cell pairing for unmatched rows.
        else:
            if c["mode"] == "keyed":
                expected = unique_index(answer, c["keys"])
                submitted = unique_index(candidate, c["keys"])
            else:
                expected = dict(enumerate(answer.records, 1))
                submitted = dict(enumerate(candidate.records, 1))
            for key, original in expected.items():
                context.check_cancelled()
                found = submitted.get(key)
                location = (
                    json.dumps(list(key), ensure_ascii=False)
                    if isinstance(key, tuple)
                    else str(key)
                )
                if found is None:
                    missing.append(original)
                row_correct = found is not None
                for field in fields:
                    equal = found is not None and normalized(original.values[field]) == normalized(
                        found.values[field]
                    )
                    if equal:
                        correct_cells += 1
                        per_field[field] += 1
                    else:
                        row_correct = False
                        difference(
                            location,
                            field,
                            original.values[field],
                            found.values[field] if found else "",
                            "不一致" if found else "缺失",
                            (original, found) if found else (original,),
                        )
                correct_rows += int(row_correct)
            for key, record in submitted.items():
                if key not in expected:
                    extra.append(record)
                    location = (
                        json.dumps(list(key), ensure_ascii=False)
                        if isinstance(key, tuple)
                        else str(key)
                    )
                    for field in fields:
                        difference(location, field, "", record.values[field], "多余", (record,))

        denominator = len(answer) + len(extra)
        # Empty expected data must not grant credit for nonempty submissions.
        row_score = ratio(correct_rows, denominator)
        cell_total = denominator * len(fields)
        score = row_score if c["metric"] == "row" else ratio(correct_cells, cell_total)
        numerator = correct_rows if c["metric"] == "row" else correct_cells
        total = denominator if c["metric"] == "row" else cell_total
        exact_score = Fraction(numerator, total) if total else Fraction(1)
        profile = (
            "整行多重集：正确行/(标准行+多余行)"
            if c["mode"] == "multiset"
            else "按唯一键对齐" if c["mode"] == "keyed" else "按行位置对齐"
        )
        if c["mode"] != "multiset":
            profile += "：正确行或格/(标准行或格+多余行或格)；错误格不另算多余"
        summary = {
            "模式": c["mode"],
            "评分单位": c["metric"],
            "正确行": str(correct_rows),
            "标准行": str(len(answer)),
            "提交行": str(len(candidate)),
            "缺失行": str(len(missing)),
            "多余行": str(len(extra)),
            "正确单元格": "不适用" if correct_cells is None else str(correct_cells),
            "单元格总数": "不适用" if correct_cells is None else str(cell_total),
            "正确率": text(score),
            "阈值": c["threshold"],
            "达标": "是" if exact_score >= Fraction(c["threshold"]) else "否",
            "口径": profile,
        }
        field_rows = (
            []
            if correct_cells is None
            else [
                {
                    "字段": f,
                    "正确": str(per_field[f]),
                    "标准": str(len(answer)),
                    "多余": str(len(extra)),
                    "正确率": text(ratio(per_field[f], denominator)),
                }
                for f in fields
            ]
        )
        return {
            "summary": Table(tuple(summary), (Record(summary),)),
            "differences": Table(("定位", "字段", "标准值", "提交值", "状态"), tuple(differences)),
            "fields": Table(
                ("字段", "正确", "标准", "多余", "正确率"), tuple(Record(row) for row in field_rows)
            ),
            "missing": answer.with_records(missing),
            "extra": candidate.with_records(extra),
        }


def edit_distance(left, right, limit):
    """Bounded Levenshtein distance in Unicode characters, not UTF-8 bytes."""
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


class FuzzyLookup(Plugin):
    spec = PluginSpec(
        "tables.fuzzy_lookup",
        "字典近似纠错候选",
        "transform",
        "按字符编辑距离查参考字典；默认只建议，启用应用时也拒绝并列最优；data始终保留全部行",
        inputs=("data", "reference"),
        outputs=("data", "review", "suggestions"),
        category="多表处理",
        parameters=(
            P("field", str, "待校正字段", required=True, widget="field"),
            P("reference_field", str, "字典中的标准值字段", required=True),
            P(
                "group_by",
                list,
                "两表同名分组字段，精确匹配后才搜索；空为全字典",
                default=[],
                widget="fields",
            ),
            P("max_distance", int, "最大字符编辑距离", default=1),
            P("top", int, "每条记录最多输出多少个候选", default=5),
            P("apply", bool, "将唯一最优候选写回data；默认仅提出建议", default=False),
            P("strip", bool, "匹配时忽略首尾空白", default=True),
            P(
                "normalization",
                str,
                "匹配时的Unicode规范化",
                default="none",
                choices=("none", "NFC", "NFKC"),
            ),
            P("ignore_case", bool, "匹配时忽略大小写", default=False),
            P("max_candidates", int, "单个分组的标准值数量上限", default=5000),
            P("max_comparisons", int, "整次执行的距离比较上限；超限明确报错", default=1000000),
        ),
    )

    def check_config(self, c):
        names([c["field"], c["reference_field"]])
        names(c["group_by"], allow_empty=True)
        if not 0 <= c["max_distance"] <= 10 or not 1 <= c["top"] <= 100:
            raise ValueError("距离应为0到10，候选数应为1到100")
        if not 1 <= c["max_candidates"] <= 100000 or not 1 <= c["max_comparisons"] <= 10000000:
            raise ValueError("候选上限应为1到100000，比较上限应为1到10000000")

    def run(self, inputs, c, context):
        table, reference = inputs["data"], inputs["reference"]
        table.require_columns([c["field"], *c["group_by"]])
        reference.require_columns([c["reference_field"], *c["group_by"]])

        def normalize(value):
            if c["normalization"] != "none":
                value = unicodedata.normalize(c["normalization"], value)
            value = value.strip() if c["strip"] else value
            return value.casefold() if c["ignore_case"] else value

        groups = defaultdict(dict)
        for record in reference.records:
            context.check_cancelled()
            canonical = record.values[c["reference_field"]]
            if not normalize(canonical):
                raise ValueError("参考字典含空标准值")
            key = tuple(record.values[f] for f in c["group_by"])
            groups[key].setdefault(canonical, record)
            if len(groups[key]) > c["max_candidates"]:
                raise ValueError("参考字典分组超过候选上限，请增加分组字段")
        data, review, suggestions = [], [], []
        cache, comparisons = {}, 0
        for position, record in enumerate(table.records, 1):
            context.check_cancelled()
            original = record.values[c["field"]]
            value = normalize(original)
            key = tuple(record.values[f] for f in c["group_by"])
            cache_key = (key, value)
            if cache_key not in cache:
                matches = []
                # Empty cells provide no evidence for a particular dictionary value.
                for canonical, source in groups.get(key, {}).items() if value else ():
                    context.check_cancelled()
                    comparisons += 1
                    if comparisons > c["max_comparisons"]:
                        raise ValueError("近似匹配超过max_comparisons，请缩小参考字典或分组")
                    target = normalize(canonical)
                    if max(len(value), len(target)) > 256:
                        raise ValueError("近似纠错仅接受最多256字符的字段")
                    distance = edit_distance(value, target, c["max_distance"])
                    if distance <= c["max_distance"]:
                        matches.append((distance, canonical, source))
                cache[cache_key] = sorted(matches, key=lambda item: (item[0], item[1]))
            matches = cache[cache_key]
            unique = bool(matches) and (len(matches) == 1 or matches[0][0] < matches[1][0])
            result = record
            reason = "没有候选" if not matches else "最优候选并列" if not unique else "待人工确认"
            if unique and matches[0][1] == original:
                pass
            elif unique and c["apply"]:
                distance, canonical, source = matches[0]
                result = record.with_updates(
                    {c["field"]: canonical},
                    node=context.node_id,
                    reason=f"唯一最优字典候选，编辑距离{distance}",
                )
                result = replace(
                    result, origins=tuple(dict.fromkeys((*result.origins, *source.origins)))
                )
            else:
                result = record.with_issue(node=context.node_id, field=c["field"], message=reason)
                review.append(result)
            data.append(result)
            for distance, canonical, source in matches[: c["top"]]:
                values = {
                    "记录位置": str(position),
                    "分组": json.dumps(list(key), ensure_ascii=False),
                    "字段": c["field"],
                    "原值": original,
                    "候选值": canonical,
                    "编辑距离": str(distance),
                    "唯一最优": "是" if unique and canonical == matches[0][1] else "否",
                }
                suggestions.append(combined_record(values, (record, source)))
        return {
            "data": table.with_records(data),
            "review": table.with_records(review),
            "suggestions": Table(
                ("记录位置", "分组", "字段", "原值", "候选值", "编辑距离", "唯一最优"),
                tuple(suggestions),
            ),
        }


class ApplyPatches(Plugin):
    spec = PluginSpec(
        "table.patch",
        "应用人工修订清单",
        "transform",
        "按唯一键定位，原值一致才修改；同一行所有修订一起通过或一起拒绝，保留来源与理由",
        inputs=("data", "patches"),
        outputs=("data", "rejected"),
        category="多表处理",
        parameters=(
            P("keys", list, "两表中同名的唯一定位字段，不能修改键", required=True, widget="fields"),
            P("field_column", str, "修订清单中记录目标字段名的列", default="字段"),
            P("before_column", str, "修订清单中记录预期原值的列", default="原值"),
            P("after_column", str, "修订清单中记录新值的列", default="新值"),
            P("reason_column", str, "修订理由列；空为不读取", default="理由"),
        ),
    )

    def check_config(self, c):
        names(c["keys"])
        columns = [
            c["field_column"],
            c["before_column"],
            c["after_column"],
            *filter(None, (c["reason_column"],)),
        ]
        names(columns)
        if set(columns) & set(c["keys"]):
            raise ValueError("修订内容列与关联键不能重名")

    def run(self, inputs, c, context):
        table, patches = inputs["data"], inputs["patches"]
        source = unique_index(table, c["keys"])
        patches.require_columns(
            [
                *c["keys"],
                c["field_column"],
                c["before_column"],
                c["after_column"],
                *filter(None, (c["reason_column"],)),
            ]
        )
        grouped = defaultdict(list)
        for patch in patches.records:
            grouped[tuple(patch.values[f] for f in c["keys"])].append(patch)
        updates, rejected = {}, []
        for key, rows in grouped.items():
            context.check_cancelled()
            original = source.get(key)
            seen, error = set(), ""
            for patch in rows:
                field = patch.values[c["field_column"]]
                if original is None:
                    error = "关联键未命中"
                elif field not in table.columns or field in c["keys"]:
                    error = "目标字段不存在或属于关联键"
                elif field in seen:
                    error = "同一字段存在重复修订"
                elif original.values[field] != patch.values[c["before_column"]]:
                    error = "原值已变化，拒绝覆盖"
                seen.add(field)
            if error:
                rejected.extend(
                    p.with_issue(node=context.node_id, field=c["field_column"], message=error)
                    for p in rows
                )
                continue
            result = original
            for patch in rows:
                field = patch.values[c["field_column"]]
                reason = patch.values[c["reason_column"]] if c["reason_column"] else "人工修订清单"
                result = result.with_updates(
                    {field: patch.values[c["after_column"]]},
                    node=context.node_id,
                    reason=reason or "人工修订清单",
                )
                result = replace(
                    result, origins=tuple(dict.fromkeys((*result.origins, *patch.origins)))
                )
            updates[key] = result
        return {
            "data": table.with_records(
                updates.get(tuple(r.values[f] for f in c["keys"]), r) for r in table.records
            ),
            "rejected": patches.with_records(rejected),
        }


PLUGINS = [ScoreTable, FuzzyLookup, ApplyPatches]
