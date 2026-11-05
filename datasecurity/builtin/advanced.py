"""Small, explicit transformations for messy tabular contest attachments.

Every cell remains a string. Row failures go to a separate branch when an
operation can reject data; configuration mistakes stop the node instead.
"""

import json
import re
from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    localcontext,
)
from string import Formatter

from datasecurity import Parameter as P, Plugin, PluginSpec, Table

from ._utils import map_values, names
from .file_inputs import scalar


def require_name(value, label="字段"):
    if not value.strip():
        raise ValueError(f"{label}不能为空")


def string_mapping(mapping):
    if not mapping or any(type(k) is not str or type(v) is not str for k, v in mapping.items()):
        raise ValueError("mapping 必须是非空的字符串到字符串映射")


class MapValues(Plugin):
    spec = PluginSpec(
        "values.map",
        "字典映射",
        "transform",
        "用明确的字典统一字段取值；未命中记录独立分流",
        inputs=("data",),
        outputs=("matched", "unmatched"),
        category="字段处理",
        parameters=(
            P("field", str, "来源字段", required=True, widget="field"),
            P("mapping", dict, "原值到标准值的映射", required=True, widget="mapping"),
            P("output", str, "结果字段；留空修改原字段", default=""),
            P("strip", bool, "匹配前去除首尾空白", default=False),
            P("ignore_case", bool, "匹配时忽略大小写", default=False),
        ),
    )

    @staticmethod
    def key(value, config):
        value = value.strip() if config["strip"] else value
        return value.casefold() if config["ignore_case"] else value

    def check_config(self, config):
        require_name(config["field"])
        string_mapping(config["mapping"])
        keys = [self.key(key, config) for key in config["mapping"]]
        if len(set(keys)) != len(keys):
            raise ValueError("字典键在去空白/忽略大小写后重复，请明确唯一映射")
        if config["output"] and not config["output"].strip():
            raise ValueError("结果字段不能只有空白")

    def run(self, inputs, config, context):
        table = inputs["data"]
        field, output = config["field"], config["output"] or config["field"]
        table.require_columns((field,))
        columns = tuple(dict.fromkeys((*table.columns, output)))
        mapping = {self.key(key, config): value for key, value in config["mapping"].items()}
        matched, unmatched = [], []
        for record in table.records:
            context.check_cancelled()
            key = self.key(record.values[field], config)
            if key in mapping:
                matched.append(
                    record.rebuild(
                        {**record.values, output: mapping[key]},
                        node=context.node_id,
                        reason="字典映射",
                    )
                )
            else:
                # Existing columns remain intact even when output names another column.
                values = {**record.values, output: record.values.get(output, "")}
                unmatched.append(
                    record.rebuild(
                        values, node=context.node_id, reason="预留映射结果字段"
                    ).with_issue(node=context.node_id, field=field, message="字典未命中")
                )
        return {
            "matched": Table(columns, tuple(matched)),
            "unmatched": Table(columns, tuple(unmatched)),
        }


class CoalesceValues(Plugin):
    spec = PluginSpec(
        "values.coalesce",
        "按优先级取值",
        "transform",
        "按字段顺序取第一个非空值，适合多来源字段回填",
        inputs=("data",),
        outputs=("data",),
        category="字段处理",
        parameters=(
            P("fields", list, "字段优先级", required=True, widget="fields"),
            P("output", str, "结果字段", default="合并值"),
            P("fallback", str, "全部为空时的值", default=""),
            P("whitespace_empty", bool, "纯空白也视为空值", default=False),
        ),
    )

    def check_config(self, config):
        names(config["fields"])
        require_name(config["output"], "结果字段")

    def run(self, inputs, config, context):
        table = inputs["data"]
        table.require_columns(config["fields"])
        columns = tuple(dict.fromkeys((*table.columns, config["output"])))

        def convert(row):
            value = next(
                (
                    row[field]
                    for field in config["fields"]
                    if (row[field].strip() if config["whitespace_empty"] else row[field])
                ),
                config["fallback"],
            )
            return {**row, config["output"]: value}

        return {"data": map_values(table, context, convert, columns=columns, reason="按优先级取值")}


