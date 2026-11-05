import re

from datasecurity import Parameter, Plugin, PluginSpec


class RegexCheck(Plugin):
    spec = PluginSpec(
        id="validate.regex",
        name="字段格式校验",
        kind="transform",
        description="按完整匹配或搜索匹配分流；错误原因附着在原记录上",
        inputs=("data",),
        outputs=("valid", "invalid"),
        category="数据校验",
        parameters=(
            Parameter("field", str, "待校验字段", required=True, widget="field"),
            Parameter("pattern", str, "Python 正则表达式", required=True),
            Parameter("full_match", bool, "是否要求整个字段匹配", default=True),
            Parameter("message", str, "校验失败时记录的原因", default="字段格式不符合规则"),
        ),
    )

    def check_config(self, config):
        if not config["field"]:
            raise ValueError("field 不能为空")
        try:
            re.compile(config["pattern"])
        except re.error as exc:
            raise ValueError(f"正则表达式无效：{exc}") from exc

    def run(self, inputs, config, context):
        table = inputs["data"]
        field = config["field"]
        table.require_columns((field,))
        pattern = re.compile(config["pattern"])
        match = pattern.fullmatch if config["full_match"] else pattern.search
        valid, invalid = [], []
        for record in table.records:
            context.check_cancelled()
            if match(record.values[field]) is not None:
                valid.append(record)
            else:
                invalid.append(
                    record.with_issue(node=context.node_id, field=field, message=config["message"])
                )
        return {"valid": table.with_records(valid), "invalid": table.with_records(invalid)}
