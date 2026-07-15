from __future__ import annotations

import re
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

        if opts.query and (opts.tables or opts.all_tables or opts.columns):
            raise ValueError(
                "--query cannot be combined with --table/--all-tables/--columns "
                "(the query already selects its own tables and columns); "
                "use one or the other"
            )

        uri = f"file:{path}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as e:
            raise ValueError(f"Failed to open SQLite database: {e}")

        try:
            if opts.query:
                _validate_select_only(opts.query)
                tables = [self._summarize_query(conn, opts.query, opts)]
            else:
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

                tables = [
                    self._summarize_table(conn, table_name, opts)
                    for table_name in selected
                ]
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

    def _accumulate_from_cursor(
        self,
        cur: sqlite3.Cursor,
        col_names: list[str],
        opts: SummarizerOptions,
    ) -> tuple[dict[str, ColumnAccumulator], list[dict[str, Any]], list[dict[str, Any]], int, bool]:
        """Consume rows from an already-executing cursor, building per-column
        accumulators plus head/tail samples. Shared by table and query
        summarization so their sampling/stats behavior can't drift apart.

        Returns (accumulators, head_rows, tail_rows, rows_scanned, truncated).
        """
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
        truncated = False
        for row in cur:
            if rows_scanned >= opts.max_rows:
                truncated = True
                break
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

        tail_rows = list(tail_buf)
        if head_rows and tail_rows and rows_scanned <= opts.sample_head + len(tail_rows):
            tail_rows = []

        return accumulators, head_rows, tail_rows, rows_scanned, truncated

    def _build_columns_and_stats(
        self,
        col_names: list[str],
        accumulators: dict[str, ColumnAccumulator],
        opts: SummarizerOptions,
        declared_types: dict[str, str | None] | None = None,
    ) -> tuple[list[ColumnInfo], list[ColumnStats]]:
        """Build ColumnInfo/ColumnStats from accumulators. ``declared_types``
        (SQL column types from PRAGMA table_info) lets table summaries widen
        an ambiguous inferred dtype; query results have no declared types."""
        columns: list[ColumnInfo] = []
        stats: list[ColumnStats] = []
        for name in col_names:
            acc = accumulators[name]
            inferred = acc.dtype()
            if declared_types is not None and inferred in ("mixed", "null", "string"):
                dtype = _normalize_sql_type(declared_types.get(name))
            else:
                dtype = inferred
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
        return columns, stats

    def _summarize_query(
        self,
        conn: sqlite3.Connection,
        query: str,
        opts: SummarizerOptions,
    ) -> TableSummary:
        cur = conn.cursor()
        try:
            cur.execute(query)
        except sqlite3.Error as e:
            raise ValueError(f"Query failed: {e}") from e
        col_names = [d[0] for d in cur.description] if cur.description else []

        if not col_names:
            return TableSummary(
                name="query result",
                row_count=0,
                column_count=0,
                columns=[],
                stats=[],
                head=[],
                tail=[],
                notes=["Query returned no columns"],
            )

        col_names = col_names[: opts.max_columns]

        accumulators, head_rows, tail_rows, rows_scanned, truncated = (
            self._accumulate_from_cursor(cur, col_names, opts)
        )
        columns, stats = self._build_columns_and_stats(col_names, accumulators, opts)

        notes: list[str] = []
        if truncated:
            notes.append(f"Row scan capped at {opts.max_rows:,} rows (use --max-rows to change)")

        return TableSummary(
            name="query result",
            row_count=rows_scanned,
            column_count=len(col_names),
            columns=columns,
            stats=stats,
            head=head_rows,
            tail=tail_rows,
            truncated=truncated,
            notes=notes,
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
        declared_types = {n: t for n, t in selected_cols}

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

        accumulators, head_rows, tail_rows, rows_scanned, _ = (
            self._accumulate_from_cursor(cur, col_names, opts)
        )
        columns, stats = self._build_columns_and_stats(
            col_names, accumulators, opts, declared_types
        )

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


_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _strip_leading_comments(s: str) -> str:
    """Strip leading whitespace and SQL comments (-- line, /* block */)."""
    s = s.lstrip()
    while True:
        if s.startswith("--"):
            nl = s.find("\n")
            s = s[nl + 1 :] if nl != -1 else ""
            s = s.lstrip()
            continue
        if s.startswith("/*"):
            end = s.find("*/")
            s = s[end + 2 :] if end != -1 else ""
            s = s.lstrip()
            continue
        break
    return s


def _skip_balanced_parens(s: str, i: int) -> int:
    """Given s[i] == '(', return the index just past the matching ')',
    respecting quoted string/identifier literals. Returns len(s) if
    unbalanced (caller treats that as malformed)."""
    depth = 0
    in_single = in_double = False
    n = len(s)
    while i < n:
        c = s[i]
        if in_single:
            if c == "'":
                if i + 1 < n and s[i + 1] == "'":
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if in_double:
            if c == '"':
                if i + 1 < n and s[i + 1] == '"':
                    i += 2
                    continue
                in_double = False
            i += 1
            continue
        if c == "'":
            in_single = True
        elif c == '"':
            in_double = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _cte_prefix_end(s: str) -> int | None:
    """Given ``s`` starting with ``WITH [RECURSIVE]``, scan past the
    comma-separated CTE definitions (``name [(cols)] AS (subquery)``) and
    return the index where the final statement begins. Returns None if the
    input doesn't parse as a well-formed CTE prefix."""
    m = re.match(r"(?i)^with\s+(recursive\s+)?", s)
    if not m:
        return None
    i = m.end()
    n = len(s)
    while True:
        m = _IDENT_RE.match(s, i)
        if not m:
            return None
        i = m.end()
        while i < n and s[i].isspace():
            i += 1
        if i < n and s[i] == "(":
            i = _skip_balanced_parens(s, i)
            while i < n and s[i].isspace():
                i += 1
        m2 = re.match(r"(?i)as\b", s[i:])
        if not m2:
            return None
        i += m2.end()
        while i < n and s[i].isspace():
            i += 1
        if i >= n or s[i] != "(":
            return None
        i = _skip_balanced_parens(s, i)
        while i < n and s[i].isspace():
            i += 1
        if i < n and s[i] == ",":
            i += 1
            while i < n and s[i].isspace():
                i += 1
            continue
        return i


def _validate_select_only(query: str) -> None:
    stripped = query.strip()
    if not stripped:
        raise ValueError("--query must not be empty")
    # Reject multiple statements (a trailing semicolon on the last statement is fine).
    body = stripped[:-1] if stripped.endswith(";") else stripped
    if ";" in body:
        raise ValueError("--query must be a single SELECT statement")

    no_comments = _strip_leading_comments(body)
    error = ValueError(
        "--query only supports SELECT statements (including `WITH ... SELECT` "
        "CTEs); this suite is a read-only pre-processor, not a database admin "
        "tool"
    )

    if re.match(r"(?i)^with\b", no_comments):
        rest_start = _cte_prefix_end(no_comments)
        if rest_start is None:
            raise error
        rest = _strip_leading_comments(no_comments[rest_start:])
        if not re.match(r"(?i)^select\b", rest):
            raise error
        return

    if not re.match(r"(?i)^select\b", no_comments):
        raise error


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
