from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..summarizer import DataSummary, SummarizerOptions


class MissingOptionalDep(RuntimeError):
    """Raised when a reader requires an optional dep that isn't installed."""


class WrongContentType(RuntimeError):
    """Raised when content doesn't match any known reader."""


class Reader(ABC):
    FORMAT_NAME: str = ""

    @abstractmethod
    def read(self, path: Path, opts: SummarizerOptions) -> DataSummary: ...


_EXT_TO_HINT: dict[str, str] = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".parquet": "parquet",
    ".pq": "parquet",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".sqlite": "sqlite",
    ".sqlite3": "sqlite",
    ".db": "sqlite",
}


def _hint_for_path(path: Path) -> str | None:
    return _EXT_TO_HINT.get(path.suffix.lower())


def _content_sniff(path: Path) -> str | None:
    """Last-resort sniff for files without a recognized extension."""
    try:
        with open(path, "rb") as f:
            head = f.read(2048)
    except OSError:
        return None
    sample = head.lstrip()
    if not sample:
        return None
    first = sample[:1]
    if first in (b"{", b"["):
        return "json" if first == b"{" else "jsonl"
    # SQLite magic header
    if head.startswith(b"SQLite format 3\x00"):
        return "sqlite"
    # CSV: contains a comma in the first line, mostly printable
    try:
        text_head = head.decode("utf-8", errors="replace")
    except Exception:
        return None
    first_line = text_head.split("\n", 1)[0]
    if "," in first_line and len(first_line) < 4096:
        return "csv"
    return None


def dispatch_reader(path: Path, format_hint: str | None) -> Reader:
    hint = format_hint or _hint_for_path(path) or _content_sniff(path)
    if hint is None:
        raise ValueError(
            f"Could not infer format for {path}; use --format-hint to override."
        )

    if hint in ("csv", "tsv"):
        from .csv_reader import CSVReader
        return CSVReader(delimiter="\t" if hint == "tsv" else ",")
    if hint == "jsonl":
        from .jsonl_reader import JSONLReader
        return JSONLReader()
    if hint == "json":
        from .json_reader import JSONReader
        return JSONReader()
    if hint == "parquet":
        from .parquet_reader import ParquetReader
        return ParquetReader()
    if hint == "xlsx":
        from .excel_reader import ExcelReader
        return ExcelReader()
    if hint == "sqlite":
        from .sqlite_reader import SQLiteReader
        return SQLiteReader()

    raise ValueError(f"Unknown format hint: {hint}")
