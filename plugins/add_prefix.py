"""A complete local plugin example; copy this file to start your own plugin."""

from datasecurity import Parameter, Plugin, PluginSpec


class AddPrefix(Plugin):
    spec = PluginSpec(
        id="example.add_prefix",
        name="添加前缀",
        kind="transform",
        description="为指定字段添加文本前缀，并自动记录修改前后的值",
        inputs=("data",),
        outputs=("data",),
        parameters=(
            Parameter("field", str, "要修改的字段", required=True),
            Parameter("prefix", str, "添加到字段前面的文本", default="[示例]"),
        ),
    )

    def run(self, inputs, config, context):
        table = inputs["data"]
        field = config["field"]
        table.require_columns((field,))
        records = (
            record.with_updates(
                {field: config["prefix"] + record.values[field]},
                node=context.node_id,
                reason="添加用户指定的前缀",
            )
            for record in table.records
        )
        return {"data": table.with_records(records)}


PLUGINS = [AddPrefix]
