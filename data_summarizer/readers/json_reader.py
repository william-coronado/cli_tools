from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path
from typing import Any

from ..stats import ColumnAccumulator
from ..summarizer import (
    ColumnInfo,
    ColumnStats,
    DataSummary,
    StructureSummary,
    SummarizerOptions,
    TableSummary,
)
from .base import Reader


class JSONReader(Reader):
    FORMAT_NAME = "json"

    def read(self, path: Path, opts: SummarizerOptions) -> DataSummary:
        t0 = time.monotonic()
        size = path.stat().st_size
        warnings: list[str] = []

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

        if isinstance(data, list) and all(isinstance(r, dict) for r in data):
            # Array of records → tabular path
            table = self._summarize_array_of_records(data, path, opts)
            return DataSummary(
                source=str(path),
                file_size_bytes=size,
                file_format="json",
                parse_duration_ms=int((time.monotonic() - t0) * 1000),
                backend_used="stdlib-json",
                tables=[table],
                warnings=warnings,
            )
        elif isinstance(data, list):
            warnings.append("Array contained non-record entries; rendering structural summary")
            structure = self._summarize_structure(data, path.name)
            return DataSummary(
                source=str(path),
                file_size_bytes=size,
                file_format="json",
                parse_duration_ms=int((time.monotonic() - t0) * 1000),
                backend_used="stdlib-json",
                structures=[structure],
                warnings=warnings,
            )
        else:
            # Nested object → structural summary
            structure = self._summarize_structure(data, path.name)
            return DataSummary(
                source=str(path),
                file_size_bytes=size,
                file_format="json",
                parse_duration_ms=int((time.monotonic() - t0) * 1000),
                backend_used="stdlib-json",
                structures=[structure],
                warnings=warnings,
            )

    def _summarize_array_of_records(
        self, records: list[dict], path: Path, opts: SummarizerOptions
    ) -> TableSummary:
        accumulators: dict[str, ColumnAccumulator] = {}
        column_order: list[str] = []
        head_rows: list[dict[str, Any]] = []
        tail_maxlen = opts.sample_tail if (not opts.no_sample and opts.sample_tail > 0) else 0
        tail_buf: deque[dict[str, Any]] = deque(maxlen=tail_maxlen) if tail_maxlen else deque()

        row_count = 0
        truncated = False

        for record in records:
            row_count += 1
            if row_count > opts.max_rows:
                truncated = True
                break

            for key in record:
                if opts.columns and key not in opts.columns:
                    continue
                if key not in accumulators:
                    if len(column_order) >= opts.max_columns:
                        continue
                    column_order.append(key)
                    acc = ColumnAccumulator(
                        name=key,
                        max_distinct=opts.max_distinct,
                        keep_samples_for_median=opts.median,
                    )
                    for _ in range(row_count - 1):
                        acc.update(None)
                    accumulators[key] = acc

            row_dict: dict[str, Any] = {}
            for col in column_order:
                val = record.get(col)
                row_dict[col] = val
                accumulators[col].update(val)

            if not opts.no_sample:
                if len(head_rows) < opts.sample_head:
                    head_rows.append(row_dict)
                if tail_maxlen:
                    tail_buf.append(row_dict)

        columns: list[ColumnInfo] = []
        stats: list[ColumnStats] = []
        for name in column_order:
            acc = accumulators[name]
            columns.append(
                ColumnInfo(
                    name=name,
                    dtype=acc.dtype(),
                    nullable=acc.null_count > 0,
                    null_count=acc.null_count,
                    null_pct=acc.null_pct(),
                    distinct_count=acc.distinct_count,
                )
            )
            if not opts.no_stats:
                top_vals = (
                    acc.top_values(opts.top_k)
                    if acc.dtype() not in ("int", "float", "datetime", "null")
                    else []
                )
                stats.append(
                    ColumnStats(
                        name=name,
                        count=acc.count,
                        null_count=acc.null_count,
                        distinct_count=acc.distinct_count,
                        min=acc.min_val,
                        max=acc.max_val,
                        mean=acc.mean,
                        median=acc.median if opts.median else None,
                        std=acc.std,
                        min_date=acc.min_dt,
                        max_date=acc.max_dt,
                        top_values=top_vals,
                    )
                )

        tail_rows = list(tail_buf)
        if head_rows and tail_rows and row_count <= opts.sample_head + len(tail_rows):
            tail_rows = []

        notes: list[str] = []
        if truncated:
            notes.append(f"Stats sampled from first {opts.max_rows:,} rows")

        return TableSummary(
            name=path.name,
            row_count=None if truncated else row_count,
            column_count=len(column_order),
            columns=columns,
            stats=stats,
            head=head_rows,
            tail=tail_rows,
            truncated=truncated,
            notes=notes,
        )

    def _summarize_structure(self, data: Any, name: str) -> StructureSummary:
        depth = _max_depth(data)
        notes = [
            "Nested JSON — not tabular. Showing top-level structure only."
        ]
        top_keys: list[dict[str, Any]] = []

        if isinstance(data, dict):
            for k, v in data.items():
                top_keys.append({
                    "key": str(k),
                    "type": _type_label(v),
                    "size": _size_of(v),
                })
        elif isinstance(data, list):
            top_keys.append({
                "key": "<root>",
                "type": "array",
                "size": len(data),
            })

        return StructureSummary(
            name=name,
            top_level_keys=top_keys,
            depth=depth,
            notes=notes,
        )


def _type_label(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _size_of(v: Any) -> int | None:
    if isinstance(v, (list, dict, str)):
        return len(v)
    return None


def _max_depth(v: Any, current: int = 1) -> int:
    if isinstance(v, dict):
        return max((_max_depth(child, current + 1) for child in v.values()), default=current)
    if isinstance(v, list):
        return max((_max_depth(child, current + 1) for child in v), default=current)
    return current
