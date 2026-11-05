import re
from collections import Counter

from datasecurity import Parameter as P, Plugin, PluginSpec

from ._utils import number, parse_date
from .filter_rows import build_conditions


def prepare_rules(rules):
    if not rules:
        raise ValueError("至少配置一条校验规则")
    prepared = []
    for rule in rules:
        if (
            not isinstance(rule, dict)
            or not isinstance(rule.get("field"), str)
            or not rule["field"]
        ):
            raise ValueError("规则需要 field")
        kind = rule.get("check")
        specific = {
            "required": set(),
            "number": set(),
            "range": {"min", "max"},
            "regex": {"pattern"},
            "length": {"min", "max"},
            "enum": {"values"},
            "unique": set(),
            "date": {"format"},
            "equals_field": {"other"},
        }
        if kind not in specific:
            raise ValueError(f"不支持的校验：{kind}")
        if set(rule) - {"field", "check", "message", "allow_empty"} - specific[kind]:
            raise ValueError("校验规则包含未知配置")
        if "allow_empty" in rule and type(rule["allow_empty"]) is not bool:
            raise ValueError("allow_empty 必须是布尔值")
        if "message" in rule and not isinstance(rule["message"], str):
            raise ValueError("message 必须是字符串")
        if kind == "date" and not isinstance(rule.get("format", ""), str):
            raise ValueError("日期 format 必须是字符串")
        if kind == "regex":
            if not isinstance(rule.get("pattern"), str):
                raise ValueError("正则校验需要 pattern 字符串")
            re.compile(rule["pattern"])
        if kind == "enum" and (
            not isinstance(rule.get("values"), list)
            or any(not isinstance(value, str) for value in rule["values"])
        ):
            raise ValueError("枚举 values 必须是字符串列表")
        if kind == "equals_field" and (not isinstance(rule.get("other"), str) or not rule["other"]):
            raise ValueError("需要比较字段 other")
        if kind in {"range", "length"}:
            if "min" not in rule and "max" not in rule:
                raise ValueError("范围至少指定 min 或 max")
            bounds = []
            for name in ("min", "max"):
                if name in rule:
                    value = rule[name]
                    if kind == "length" and (type(value) is not int or value < 0):
                        raise ValueError("长度范围必须是非负整数")
                    if kind == "range" and type(value) not in (str, int):
                        raise ValueError("数值范围应填写数字字符串")
                    bounds.append(number(str(value)))
            if len(bounds) == 2 and bounds[0] > bounds[1]:
                raise ValueError("min 不能大于 max")
        prepared.append(rule)
    return prepared


class ValidateRules(Plugin):
    spec = PluginSpec(
        "validate.rules",
        "组合规则校验",
        "transform",
        "一次检查必填、范围、正则、枚举、唯一性、日期和字段一致性，汇总问题原因",
        inputs=("data",),
        outputs=("valid", "invalid"),
        category="数据校验",
        parameters=(
            P(
                "rules",
                list,
                "所有规则均通过才进入 valid",
                default=[{"field": "", "check": "required"}],
                widget="validation_rules",
            ),
        ),
    )

    def check_config(self, config):
        prepare_rules(config["rules"])

    def run(self, inputs, config, context):
        table = inputs["data"]
        rules = prepare_rules(config["rules"])
        table.require_columns(rule["field"] for rule in rules)
        table.require_columns(rule["other"] for rule in rules if rule["check"] == "equals_field")
        counts = {
            rule["field"]: Counter(record.values[rule["field"]] for record in table.records)
            for rule in rules
            if rule["check"] == "unique"
        }
        patterns = {
            index: re.compile(rule["pattern"])
            for index, rule in enumerate(rules)
            if rule["check"] == "regex"
        }
        valid, invalid = [], []
        for record in table.records:
            context.check_cancelled()
            updated = record
            failures = 0
            for index, rule in enumerate(rules):
                value = record.values[rule["field"]]
                kind = rule["check"]
                if value == "" and rule.get("allow_empty") and kind != "required":
                    continue
                try:
                    if kind == "required":
                        passed = bool(value.strip())
                    elif kind == "number":
                        number(value)
                        passed = True
                    elif kind == "range":
                        actual = number(value)
                        passed = ("min" not in rule or actual >= number(str(rule["min"]))) and (
                            "max" not in rule or actual <= number(str(rule["max"]))
                        )
                    elif kind == "length":
                        passed = rule.get("min", 0) <= len(value) <= rule.get("max", len(value))
                    elif kind == "regex":
                        passed = patterns[index].fullmatch(value) is not None
                    elif kind == "enum":
                        passed = value in rule["values"]
                    elif kind == "unique":
                        passed = counts[rule["field"]][value] == 1
                    elif kind == "date":
                        parse_date(value, rule.get("format", ""))
                        passed = True
                    else:
                        passed = value == record.values[rule["other"]]
                except ValueError:
                    passed = False
                if not passed:
                    failures += 1
                    updated = updated.with_issue(
                        node=context.node_id,
                        field=rule["field"],
                        message=rule.get("message") or f"{rule['field']} 未通过 {kind} 校验",
                    )
            (invalid if failures else valid).append(updated)
        return {"valid": table.with_records(valid), "invalid": table.with_records(invalid)}


class ClassifyRows(Plugin):
    spec = PluginSpec(
        "rows.classify",
        "条件分类",
        "transform",
        "按规则顺序匹配，写入第一个命中的分类标签",
        inputs=("data",),
        outputs=("data",),
        category="计算与分类",
        parameters=(
            P(
                "rules",
                list,
                "每条包含 label、conditions 和 match",
                default=[
                    {
                        "label": "分类1",
                        "conditions": [{"field": "", "op": "eq", "value": ""}],
                        "match": "all",
                    }
                ],
                widget="case_rules",
            ),
            P("default", str, "未命中时的标签", default="其他"),
            P("output", str, "分类字段", default="分类"),
        ),
    )

    def check_config(self, config):
        if not config["rules"] or not config["output"].strip():
            raise ValueError("需要规则和结果字段")
        for rule in config["rules"]:
            if (
                not isinstance(rule, dict)
                or set(rule) - {"label", "conditions", "match"}
                or not isinstance(rule.get("label"), str)
            ):
                raise ValueError("分类规则无效")
            if rule.get("match", "all") not in {"all", "any"}:
                raise ValueError("match 只能是 all 或 any")
            build_conditions(rule.get("conditions", []))

    def run(self, inputs, config, context):
        from ._utils import map_values

        table = inputs["data"]
        rules = [
            (
                rule["label"],
                build_conditions(rule["conditions"]),
                all if rule.get("match", "all") == "all" else any,
            )
            for rule in config["rules"]
        ]
        table.require_columns(field for _, conditions, _ in rules for field, _ in conditions)

        def convert(row):
            label = next(
                (
                    label
                    for label, conditions, combine in rules
                    if combine(test(row[field]) for field, test in conditions)
                ),
                config["default"],
            )
            return {**row, config["output"]: label}

        columns = tuple(dict.fromkeys((*table.columns, config["output"])))
        return {"data": map_values(table, context, convert, columns=columns, reason="条件分类")}


PLUGINS = [ValidateRules, ClassifyRows]