class NumberRows(Plugin):
    spec = PluginSpec(
        "rows.number",
        "添加序号",
        "transform",
        "按当前记录顺序生成序号；不会重新排序",
        inputs=("data",),
        outputs=("data",),
        category="行处理",
        parameters=(
            P("output", str, "新增序号字段", default="序号"),
            P("start", int, "起始序号", default=1),
            P("step", int, "递增步长", default=1),
            P("width", int, "最小位数，0 不补零", default=0),
        ),
    )

    def check_config(self, config):
        require_name(config["output"], "序号字段")
        if config["step"] == 0 or not 0 <= config["width"] <= 100:
            raise ValueError("步长不能为 0，补零位数应在 0 到 100 之间")

    def run(self, inputs, config, context):
        table = inputs["data"]
        output = config["output"]
        if output in table.columns:
            raise ValueError("序号字段已存在，请使用新字段名")
        records = []
        for index, record in enumerate(table.records):
            context.check_cancelled()
            value = str(config["start"] + index * config["step"]).zfill(config["width"])
            records.append(
                record.rebuild(
                    {**record.values, output: value}, node=context.node_id, reason="添加序号"
                )
            )
        return {"data": Table((*table.columns, output), tuple(records))}


class ExplodeRows(Plugin):
    spec = PluginSpec(
        "rows.explode",
        "多值拆成多行",
        "transform",
        "按字面分隔符展开一个字段，其他字段及来源随行复制",
        inputs=("data",),
        outputs=("data",),
        category="行处理",
        parameters=(
            P("field", str, "多值字段", required=True, widget="field"),
            P("separator", str, "字面分隔符", default=","),
            P("output", str, "结果字段；留空修改原字段", default=""),
            P("strip", bool, "去除每项首尾空白", default=False),
            P("keep_empty", bool, "保留空项", default=True),
            P("max_rows", int, "结果行数上限", default=1000000),
        ),
    )

    def check_config(self, config):
        require_name(config["field"])
        if not config["separator"] or config["max_rows"] < 1:
            raise ValueError("分隔符不能为空，结果行数上限必须为正数")
        if config["output"] and not config["output"].strip():
            raise ValueError("结果字段不能只有空白")

    def run(self, inputs, config, context):
        table = inputs["data"]
        field, output = config["field"], config["output"] or config["field"]
        table.require_columns((field,))
        columns = tuple(dict.fromkeys((*table.columns, output)))
        records = []
        for record in table.records:
            context.check_cancelled()
            # Limit split allocation too, not just the final result table.
            parts = record.values[field].split(config["separator"], config["max_rows"])
            if len(parts) > config["max_rows"]:
                raise ValueError("单条记录拆分项数超过 max_rows")
            for value in parts:
                context.check_cancelled()
                value = value.strip() if config["strip"] else value
                if not value and not config["keep_empty"]:
                    continue
                if len(records) >= config["max_rows"]:
                    raise ValueError("拆分结果超过 max_rows")
                records.append(
                    record.rebuild(
                        {**record.values, output: value},
                        node=context.node_id,
                        reason="多值拆成多行",
                    )
                )
        return {"data": Table(columns, tuple(records))}


class UnpivotColumns(Plugin):
    spec = PluginSpec(
        "columns.unpivot",
        "宽表转长表",
        "transform",
        "把选中字段转换为字段名/值两列，其他字段作为标识保留",
        inputs=("data",),
        outputs=("data",),
        category="字段处理",
        parameters=(
            P("fields", list, "待展开字段", required=True, widget="fields"),
            P("name_output", str, "字段名列", default="字段"),
            P("value_output", str, "值列", default="值"),
            P("keep_empty", bool, "保留空字符串", default=True),
            P("max_rows", int, "结果行数上限", default=1000000),
        ),
    )

    def check_config(self, config):
        names(config["fields"])
        names([config["name_output"], config["value_output"]])
        if config["max_rows"] < 1:
            raise ValueError("结果行数上限必须为正数")

    def run(self, inputs, config, context):
        table = inputs["data"]
        table.require_columns(config["fields"])
        base = [col for col in table.columns if col not in config["fields"]]
        output_names = (config["name_output"], config["value_output"])
        if set(base) & set(output_names):
            raise ValueError("输出字段与保留字段重名")
        records = []
        for record in table.records:
            context.check_cancelled()
            for field in config["fields"]:
                context.check_cancelled()
                value = record.values[field]
                if not value and not config["keep_empty"]:
                    continue
                if len(records) >= config["max_rows"]:
                    raise ValueError("展开结果超过 max_rows")
                values = {
                    **{col: record.values[col] for col in base},
                    output_names[0]: field,
                    output_names[1]: value,
                }
                records.append(record.rebuild(values, node=context.node_id, reason="宽表转长表"))
        return {"data": Table((*base, *output_names), tuple(records))}


