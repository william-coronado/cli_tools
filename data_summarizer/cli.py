from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _parse_columns(s: str | None) -> list[str] | None:
    if s is None:
        return None
    return [c.strip() for c in s.split(",") if c.strip()]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m data_summarizer.cli",
        description=(
            "Summarize a tabular or structured data file (CSV, TSV, JSON, JSONL, "
            "Parquet, Excel, SQLite). Returns schema, sample rows, and per-column "
            "statistics. Use instead of reading raw data files."
        ),
    )
    p.add_argument("path", help="File path or directory")
    p.add_argument(
        "--format-hint",
        dest="format_hint",
        choices=["csv", "tsv", "json", "jsonl", "parquet", "xlsx", "sqlite"],
        default=None,
    )

    p.add_argument("--output", "-o", default=None)
    p.add_argument("--format", choices=["markdown", "json", "text"], default="markdown")

    # Sampling
    p.add_argument("--sample", type=int, default=5)
    p.add_argument("--head", type=int, default=None)
    p.add_argument("--tail", type=int, default=None)
    p.add_argument("--no-sample", action="store_true", dest="no_sample")

    # Statistics
    p.add_argument("--no-stats", action="store_true", dest="no_stats")
    p.add_argument("--max-distinct", type=int, default=100, dest="max_distinct")
    p.add_argument("--top-k", type=int, default=5, dest="top_k")
    p.add_argument("--median", action="store_true")
    p.add_argument("--columns", default=None, help="Comma-separated subset")

    # Capping
    p.add_argument("--max-rows", type=int, default=100_000, dest="max_rows")
    p.add_argument("--max-columns", type=int, default=50, dest="max_columns")
    p.add_argument("--max-cell-width", type=int, default=80, dest="max_cell_width")
    p.add_argument(
        "--max-json-mb",
        type=int,
        default=50,
        dest="max_json_mb",
        help="Refuse to load whole-document JSON files larger than this (MB).",
    )

    # SQLite / Excel
    p.add_argument(
        "--table",
        action="append",
        default=None,
        help="SQLite table or Excel sheet. Repeatable.",
    )
    p.add_argument("--all-tables", action="store_true", dest="all_tables")
    p.add_argument("--max-tables", type=int, default=20, dest="max_tables")
    p.add_argument(
        "--query",
        default=None,
        help=(
            "Run a single read-only SELECT against a SQLite file instead of "
            "summarizing whole tables (e.g. --query 'SELECT id, name FROM "
            "users WHERE active = 1'). SELECT-only (including `WITH ... "
            "SELECT` CTEs); no mutations. Cannot be combined with "
            "--table/--all-tables/--columns — the query already selects its "
            "own tables and columns."
        ),
    )

    # Directory
    p.add_argument(
        "--pattern",
        default="*.csv,*.tsv,*.parquet,*.json,*.jsonl,*.ndjson,*.xlsx,*.sqlite,*.sqlite3,*.db",
    )
    p.add_argument("--recursive", action="store_true")

    p.add_argument("--verbose", "-v", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    from .summarizer import DataSummarizer, SummarizerOptions
    from .readers.base import MissingOptionalDep, WrongContentType

    # Resolve head/tail
    head = args.head if args.head is not None else (0 if args.no_sample else args.sample)
    tail = args.tail if args.tail is not None else (0 if args.no_sample else args.sample)

    opts = SummarizerOptions(
        sample_head=head,
        sample_tail=tail,
        no_sample=args.no_sample,
        no_stats=args.no_stats,
        median=args.median,
        max_distinct=args.max_distinct,
        top_k=args.top_k,
        max_rows=args.max_rows,
        max_columns=args.max_columns,
        max_cell_width=args.max_cell_width,
        max_tables=args.max_tables,
        max_json_bytes=args.max_json_mb * 1_000_000,
        all_tables=args.all_tables,
        columns=_parse_columns(args.columns),
        tables=args.table,
        format_hint=args.format_hint,
        query=args.query,
    )

    summarizer = DataSummarizer(opts)

    if args.path == "-":
        print("error: stdin input is not supported; provide a file path.", file=sys.stderr)
        return 1

    target = Path(args.path)
    if not target.exists():
        print(f"error: path not found: {target}", file=sys.stderr)
        return 1

    try:
        if target.is_dir():
            results = _summarize_directory(target, args.pattern, args.recursive, summarizer)
            if not results:
                print(f"warning: no matching files in {target}", file=sys.stderr)
                return 0
        else:
            results = [summarizer.summarize(target)]
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except PermissionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except MissingOptionalDep as e:
        print(f"error: {e}", file=sys.stderr)
        return 4
    except WrongContentType as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.verbose:
        for r in results:
            print(
                f"[{r.source}] format={r.file_format} backend={r.backend_used} "
                f"tables={len(r.tables)} size={r.file_size_bytes:,}B "
                f"parsed_in={r.parse_duration_ms}ms",
                file=sys.stderr,
            )

    outputs: list[str] = []
    for r in results:
        if args.format == "json":
            outputs.append(json.dumps(r.to_json(), indent=2, default=_json_default))
        elif args.format == "text":
            outputs.append(r.to_text())
        else:
            outputs.append(r.to_markdown())

    output = "\n\n---\n\n".join(outputs)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)

    return 0


def _json_default(o):
    from datetime import date, datetime
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    return str(o)


def _summarize_directory(target: Path, pattern: str, recursive: bool, summarizer) -> list:
    from shared.walker import ExclusionRules
    from .readers.base import MissingOptionalDep, WrongContentType

    patterns = [p.strip() for p in pattern.split(",") if p.strip()]
    rules = ExclusionRules(target, ignore_filename=".indexignore")

    matches: list[Path] = []
    walker = target.rglob if recursive else target.glob
    for pat in patterns:
        for f in walker(pat):
            if f.is_file() and not rules.is_excluded(f):
                matches.append(f)
    matches = sorted(set(matches))

    results = []
    for f in matches:
        try:
            results.append(summarizer.summarize(f))
        except (MissingOptionalDep, WrongContentType, ValueError) as e:
            print(f"warning: skipped {f}: {e}", file=sys.stderr)
    return results


if __name__ == "__main__":
    sys.exit(main())
