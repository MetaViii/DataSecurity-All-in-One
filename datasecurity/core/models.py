from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from types import MappingProxyType
from typing import Iterable, Mapping


@dataclass(frozen=True)
class Origin:
    source: str
    record: int
    line: int | None = None


@dataclass(frozen=True)
class Issue:
    node: str
    field: str
    message: str


@dataclass(frozen=True)
class Change:
    node: str
    field: str
    before: str
    after: str
    reason: str
    operation: str = "update"


@dataclass(frozen=True)
class Record:
    values: Mapping[str, str]
    origins: tuple[Origin, ...] = ()
    issues: tuple[Issue, ...] = ()
    changes: tuple[Change, ...] = ()

    def __post_init__(self) -> None:
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.values.items()
        ):
            raise TypeError("单元格和字段名必须是字符串；数值计算后请明确格式化")
        # A branch may share records with another branch. Freeze a private copy
        # so a plugin cannot accidentally change its upstream or sibling data.
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        for name in ("origins", "issues", "changes"):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    def with_issue(self, *, node: str, field: str, message: str) -> Record:
        return replace(self, issues=(*self.issues, Issue(node, field, message)))

    def with_updates(self, updates: Mapping[str, str], *, node: str, reason: str) -> Record:
        unknown = set(updates) - set(self.values)
        if unknown:
            raise ValueError(f"修改了不存在的字段：{', '.join(sorted(unknown))}")
        changes = tuple(
            Change(node, field, self.values[field], value, reason)
            for field, value in updates.items()
            if value != self.values[field]
        )
        return replace(self, values={**self.values, **updates}, changes=(*self.changes, *changes))

    def diagnostics(self) -> dict:
        return {
            "origins": [asdict(item) for item in self.origins],
            "issues": [asdict(item) for item in self.issues],
            "changes": [asdict(item) for item in self.changes],
        }

    def rebuild(self, values: Mapping[str, str], *, node: str, reason: str) -> Record:
        """Change the schema as well as values, preserving a per-cell history."""
        changes = []
        for name in dict.fromkeys((*self.values, *values)):
            if name not in self.values:
                operation = "add"
            elif name not in values:
                operation = "drop"
            elif self.values[name] != values[name]:
                operation = "update"
            else:
                continue
            changes.append(
                Change(
                    node, name, self.values.get(name, ""), values.get(name, ""), reason, operation
                )
            )
        return replace(self, values=values, changes=(*self.changes, *changes))


@dataclass(frozen=True)
class Table:
    columns: tuple[str, ...]
    records: tuple[Record, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "records", tuple(self.records))
        if any(not isinstance(column, str) or not column.strip() for column in self.columns):
            raise ValueError("字段名必须是非空字符串")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("字段名不能重复")
        expected = set(self.columns)
        for index, record in enumerate(self.records, 1):
            if set(record.values) != expected:
                raise ValueError(f"第 {index} 条记录的字段与表头不一致")

    def __len__(self) -> int:
        return len(self.records)

    def with_records(self, records: Iterable[Record]) -> Table:
        return Table(self.columns, tuple(records))

    def require_columns(self, columns: Iterable[str]) -> None:
        missing = set(columns) - set(self.columns)
        if missing:
            raise ValueError(f"不存在字段：{', '.join(sorted(missing))}")

    @classmethod
    def from_rows(
        cls, columns: Iterable[str], rows: Iterable[Mapping[str, str]], source: str = "<memory>"
    ) -> Table:
        return cls(
            tuple(columns),
            tuple(Record(row, (Origin(source, index),)) for index, row in enumerate(rows, 1)),
        )