def pointer_tokens(pointer):
    """RFC 6901 string form, without URI fragments or a JSONPath evaluator."""
    if pointer == "":
        return []
    if not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise ValueError("JSON 路径必须为 JSON Pointer，例如 /user/name 或 /items/0/id")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def resolve_pointer(value, tokens):
    for token in tokens:
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
            # Compare lengths before int conversion, including hostile enormous indexes.
            if len(token) > len(str(len(value))) or int(token) >= len(value):
                raise ValueError("JSON 数组索引越界")
            value = value[int(token)]
        else:
            raise ValueError(f"JSON 路径不存在或类型不符：{token}")
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 包含重复键：{key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"JSON 不接受 {value}")


class ExtractJson(Plugin):
    spec = PluginSpec(
        "json.extract",
        "提取 JSON 字段",
        "transform",
        "从单元格 JSON 按 JSON Pointer 提取字段；失败记录完整保留并分流",
        inputs=("data",),
        outputs=("valid", "invalid"),
        category="文本处理",
        parameters=(
            P("field", str, "包含 JSON 的字段", required=True, widget="field"),
            P(
                "mapping",
                dict,
                "新增字段到 JSON Pointer 的映射，如 姓名 → /user/name",
                required=True,
                widget="mapping",
            ),
        ),
    )

    def check_config(self, config):
        require_name(config["field"])
        string_mapping(config["mapping"])
        names(list(config["mapping"]))
        for pointer in config["mapping"].values():
            pointer_tokens(pointer)

    def run(self, inputs, config, context):
        table = inputs["data"]
        table.require_columns((config["field"],))
        if set(config["mapping"]) & set(table.columns):
            raise ValueError("JSON 提取结果字段已存在，请使用新字段名")
        columns = (*table.columns, *config["mapping"])
        pointers = {key: pointer_tokens(value) for key, value in config["mapping"].items()}
        valid, invalid = [], []
        for record in table.records:
            context.check_cancelled()
            try:
                value = json.loads(
                    record.values[config["field"]],
                    parse_float=Decimal,
                    object_pairs_hook=unique_object,
                    parse_constant=reject_constant,
                )
                extracted = {
                    key: scalar(resolve_pointer(value, tokens)) for key, tokens in pointers.items()
                }
            except (ValueError, RecursionError, InvalidOperation) as exc:
                invalid.append(
                    record.rebuild(
                        {**record.values, **dict.fromkeys(pointers, "")},
                        node=context.node_id,
                        reason="预留 JSON 结果字段",
                    ).with_issue(node=context.node_id, field=config["field"], message=str(exc))
                )
            else:
                valid.append(
                    record.rebuild(
                        {**record.values, **extracted},
                        node=context.node_id,
                        reason="提取 JSON 字段",
                    )
                )
        return {"valid": Table(columns, tuple(valid)), "invalid": Table(columns, tuple(invalid))}


