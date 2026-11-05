from __future__ import annotations

import csv

from datasecurity import Origin, Parameter, Plugin, PluginSpec, Record, Table

from ._files import atomic_text, check_delimiter, check_encoding, csv_columns, csv_row


class CsvReader(Plugin):
    spec = PluginSpec(
        id="csv.read",
        name="读取 CSV",
        kind="input",
        description="保留字符串、表头顺序与源记录位置；不推断数字或日期",
        outputs=("data",),
        category="数据输入",
        parameters=(
            Parameter(
                "path",
                str,
                "输入文件；相对路径以流程文件所在目录为基准",
                required=True,
                widget="input_file",
            ),
            Parameter("encoding", str, "字符编码；默认兼容 UTF-8 BOM", default="utf-8-sig"),
            Parameter("delimiter", str, "单字符分隔符", default=","),
            Parameter(
                "skip_blank_lines",
                bool,
                "忽略空行；不忽略只有空格的行或 ,,, 这类空字段记录",
                default=True,
            ),
        ),
    )

    def check_config(self, config):
        if not config["path"]:
            raise ValueError("path 不能为空")
        check_encoding(config["encoding"])
        check_delimiter(config["delimiter"])

    def run(self, inputs, config, context):
        path = context.resolve_path(config["path"])
        context.source_paths.add(path)
        records = []
        with path.open("r", encoding=config["encoding"], newline="") as handle:
            reader = csv.reader(handle, delimiter=config["delimiter"], strict=True)
            columns = next(reader, None)
            if columns is None:
                raise ValueError("CSV 为空，缺少表头")
            # Check the schema before reading rows. Duplicate headers would
            # otherwise silently overwrite a value when converted to a dict.
            Table(tuple(columns), ())
            if not columns:
                raise ValueError("CSV 的第一条记录必须是表头")
            previous_line = reader.line_num
            try:
                for values in reader:
                    context.check_cancelled()
                    start_line = previous_line + 1
                    previous_line = reader.line_num
                    if not values and config["skip_blank_lines"]:
                        continue
                    if len(values) != len(columns):
                        raise ValueError(
                            f"第 {start_line} 行有 {len(values)} 个字段，表头有 {len(columns)} 个"
                        )
                    origin = Origin(str(path), len(records) + 1, start_line)
                    records.append(Record(dict(zip(columns, values)), (origin,)))
            except csv.Error as exc:
                raise ValueError(f"第 {reader.line_num} 行 CSV 格式无效：{exc}") from exc
        return {"data": Table(tuple(columns), tuple(records))}


class CsvWriter(Plugin):
    spec = PluginSpec(
        id="csv.write",
        name="导出 CSV",
        kind="output",
        description="按原列序导出全部记录；可附带来源、问题和修改明细",
        inputs=("data",),
        category="数据输出",
        parameters=(
            Parameter("path", str, "输出文件", required=True, widget="output_file"),
            Parameter("encoding", str, "实际写入的字符编码", default="utf-8"),
            Parameter("delimiter", str, "单字符分隔符", default=","),
            Parameter("line_ending", str, "换行符", default="lf", choices=("lf", "crlf")),
            Parameter("overwrite", bool, "允许替换已有输出文件；输入文件始终受保护", default=False),
            Parameter("diagnostics", bool, "追加来源、问题和修改明细三列", default=False),
        ),
    )

    def check_config(self, config):
        if not config["path"]:
            raise ValueError("path 不能为空")
        check_encoding(config["encoding"])
        check_delimiter(config["delimiter"])

    def run(self, inputs, config, context):
        table = inputs["data"]
        columns = csv_columns(table, config["diagnostics"])
        path = context.output_path(config["path"], overwrite=config["overwrite"])
        with atomic_text(path, encoding=config["encoding"], newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=columns,
                delimiter=config["delimiter"],
                lineterminator="\n" if config["line_ending"] == "lf" else "\r\n",
            )
            writer.writeheader()
            for record in table.records:
                context.check_cancelled()
                writer.writerow(csv_row(record, config["diagnostics"]))
            context.check_cancelled()
        return {}
