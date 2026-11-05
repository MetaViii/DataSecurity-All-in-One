from __future__ import annotations

import re
from typing import Callable

from datasecurity import Parameter, Plugin, PluginSpec
from ._utils import number


def build_conditions(rules: list) -> list[tuple[str, Callable[[str], bool]]]:
    if not rules:
        raise ValueError("conditions 至少需要一条条件")
    conditions = []
    for index, rule in enumerate(rules, 1):
        if (
            not isinstance(rule, dict)
            or not isinstance(rule.get("field"), str)
            or not rule["field"]
        ):
            raise ValueError(f"第 {index} 条条件缺少 field")
        operation = rule.get("op")
        if operation in {"eq", "ne", "contains", "not_contains", "regex", "gt", "gte", "lt", "lte"}:
            allowed = {"field", "op", "value"}
            value = rule.get("value")
            if not isinstance(value, str):
                raise ValueError(f"第 {index} 条条件的 value 必须是字符串")
            if operation == "eq":

                def predicate(text, expected=value):
                    return text == expected

            elif operation == "ne":

                def predicate(text, expected=value):
                    return text != expected

            elif operation == "contains":

                def predicate(text, expected=value):
                    return expected in text

            elif operation == "not_contains":

                def predicate(text, expected=value):
                    return expected not in text

            elif operation in {"gt", "gte", "lt", "lte"}:
                expected = number(value)

                def predicate(text, expected=expected, operation=operation):
                    try:
                        actual = number(text)
                    except ValueError:
                        return False
                    return {
                        "gt": actual > expected,
                        "gte": actual >= expected,
                        "lt": actual < expected,
                        "lte": actual <= expected,
                    }[operation]

            else:
                try:
                    pattern = re.compile(value)
                except re.error as exc:
                    raise ValueError(f"第 {index} 条条件的正则无效：{exc}") from exc

                def predicate(text, pattern=pattern):
                    return pattern.search(text) is not None

        elif operation == "length":
            allowed = {"field", "op", "min", "max"}
            minimum, maximum = rule.get("min", 0), rule.get("max")
            if type(minimum) is not int or type(maximum) is not int or not 0 <= minimum <= maximum:
                raise ValueError(f"第 {index} 条条件需要 0 <= min <= max 的整数范围")

            def predicate(text, low=minimum, high=maximum):
                return low <= len(text) <= high

        elif operation in {"empty", "not_empty"}:
            allowed = {"field", "op"}
            predicate = (
                (lambda text: text == "") if operation == "empty" else (lambda text: text != "")
            )
        else:
            raise ValueError(f"第 {index} 条条件的 op 不支持：{operation}")
        unknown = set(rule) - allowed
        if unknown:
            raise ValueError(f"第 {index} 条条件包含未知参数：{', '.join(sorted(unknown))}")
        conditions.append((rule["field"], predicate))
    return conditions


class FilterRows(Plugin):
    spec = PluginSpec(
        id="rows.filter",
        name="条件筛选",
        kind="transform",
        description="按多条字符串条件进行 AND/OR 筛选，同时保留满足与不满足的两个分支",
        inputs=("data",),
        outputs=("matched", "unmatched"),
        category="行处理",
        parameters=(
            Parameter(
                "conditions",
                list,
                "条件列表：field、op 和对应参数",
                required=True,
                widget="conditions",
            ),
            Parameter(
                "match",
                str,
                "all 表示全部满足，any 表示任一满足",
                default="all",
                choices=("all", "any"),
            ),
        ),
    )

    def check_config(self, config):
        build_conditions(config["conditions"])

    def run(self, inputs, config, context):
        table = inputs["data"]
        conditions = build_conditions(config["conditions"])
        table.require_columns(field for field, _ in conditions)
        combine = all if config["match"] == "all" else any
        matched, unmatched = [], []
        for record in table.records:
            context.check_cancelled()
            accepted = combine(predicate(record.values[field]) for field, predicate in conditions)
            (matched if accepted else unmatched).append(record)
        return {"matched": table.with_records(matched), "unmatched": table.with_records(unmatched)}