class NormalizeNumber(Plugin):
    spec = PluginSpec(
        "number.normalize",
        "规范化数值",
        "transform",
        "严格解析十进制、千分位及百分号，按明确规则输出；错误行不做部分修改",
        inputs=("data",),
        outputs=("valid", "invalid"),
        category="计算与分类",
        parameters=(
            P("fields", list, "数值字段，不用于编号或身份证", required=True, widget="fields"),
            P("thousands", str, "千分位符号", default="none", choices=("none", "comma", "space")),
            P("percent", bool, "允许末尾 % 并除以 100", default=False),
            P("places", int, "小数位数，-1 保留精度并去尾零", default=-1),
            P(
                "rounding",
                str,
                "舍入方式",
                default="half_up",
                choices=("half_up", "half_even", "truncate"),
            ),
            P("allow_empty", bool, "空字符串保持为空", default=True),
        ),
    )

    def check_config(self, config):
        names(config["fields"])
        if not -1 <= config["places"] <= 30:
            raise ValueError("小数位数应在 -1 到 30 之间")

    @staticmethod
    def convert(raw, config):
        value = raw.strip()
        if not value and config["allow_empty"]:
            return ""
        is_percent = config["percent"] and value.endswith("%")
        if is_percent:
            value = value[:-1].strip()
        separator = {"none": "", "comma": ",", "space": " "}[config["thousands"]]
        integer = r"[0-9]+"
        if separator:
            integer = rf"(?:[0-9]+|[0-9]{{1,3}}(?:{re.escape(separator)}[0-9]{{3}})+)"
        pattern = rf"[+-]?(?:{integer}(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
        if len(value) > 4096 or not re.fullmatch(pattern, value):
            raise ValueError("数值格式无效；千分位必须每三位一组")
        value = value.replace(separator, "") if separator else value
        number = Decimal(value)
        if (
            not number.is_finite()
            or abs(number.as_tuple().exponent) > 10000
            or abs(number.adjusted()) > 10000
        ):
            raise ValueError("数值指数超出允许范围")
        with localcontext() as decimal_context:
            decimal_context.prec = max(
                50, len(number.as_tuple().digits) + abs(number.as_tuple().exponent) + 40
            )
            if is_percent:
                number /= Decimal(100)
            if config["places"] >= 0:
                rounding = {
                    "half_up": ROUND_HALF_UP,
                    "half_even": ROUND_HALF_EVEN,
                    "truncate": ROUND_DOWN,
                }[config["rounding"]]
                number = number.quantize(Decimal(1).scaleb(-config["places"]), rounding=rounding)
            if number == 0:
                number = abs(number)
            result = format(number, "f")
            return (
                result.rstrip("0").rstrip(".")
                if config["places"] == -1 and "." in result
                else result
            )

    def run(self, inputs, config, context):
        table = inputs["data"]
        table.require_columns(config["fields"])
        valid, invalid = [], []
        for record in table.records:
            context.check_cancelled()
            updates, issues = {}, []
            for field in config["fields"]:
                context.check_cancelled()
                try:
                    updates[field] = self.convert(record.values[field], config)
                except (ValueError, ArithmeticError) as exc:
                    issues.append((field, str(exc)))
            if issues:
                for field, message in issues:
                    record = record.with_issue(node=context.node_id, field=field, message=message)
                invalid.append(record)
            else:
                valid.append(
                    record.with_updates(updates, node=context.node_id, reason="规范化数值")
                )
        return {"valid": table.with_records(valid), "invalid": table.with_records(invalid)}


class TemplateText(Plugin):
    spec = PluginSpec(
        "text.template",
        "文本模板",
        "transform",
        "用 {字段名} 生成提交文本；{{ 和 }} 表示字面花括号",
        inputs=("data",),
        outputs=("data",),
        category="文本处理",
        parameters=(
            P("template", str, "模板，例如 flag{{{摘要}}}", required=True),
            P("output", str, "结果字段", default="文本结果"),
        ),
    )

    @staticmethod
    def parts(template):
        parts = list(Formatter().parse(template))
        for _, field, format_spec, conversion in parts:
            if field is not None and (
                not field.strip()
                or any(char in field for char in ".[]")
                or format_spec
                or conversion
            ):
                raise ValueError("模板仅支持 {字段名}，不支持属性、索引、转换或格式表达式")
        return parts

    def check_config(self, config):
        require_name(config["output"], "结果字段")
        self.parts(config["template"])

    def run(self, inputs, config, context):
        table = inputs["data"]
        parts = self.parts(config["template"])
        table.require_columns(field for _, field, _, _ in parts if field is not None)
        columns = tuple(dict.fromkeys((*table.columns, config["output"])))

        def convert(row):
            value = "".join(
                literal + (row[field] if field is not None else "")
                for literal, field, _, _ in parts
            )
            return {**row, config["output"]: value}

        return {"data": map_values(table, context, convert, columns=columns, reason="文本模板")}


PLUGINS = [
    MapValues,
    CoalesceValues,
    NumberRows,
    ExplodeRows,
    UnpivotColumns,
    ExtractJson,
    NormalizeNumber,
    TemplateText,
]
