from __future__ import annotations

import csv
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


def _has_pandas() -> bool:
    try:
        import pandas  # noqa: F401
        return True
    except ImportError:
        return False


class CSVReader(Reader):
    FORMAT_NAME = "csv"

    def __init__(self, delimiter: str = ",") -> None:
        self.delimiter = delimiter
        self.format_name = "tsv" if delimiter == "\t" else "csv"

    def read(self, path: Path, opts: SummarizerOptions) -> DataSummary:
        t0 = time.monotonic()
        size = path.stat().st_size
        warnings: list[str] = []

        table: TableSummary
        if _has_pandas():
            try:
                table = self._read_with_pandas(path, opts)
                backend = "pandas"
            except Exception as e:
                warnings.append(f"pandas reader failed ({e!s}); fell back to stdlib")
                table = self._read_with_stdlib(path, opts)
                backend = "stdlib-csv"
        else:
            backend = "stdlib-csv"
            warnings.append("pandas not installed; using stdlib reader (stats are limited)")
            table = self._read_with_stdlib(path, opts)

        return DataSummary(
            source=str(path),
            file_size_bytes=size,
            file_format=self.format_name,
            parse_duration_ms=int((time.monotonic() - t0) * 1000),
            backend_used=backend,
            tables=[table],
            warnings=warnings,
        )

    # ── stdlib path ────────────────────────────────────────────────────────────

    def _read_with_stdlib(self, path: Path, opts: SummarizerOptions) -> TableSummary:
        head_rows: list[dict[str, Any]] = []
        tail_maxlen = opts.sample_tail if (not opts.no_sample and opts.sample_tail > 0) else 0
        tail_buf: deque[dict[str, Any]] = deque(maxlen=tail_maxlen) if tail_maxlen else deque()

        truncated = False
        row_count = 0
        column_names: list[str] = []
        col_indices: list[tuple[int, str]] = []
        accumulators: dict[str, ColumnAccumulator] = {}

        with open(path, "r", newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f, delimiter=self.delimiter)
            try:
                header = next(reader)
            except StopIteration:
                raise ValueError(f"Empty file: {path}")

            header = [h.strip() for h in header]
            if opts.columns:
                col_indices = [(i, name) for i, name in enumerate(header) if name in opts.columns]
            else:
                col_indices = list(enumerate(header))
            col_indices = col_indices[: opts.max_columns]
            column_names = [name for _, name in col_indices]

            for name in column_names:
                accumulators[name] = ColumnAccumulator(
                    name=name,
                    max_distinct=opts.max_distinct,
                    keep_samples_for_median=opts.median,
                )

            for row in reader:
                row_count += 1
                if row_count > opts.max_rows:
                    truncated = True
                    break

                row_dict: dict[str, Any] = {}
                for i, name in col_indices:
                    val = row[i] if i < len(row) else None
                    if val == "":
                        val = None
                    row_dict[name] = val
                    accumulators[name].update(val)

                if not opts.no_sample:
                    if len(head_rows) < opts.sample_head:
                        head_rows.append(row_dict)
                    if tail_maxlen:
                        tail_buf.append(row_dict)

        # Build outputs
        columns: list[ColumnInfo] = []
        stats: list[ColumnStats] = []
        for name in column_names:
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
                # Only show top values for non-numeric, non-datetime columns
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

        notes: list[str] = []
        if truncated:
            notes.append(f"Stats sampled from first {opts.max_rows:,} rows")

        tail_rows = list(tail_buf)
        # Avoid duplication when total rows fit in head+tail window
        if head_rows and tail_rows and row_count <= opts.sample_head + len(tail_rows):
            tail_rows = []

        return TableSummary(
            name=path.name,
            row_count=None if truncated else row_count,
            column_count=len(column_names),
            columns=columns,
            stats=stats,
            head=head_rows,
            tail=tail_rows,
            truncated=truncated,
            notes=notes,
        )

    # ── pandas path ────────────────────────────────────────────────────────────

    def _read_with_pandas(self, path: Path, opts: SummarizerOptions) -> TableSummary:
        import pandas as pd  # noqa: WPS433

        # Read one extra row to detect truncation
        # Only empty cells are null — matches the stdlib backend, which never
        # coerces strings like "NA"/"null" to missing values.
        df = pd.read_csv(
            path,
            sep=self.delimiter,
            nrows=opts.max_rows + 1,
            na_values=[""],
            keep_default_na=False,
        )
        truncated = len(df) > opts.max_rows
        if truncated:
            df = df.head(opts.max_rows)

        if opts.columns:
            keep = [c for c in df.columns if c in opts.columns]
            df = df[keep]
        if opts.max_columns and df.shape[1] > opts.max_columns:
            df = df.iloc[:, : opts.max_columns]

        n_rows = len(df)
        columns: list[ColumnInfo] = []
        stats: list[ColumnStats] = []

        for name in df.columns:
            col = df[name]
            null_count = int(col.isna().sum())
            try:
                distinct_count: int | None = int(col.nunique(dropna=True))
                if distinct_count > opts.max_distinct:
                    distinct_count = None
            except Exception:
                distinct_count = None

            dtype = self._pandas_dtype_label(col)
            null_pct = 100.0 * null_count / n_rows if n_rows else 0.0

            columns.append(
                ColumnInfo(
                    name=str(name),
                    dtype=dtype,
                    nullable=null_count > 0,
                    null_count=null_count,
                    null_pct=null_pct,
                    distinct_count=distinct_count,
                )
            )

            if not opts.no_stats:
                stats.append(self._pandas_column_stats(col, str(name), dtype, opts))

        head_rows: list[dict[str, Any]] = []
        tail_rows: list[dict[str, Any]] = []
        if not opts.no_sample:
            head_rows = df.head(opts.sample_head).to_dict(orient="records")
            if opts.sample_tail and n_rows > opts.sample_head:
                tail_rows = df.tail(opts.sample_tail).to_dict(orient="records")

        notes: list[str] = []
        if truncated:
            notes.append(f"Stats sampled from first {opts.max_rows:,} rows")

        return TableSummary(
            name=path.name,
            row_count=None if truncated else n_rows,
            column_count=int(df.shape[1]),
            columns=columns,
            stats=stats,
            head=head_rows,
            tail=tail_rows,
            truncated=truncated,
            notes=notes,
        )

    @staticmethod
    def _pandas_dtype_label(col: Any) -> str:
        import pandas as pd  # noqa: WPS433

        if pd.api.types.is_bool_dtype(col):
            return "bool"
        if pd.api.types.is_integer_dtype(col):
            return "int"
        if pd.api.types.is_float_dtype(col):
            return "float"
        if pd.api.types.is_datetime64_any_dtype(col):
            return "datetime"
        # Object columns: try to infer
        non_null = col.dropna()
        if non_null.empty:
            return "null"
        sample = non_null.iloc[: min(50, len(non_null))]
        try:
            pd.to_datetime(sample, errors="raise")
            return "datetime"
        except Exception:
            pass
        return "string"

    @staticmethod
    def _pandas_column_stats(col, name: str, dtype: str, opts: SummarizerOptions) -> ColumnStats:
        import pandas as pd  # noqa: WPS433

        count = int(col.notna().sum())
        null_count = int(col.isna().sum())
        try:
            distinct = int(col.nunique(dropna=True))
            if distinct > opts.max_distinct:
                distinct = None
        except Exception:
            distinct = None

        cs = ColumnStats(
            name=name,
            count=count,
            null_count=null_count,
            distinct_count=distinct,
        )

        if dtype in ("int", "float"):
            try:
                cs.min = float(col.min())
                cs.max = float(col.max())
                cs.mean = float(col.mean())
                if opts.median:
                    cs.median = float(col.median())
                cs.std = float(col.std()) if count > 1 else None
            except Exception:
                pass
        elif dtype == "datetime":
            try:
                series = pd.to_datetime(col, errors="coerce").dropna()
                if not series.empty:
                    cs.min_date = series.min().isoformat()
                    cs.max_date = series.max().isoformat()
            except Exception:
                pass
        else:
            try:
                vc = col.dropna().value_counts().head(opts.top_k)
                cs.top_values = [(idx, int(c)) for idx, c in vc.items()]
            except Exception:
                pass

        return cs
