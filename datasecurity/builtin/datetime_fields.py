from datetime import timedelta

from datasecurity import Parameter as P, Plugin, PluginSpec

from ._utils import map_values, parse_date, text


class DateTimeFields(Plugin):
    spec = PluginSpec(
        "datetime.transform",
        "日期时间处理",
        "transform",
        "明确解析日期后格式化、增加秒数，或计算两字段秒差",
        inputs=("data",),
        outputs=("data",),
        category="计算与分类",
        parameters=(
            P("field", str, "来源字段", required=True, widget="field"),
            P(
                "operation",
                str,
                "操作",
                default="format",
                choices=("format", "add_seconds", "difference_seconds"),
            ),
            P("input_format", str, "输入格式，留空按 ISO 解析", default=""),
            P("output_format", str, "输出格式", default="%Y-%m-%d %H:%M:%S"),
            P("seconds", int, "增加秒数，可为负数", default=0),
            P("other", str, "秒差的第二字段；结果为来源减第二字段", default="", widget="field"),
            P("output", str, "结果字段", default="时间结果"),
        ),
    )

    def check_config(self, config):
        if not config["field"] or not config["output"].strip():
            raise ValueError("来源和结果字段不能为空")
        if config["operation"] == "difference_seconds" and not config["other"]:
            raise ValueError("秒差需要第二字段")

    def run(self, inputs, config, context):
        from decimal import Decimal

        table = inputs["data"]
        table.require_columns(
            [
                config["field"],
                *([config["other"]] if config["operation"] == "difference_seconds" else []),
            ]
        )

        def convert(row):
            value = parse_date(row[config["field"]], config["input_format"])
            if config["operation"] == "difference_seconds":
                other = parse_date(row[config["other"]], config["input_format"])
                difference = value - other
                result = text(
                    Decimal(difference.days * 86400 + difference.seconds)
                    + Decimal(difference.microseconds) / Decimal(1000000)
                )
            else:
                if config["operation"] == "add_seconds":
                    value += timedelta(seconds=config["seconds"])
                result = value.strftime(config["output_format"])
            return {**row, config["output"]: result}

        columns = tuple(dict.fromkeys((*table.columns, config["output"])))
        return {"data": map_values(table, context, convert, columns=columns, reason="日期时间处理")}


PLUGINS = [DateTimeFields]
