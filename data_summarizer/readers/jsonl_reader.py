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
    SummarizerOptions,
    TableSummary,
)
from .base import Reader


class JSONLReader(Reader):
    FORMAT_NAME = "jsonl"

    def read(self, path: Path, opts: SummarizerOptions) -> DataSummary:
        t0 = time.monotonic()
        size = path.stat().st_size
        warnings: list[str] = []

        head_rows: list[dict[str, Any]] = []
        tail_maxlen = opts.sample_tail if (not opts.no_sample and opts.sample_tail > 0) else 0
        tail_buf: deque[dict[str, Any]] = deque(maxlen=tail_maxlen) if tail_maxlen else deque()

        accumulators: dict[str, ColumnAccumulator] = {}
        column_order: list[str] = []
        row_count = 0
        truncated = False
        parse_errors = 0

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue
                if not isinstance(record, dict):
                    parse_errors += 1
                    continue

                row_count += 1
                if row_count > opts.max_rows:
                    truncated = True
                    break

                # Apply --columns filter, capture column order on first sight
                for key, val in record.items():
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
                        # Backfill: count earlier rows as nulls for this column
                        for _ in range(row_count - 1):
                            acc.update(None)
                        accumulators[key] = acc

                # Apply NaN treatment + accumulator update for every tracked column
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

        if parse_errors:
            warnings.append(f"{parse_errors} line(s) failed to parse as JSON; skipped")

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

        table = TableSummary(
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

        return DataSummary(
            source=str(path),
            file_size_bytes=size,
            file_format="jsonl",
            parse_duration_ms=int((time.monotonic() - t0) * 1000),
            backend_used="stdlib-json",
            tables=[table],
            warnings=warnings,
        )
