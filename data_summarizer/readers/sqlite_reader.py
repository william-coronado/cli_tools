from __future__ import annotations

import sqlite3
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


class SQLiteReader(Reader):
    FORMAT_NAME = "sqlite"

    def read(self, path: Path, opts: SummarizerOptions) -> DataSummary:
        t0 = time.monotonic()
        size = path.stat().st_size
        warnings: list[str] = []

        uri = f"file:{path}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as e:
            raise ValueError(f"Failed to open SQLite database: {e}")

        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            all_tables = [row[0] for row in cur.fetchall()]

            if opts.tables:
                selected = [t for t in all_tables if t in opts.tables]
                missing = [t for t in opts.tables if t not in all_tables]
                if missing:
                    warnings.append(f"Tables not found: {', '.join(missing)}")
            else:
                selected = all_tables

            if not opts.all_tables and len(selected) > opts.max_tables:
                warnings.append(
                    f"Showing first {opts.max_tables} of {len(selected)} tables "
                    f"(use --all-tables or --max-tables to change)"
                )
                selected = selected[: opts.max_tables]

            tables: list[TableSummary] = []
            for table_name in selected:
                tables.append(self._summarize_table(conn, table_name, opts))
        finally:
            conn.close()

        return DataSummary(
            source=str(path),
            file_size_bytes=size,
            file_format="sqlite",
            parse_duration_ms=int((time.monotonic() - t0) * 1000),
            backend_used="stdlib-sqlite3",
            tables=tables,
            warnings=warnings,
        )

    def _summarize_table(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        opts: SummarizerOptions,
    ) -> TableSummary:
        cur = conn.cursor()

        # PRAGMA table_info → ordered columns with declared types
        cur.execute(f"PRAGMA table_info({_quote_ident(table_name)})")
        schema_rows = cur.fetchall()
        # Each row: (cid, name, type, notnull, dflt_value, pk)
        all_columns = [(r[1], r[2]) for r in schema_rows]

        if opts.columns:
            wanted = set(opts.columns)
            selected_cols = [(n, t) for n, t in all_columns if n in wanted]
        else:
            selected_cols = all_columns
        selected_cols = selected_cols[: opts.max_columns]
        col_names = [n for n, _ in selected_cols]

        if not col_names:
            return TableSummary(
                name=table_name,
                row_count=0,
                column_count=0,
                columns=[],
                stats=[],
                head=[],
                tail=[],
                notes=["No selectable columns"],
            )

        # Row count
        cur.execute(f"SELECT COUNT(*) FROM {_quote_ident(table_name)}")
        total_rows = int(cur.fetchone()[0])

        # Apply --max-rows
        truncated = total_rows > opts.max_rows
        scan_limit = min(total_rows, opts.max_rows)

        col_list_sql = ", ".join(_quote_ident(n) for n in col_names)
        cur.execute(
            f"SELECT {col_list_sql} FROM {_quote_ident(table_name)} LIMIT ?",
            (scan_limit,),
        )

        accumulators: dict[str, ColumnAccumulator] = {
            n: ColumnAccumulator(
                name=n,
                max_distinct=opts.max_distinct,
                keep_samples_for_median=opts.median,
            )
            for n in col_names
        }

        head_rows: list[dict[str, Any]] = []
        tail_maxlen = opts.sample_tail if (not opts.no_sample and opts.sample_tail > 0) else 0
        tail_buf: deque[dict[str, Any]] = deque(maxlen=tail_maxlen) if tail_maxlen else deque()

        rows_scanned = 0
        for row in cur:
            rows_scanned += 1
            row_dict: dict[str, Any] = {}
            for i, name in enumerate(col_names):
                val = row[i]
                row_dict[name] = val
                accumulators[name].update(val)

            if not opts.no_sample:
                if len(head_rows) < opts.sample_head:
                    head_rows.append(row_dict)
                if tail_maxlen:
                    tail_buf.append(row_dict)

        columns: list[ColumnInfo] = []
        stats: list[ColumnStats] = []
        for name, declared_type in selected_cols:
            acc = accumulators[name]
            # Prefer declared SQL type if accumulator inferred mixed/null
            inferred = acc.dtype()
            dtype = _normalize_sql_type(declared_type) if inferred in ("mixed", "null", "string") else inferred
            columns.append(
                ColumnInfo(
                    name=name,
                    dtype=dtype,
                    nullable=acc.null_count > 0,
                    null_count=acc.null_count,
                    null_pct=acc.null_pct(),
                    distinct_count=acc.distinct_count,
                )
            )
            if not opts.no_stats:
                top_vals = (
                    acc.top_values(opts.top_k)
                    if dtype not in ("int", "float", "datetime", "null")
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
        if head_rows and tail_rows and rows_scanned <= opts.sample_head + len(tail_rows):
            tail_rows = []

        notes: list[str] = []
        if truncated:
            notes.append(
                f"Stats sampled from first {opts.max_rows:,} of {total_rows:,} rows"
            )

        return TableSummary(
            name=table_name,
            row_count=total_rows,
            column_count=len(col_names),
            columns=columns,
            stats=stats,
            head=head_rows,
            tail=tail_rows,
            truncated=truncated,
            notes=notes,
        )


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _normalize_sql_type(declared: str | None) -> str:
    if not declared:
        return "string"
    d = declared.strip().upper()
    if "INT" in d:
        return "int"
    if "REAL" in d or "FLOA" in d or "DOUB" in d or "NUMERIC" in d or "DECIMAL" in d:
        return "float"
    if "DATE" in d or "TIME" in d:
        return "datetime"
    if "BOOL" in d:
        return "bool"
    return "string"
