from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ColumnInfo:
    name: str
    dtype: str               # "int" | "float" | "string" | "bool" | "datetime" | "null" | "mixed"
    nullable: bool
    null_count: int
    null_pct: float          # 0.0 .. 100.0
    distinct_count: int | None  # None when distinct count exceeded --max-distinct


@dataclass
class ColumnStats:
    name: str
    count: int
    null_count: int
    distinct_count: int | None
    # Numeric (None if not applicable):
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    # Datetime (None if not applicable):
    min_date: str | None = None
    max_date: str | None = None
    # String / categorical:
    top_values: list[tuple[Any, int]] = field(default_factory=list)


@dataclass
class TableSummary:
    name: str
    row_count: int | None
    column_count: int
    columns: list[ColumnInfo]
    stats: list[ColumnStats] = field(default_factory=list)
    head: list[dict[str, Any]] = field(default_factory=list)
    tail: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class StructureSummary:
    """For non-tabular JSON: a top-level structural view."""
    name: str
    top_level_keys: list[dict[str, Any]]   # [{"key": str, "type": str, "size": int | None}]
    depth: int
    notes: list[str] = field(default_factory=list)


@dataclass
class DataSummary:
    source: str
    file_size_bytes: int
    file_format: str
    parse_duration_ms: int
    backend_used: str
    tables: list[TableSummary] = field(default_factory=list)
    structures: list[StructureSummary] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    max_cell_width: int = 80

    def to_markdown(self) -> str:
        from .renderer import Renderer
        return Renderer().render_markdown(self)

    def to_json(self) -> dict:
        from .renderer import Renderer
        return Renderer().render_json(self)

    def to_text(self) -> str:
        from .renderer import Renderer
        return Renderer().render_text(self)


@dataclass
class SummarizerOptions:
    sample_head: int = 5
    sample_tail: int = 5
    no_sample: bool = False
    no_stats: bool = False
    median: bool = False
    max_distinct: int = 100
    top_k: int = 5
    max_rows: int = 100_000
    max_columns: int = 50
    max_cell_width: int = 80
    max_tables: int = 20
    max_json_bytes: int = 50_000_000
    all_tables: bool = False
    columns: list[str] | None = None
    tables: list[str] | None = None
    format_hint: str | None = None
    query: str | None = None


class DataSummarizer:
    def __init__(self, options: SummarizerOptions | None = None) -> None:
        self.options = options or SummarizerOptions()

    def summarize(self, path: str | Path) -> DataSummary:
        from .readers.base import dispatch_reader
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        reader = dispatch_reader(path, self.options.format_hint)
        result = reader.read(path, self.options)
        result.max_cell_width = self.options.max_cell_width
        return result
