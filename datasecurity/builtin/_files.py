from __future__ import annotations

import codecs
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO

from datasecurity import Record, Table

DIAGNOSTIC_COLUMNS = ("__origins", "__issues", "__changes")


def check_encoding(encoding: str) -> None:
    try:
        codecs.lookup(encoding)
    except LookupError as exc:
        raise ValueError(f"未知字符编码：{encoding}") from exc


def check_delimiter(delimiter: str) -> None:
    if len(delimiter) != 1 or delimiter in '\r\n\x00"':
        raise ValueError("分隔符必须是一个字符，且不能是换行、双引号或 NUL")


@contextmanager
def atomic_text(path: Path, *, encoding: str, newline: str | None = None) -> Iterator[TextIO]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            newline=newline,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            yield handle
        # Close the handle before replacement: Windows does not allow renaming
        # an open temporary file. The temporary stays on the same filesystem.
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def csv_columns(table: Table, diagnostics: bool) -> tuple[str, ...]:
    if diagnostics and set(table.columns) & set(DIAGNOSTIC_COLUMNS):
        raise ValueError("原始字段与诊断列冲突，请重命名或关闭 diagnostics")
    return (*table.columns, *DIAGNOSTIC_COLUMNS) if diagnostics else table.columns


def csv_row(record: Record, diagnostics: bool) -> dict[str, str]:
    row = dict(record.values)
    if diagnostics:
        for key, value in record.diagnostics().items():
            row[f"__{key}"] = json.dumps(value, ensure_ascii=False)
    return row
