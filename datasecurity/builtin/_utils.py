from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

from datasecurity import Record, RunContext, Table


def names(value: list, *, allow_empty: bool = False) -> list[str]:
    if (not value and not allow_empty) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError("字段列表必须包含非空字符串")
    if len(set(value)) != len(value):
        raise ValueError("字段列表不能重复")
    return value


def number(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"不是有效数值：{value!r}") from exc
    if not result.is_finite():
        raise ValueError("不接受 NaN 或 Infinity")
    return result


def text(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("计算结果不是有限数值")
        result = format(value, "f")
        return result.rstrip("0").rstrip(".") if "." in result else result
    return str(value)


def parse_date(value: str, fmt: str = "") -> datetime:
    try:
        return (
            datetime.strptime(value, fmt)
            if fmt
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
    except ValueError as exc:
        raise ValueError(f"日期无法解析：{value!r}") from exc


def map_values(
    table: Table,
    context: RunContext,
    function,
    *,
    columns: Iterable[str] | None = None,
    reason: str,
) -> Table:
    records = []
    for record in table.records:
        context.check_cancelled()
        try:
            values: Mapping[str, str] = function(record.values)
            records.append(record.rebuild(values, node=context.node_id, reason=reason))
        except (ValueError, TypeError, ArithmeticError) as exc:
            position = record.origins[0].record if record.origins else "?"
            raise ValueError(f"源记录 {position}：{exc}") from exc
    return Table(tuple(columns) if columns is not None else table.columns, tuple(records))


def combined_record(values: Mapping[str, str], records: Iterable[Record]) -> Record:
    sources = list(records)
    return Record(
        values,
        tuple(dict.fromkeys(origin for record in sources for origin in record.origins)),
        tuple(issue for record in sources for issue in record.issues),
        tuple(change for record in sources for change in record.changes),
    )
