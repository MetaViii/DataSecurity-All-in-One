import json

from datasecurity import Parameter, Plugin, PluginSpec

from ._files import atomic_text, check_encoding


class JsonWriter(Plugin):
    spec = PluginSpec(
        id="json.write",
        name="导出 JSON",
        kind="output",
        description="导出 JSON 数组；diagnostics 模式保留结构化的来源、问题与修改明细",
        inputs=("data",),
        category="数据输出",
        parameters=(
            Parameter("path", str, "输出文件", required=True, widget="output_file"),
            Parameter(
                "format", str, "JSON 数组或逐行 JSON", default="json", choices=("json", "jsonl")
            ),
            Parameter("encoding", str, "字符编码", default="utf-8"),
            Parameter("overwrite", bool, "允许替换已有输出文件", default=False),
            Parameter(
                "diagnostics", bool, "每条记录输出 values、origins、issues、changes", default=False
            ),
        ),
    )

    def check_config(self, config):
        if not config["path"]:
            raise ValueError("path 不能为空")
        check_encoding(config["encoding"])

    def run(self, inputs, config, context):
        table = inputs["data"]
        path = context.output_path(config["path"], overwrite=config["overwrite"])
        with atomic_text(path, encoding=config["encoding"]) as handle:
            if config["format"] == "json":
                handle.write("[\n")
            for index, record in enumerate(table.records):
                context.check_cancelled()
                row = (
                    {"values": dict(record.values), **record.diagnostics()}
                    if config["diagnostics"]
                    else dict(record.values)
                )
                if index and config["format"] == "json":
                    handle.write(",\n")
                handle.write(
                    ("  " if config["format"] == "json" else "")
                    + json.dumps(row, ensure_ascii=False)
                )
                if config["format"] == "jsonl":
                    handle.write("\n")
            if config["format"] == "json":
                handle.write("\n]\n")
            context.check_cancelled()
        return {}
