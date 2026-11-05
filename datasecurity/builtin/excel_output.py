import os
import tempfile
from itertools import chain
from pathlib import Path

from datasecurity import Parameter as P, Plugin, PluginSpec

from ._files import csv_columns, csv_row


class ExcelWriter(Plugin):
    spec = PluginSpec(
        "xlsx.write",
        "导出 Excel",
        "output",
        "所有单元格以文本写入，保留长号码和前导零，不执行公式",
        inputs=("data",),
        category="数据输出",
        parameters=(
            P("path", str, "输出文件名", required=True, widget="output_file"),
            P("sheet", str, "工作表名", default="结果"),
            P("overwrite", bool, "替换已有输出文件", default=False),
            P("diagnostics", bool, "附带来源、问题和修改记录", default=False),
        ),
    )

    def check_config(self, config):
        if (
            not config["path"]
            or not config["sheet"]
            or len(config["sheet"]) > 31
            or any(char in config["sheet"] for char in "[]:*?/\\")
        ):
            raise ValueError("输出路径或工作表名称无效")

    def run(self, inputs, config, context):
        from openpyxl import Workbook
        from openpyxl.cell import WriteOnlyCell

        table = inputs["data"]
        columns = csv_columns(table, config["diagnostics"])
        if len(columns) > 16384 or len(table) > 1048575:
            raise ValueError("数据超过 XLSX 单表行列上限，请使用 CSV 或 JSONL")
        # openpyxl silently truncates long strings. Validate before creating a
        # write-only workbook so failure cannot damage an existing export.
        for values in chain(
            (columns,),
            (csv_row(record, config["diagnostics"]).values() for record in table.records),
        ):
            context.check_cancelled()
            if any(len(value) > 32767 for value in values):
                raise ValueError("单元格超过 XLSX 的 32767 字符上限，请使用 CSV 或 JSONL")
        path = context.output_path(config["path"], overwrite=config["overwrite"])
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.stem}.", suffix=".xlsx", dir=path.parent
        )
        os.close(descriptor)
        temporary = Path(name)
        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet(config["sheet"])

        def cells(values):
            result = []
            for value in values:
                cell = WriteOnlyCell(sheet, value=value)
                cell.data_type = "s"
                result.append(cell)
            return result

        try:
            sheet.append(cells(columns))
            for record in table.records:
                context.check_cancelled()
                row = csv_row(record, config["diagnostics"])
                sheet.append(cells(row[col] for col in columns))
            workbook.save(temporary)
            context.check_cancelled()
            os.replace(temporary, path)
        finally:
            workbook.close()
            temporary.unlink(missing_ok=True)
        return {}
