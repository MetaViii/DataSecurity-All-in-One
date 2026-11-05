import json
from datetime import date, datetime
from decimal import Decimal

from datasecurity import Origin, Parameter as P, Plugin, PluginSpec, Record, Table

from ._files import check_encoding


def scalar(value):
    if isinstance(value, str):
        return value
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                json.dumps(key, ensure_ascii=False) + ":" + json_fragment(item)
                for key, item in value.items()
            )
            + "}"
        )
    if isinstance(value, list):
        return "[" + ",".join(json_fragment(item) for item in value) + "]"
    return str(value)


def json_fragment(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return scalar(value)


class JsonReader(Plugin):
    spec = PluginSpec(
        "json.read",
        "读取 JSON / JSONL",
        "input",
        "读取对象数组或逐行对象；嵌套值保留为 JSON 文本，缺少字段补空字符串",
        outputs=("data",),
        category="数据输入",
        parameters=(
            P("path", str, "文件路径", required=True, widget="input_file"),
            P("format", str, "文件格式", default="auto", choices=("auto", "json", "jsonl")),
            P("record_path", str, "JSON 数组路径，例如 data.users；JSONL 留空", default=""),
            P("encoding", str, "字符编码", default="utf-8-sig"),
        ),
    )

    def check_config(self, config):
        if not config["path"]:
            raise ValueError("文件路径不能为空")
        if config["format"] == "jsonl" and config["record_path"]:
            raise ValueError("JSONL 不接受 record_path")
        check_encoding(config["encoding"])

    def run(self, inputs, config, context):
        path = context.resolve_path(config["path"])
        context.source_paths.add(path)
        fmt = (
            config["format"]
            if config["format"] != "auto"
            else ("jsonl" if path.suffix.lower() in {".jsonl", ".ndjson"} else "json")
        )
        rows = []
        with path.open(encoding=config["encoding"]) as handle:
            if fmt == "jsonl":
                for line, content in enumerate(handle, 1):
                    context.check_cancelled()
                    if content.strip():
                        rows.append((json.loads(content, parse_float=Decimal), line))
            else:
                data = json.load(handle, parse_float=Decimal)
                for key in filter(None, config["record_path"].split(".")):
                    if not isinstance(data, dict) or key not in data:
                        raise ValueError(f"找不到 JSON 路径：{config['record_path']}")
                    data = data[key]
                if isinstance(data, dict):
                    data = [data]
                if not isinstance(data, list):
                    raise ValueError("JSON 数据应为对象或对象数组")
                rows = [(row, None) for row in data]
        if any(not isinstance(row, dict) for row, _ in rows):
            raise ValueError("每条记录必须是 JSON 对象")
        columns = tuple(dict.fromkeys(key for row, _ in rows for key in row))
        records = tuple(
            Record(
                {col: scalar(row[col]) if col in row else "" for col in columns},
                (Origin(str(path), index, line),),
            )
            for index, (row, line) in enumerate(rows, 1)
        )
        return {"data": Table(columns, records)}


class TextReader(Plugin):
    spec = PluginSpec(
        "text.read",
        "读取文本 / 日志",
        "input",
        "逐行读取原始文本；只移除行末换行符，保留其余空白",
        outputs=("data",),
        category="数据输入",
        parameters=(
            P("path", str, "文件路径", required=True, widget="input_file"),
            P("encoding", str, "字符编码", default="utf-8-sig"),
            P("skip_empty", bool, "跳过空行", default=False),
        ),
    )

    def check_config(self, config):
        if not config["path"]:
            raise ValueError("文件路径不能为空")
        check_encoding(config["encoding"])

    def run(self, inputs, config, context):
        path = context.resolve_path(config["path"])
        context.source_paths.add(path)
        records = []
        with path.open(encoding=config["encoding"], newline="") as handle:
            for index, content in enumerate(handle, 1):
                context.check_cancelled()
                value = content.rstrip("\r\n")
                if value or not config["skip_empty"]:
                    records.append(
                        Record(
                            {"行号": str(index), "内容": value}, (Origin(str(path), index, index),)
                        )
                    )
        return {"data": Table(("行号", "内容"), tuple(records))}


class ExcelReader(Plugin):
    spec = PluginSpec(
        "xlsx.read",
        "读取 Excel",
        "input",
        "读取 XLSX；字符串保留原值，日期转 ISO，数字按存储值转换，公式默认保留文本",
        outputs=("data",),
        category="数据输入",
        parameters=(
            P("path", str, "XLSX 文件", required=True, widget="input_file"),
            P("sheet", str, "工作表名，留空读取第一张", default=""),
            P("formulas", str, "公式处理", default="text", choices=("text", "reject", "cached")),
            P("skip_empty", bool, "跳过全空行", default=True),
        ),
    )

    def run(self, inputs, config, context):
        from openpyxl import load_workbook

        path = context.resolve_path(config["path"])
        context.source_paths.add(path)
        workbook = load_workbook(path, read_only=True, data_only=False)
        cached = (
            load_workbook(path, read_only=True, data_only=True)
            if config["formulas"] == "cached"
            else None
        )
        try:
            sheet = workbook[config["sheet"]] if config["sheet"] else workbook.worksheets[0]
            iterator = sheet.iter_rows()
            header = next(iterator, None)
            if header is None:
                raise ValueError("工作表为空")
            columns = tuple("" if cell.value is None else str(cell.value) for cell in header)
            Table(columns, ())
            records = []
            cached_rows = iter(cached[sheet.title].iter_rows(min_row=2)) if cached else None
            for index, cells in enumerate(iterator, 2):
                context.check_cancelled()
                cached_cells = next(cached_rows) if cached_rows else None
                values, warnings = {}, []
                for position, (column, cell) in enumerate(zip(columns, cells)):
                    value = cell.value
                    if cell.data_type == "f":
                        if config["formulas"] == "reject":
                            raise ValueError(f"{cell.coordinate} 包含公式")
                        if cached_cells is not None:
                            value = cached_cells[position].value
                            if value is None:
                                raise ValueError(
                                    f"{cell.coordinate} 缺少公式缓存，请用 Excel 重算或选择 text"
                                )
                    if value is None:
                        value = ""
                    elif isinstance(value, (date, datetime)):
                        value = value.isoformat()
                    elif isinstance(value, bool):
                        value = "true" if value else "false"
                    elif isinstance(value, int):
                        if len(str(abs(value))) > 15:
                            warnings.append(
                                (column, "数值单元格超过 15 位，源 Excel 可能已经丢失精度")
                            )
                        if cell.number_format and set(cell.number_format) == {"0"}:
                            value = str(value).zfill(len(cell.number_format))
                    values[column] = str(value)
                if config["skip_empty"] and all(value == "" for value in values.values()):
                    continue
                record = Record(values, (Origin(f"{path}#{sheet.title}", index - 1, index),))
                for column, message in warnings:
                    record = record.with_issue(node=context.node_id, field=column, message=message)
                records.append(record)
            return {"data": Table(columns, tuple(records))}
        finally:
            workbook.close()
            if cached:
                cached.close()


PLUGINS = [JsonReader, TextReader, ExcelReader]
