from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..summarizer import (
    ColumnInfo,
    ColumnStats,
    DataSummary,
    SummarizerOptions,
    TableSummary,
)
from .base import MissingOptionalDep, Reader


class ParquetReader(Reader):
    FORMAT_NAME = "parquet"

    def read(self, path: Path, opts: SummarizerOptions) -> DataSummary:
        t0 = time.monotonic()
        size = path.stat().st_size
        warnings: list[str] = []

        backend, df = self._load(path, opts)

        n_rows = len(df)
        truncated = False
        if n_rows > opts.max_rows:
            df = df.head(opts.max_rows)
            truncated = True
            n_rows = len(df)

        if opts.columns:
            keep = [c for c in df.columns if c in opts.columns]
            df = df[keep]
        if opts.max_columns and df.shape[1] > opts.max_columns:
            df = df.iloc[:, : opts.max_columns]

        from .csv_reader import CSVReader  # reuse pandas helpers
        columns: list[ColumnInfo] = []
        stats: list[ColumnStats] = []
        for name in df.columns:
            col = df[name]
            null_count = int(col.isna().sum())
            try:
                distinct: int | None = int(col.nunique(dropna=True))
                if distinct > opts.max_distinct:
                    distinct = None
            except Exception:
                distinct = None
            dtype = CSVReader._pandas_dtype_label(col)
            columns.append(
                ColumnInfo(
                    name=str(name),
                    dtype=dtype,
                    nullable=null_count > 0,
                    null_count=null_count,
                    null_pct=100.0 * null_count / n_rows if n_rows else 0.0,
                    distinct_count=distinct,
                )
            )
            if not opts.no_stats:
                stats.append(CSVReader._pandas_column_stats(col, str(name), dtype, opts))

        head_rows: list[dict[str, Any]] = []
        tail_rows: list[dict[str, Any]] = []
        if not opts.no_sample:
            head_rows = df.head(opts.sample_head).to_dict(orient="records")
            if opts.sample_tail and n_rows > opts.sample_head:
                tail_rows = df.tail(opts.sample_tail).to_dict(orient="records")

        notes: list[str] = []
        if truncated:
            notes.append(f"Stats sampled from first {opts.max_rows:,} rows")

        table = TableSummary(
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

        return DataSummary(
            source=str(path),
            file_size_bytes=size,
            file_format="parquet",
            parse_duration_ms=int((time.monotonic() - t0) * 1000),
            backend_used=backend,
            tables=[table],
            warnings=warnings,
        )

    @staticmethod
    def _load(path: Path, opts: SummarizerOptions):
        """Return (backend_name, dataframe). Raises MissingOptionalDep if neither lib present."""
        try:
            import pyarrow.parquet as pq  # noqa: WPS433
            import pyarrow as pa  # noqa: F401, WPS433
        except ImportError:
            pq = None  # type: ignore
        if pq is not None:
            try:
                import pandas  # noqa: F401, WPS433
                df = pq.read_table(str(path)).to_pandas()
                return "pyarrow+pandas", df
            except ImportError:
                # pyarrow alone — return arrow Table converted via own helper
                table = pq.read_table(str(path))
                # We need a pandas-like for our stat helpers; require pandas
                raise MissingOptionalDep(
                    "Parquet support requires pandas in addition to pyarrow. "
                    "Install with: pip install pandas"
                )
        # No pyarrow; try pandas fastparquet / pyarrow auto
        try:
            import pandas as pd  # noqa: WPS433
            df = pd.read_parquet(str(path))
            return "pandas", df
        except ImportError:
            raise MissingOptionalDep(
                "Parquet support requires pyarrow (or pandas with a parquet engine). "
                "Install with: pip install pyarrow"
            )
        except Exception as e:
            raise MissingOptionalDep(
                f"Parquet read failed: {e}. Install pyarrow: pip install pyarrow"
            )
