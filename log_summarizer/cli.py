from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m log_summarizer.cli",
        description="Summarize a log file, extracting errors, warnings, and metrics.",
    )
    parser.add_argument("path", help="Log file path, directory, or - for stdin")
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument("--format", choices=["markdown", "json", "text"], default="markdown")
    parser.add_argument(
        "--format-hint", dest="format_hint",
        choices=["pytest", "python", "training", "json", "webserver", "generic"],
        default=None,
    )
    parser.add_argument("--max-errors", type=int, default=50, dest="max_errors")
    parser.add_argument("--max-warnings", type=int, default=20, dest="max_warnings")
    parser.add_argument("--max-tracebacks", type=int, default=10, dest="max_tracebacks")
    parser.add_argument("--max-metrics", type=int, default=30, dest="max_metrics")
    parser.add_argument("--no-dedup", action="store_true", dest="no_dedup")
    parser.add_argument("--dedup-threshold", type=int, default=3, dest="dedup_threshold")
    parser.add_argument("--pattern", default="*.log")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--tail", type=int, default=None, metavar="N")
    parser.add_argument("--head", type=int, default=None, metavar="N")
    parser.add_argument("--errors-only", action="store_true", dest="errors_only")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args(argv)

    from .summarizer import LogSummarizer

    summarizer = LogSummarizer(
        max_errors=args.max_errors,
        max_warnings=args.max_warnings,
        max_tracebacks=args.max_tracebacks,
        max_metrics=args.max_metrics,
        dedup_threshold=args.dedup_threshold,
        format_hint=args.format_hint,
        errors_only=args.errors_only,
        use_dedup=not args.no_dedup,
    )

    try:
        if args.path == "-":
            source = _apply_window(sys.stdin, args.tail, args.head)
            result = summarizer.summarize(source)
            results = [result]
        else:
            target = Path(args.path)
            if not target.exists():
                print(f"error: path not found: {target}", file=sys.stderr)
                return 1
            if target.is_dir():
                results = summarizer.summarize_directory(
                    target, pattern=args.pattern, recursive=args.recursive
                )
                if not results:
                    return 0
            else:
                source = _apply_file_window(target, args.tail, args.head)
                if isinstance(source, Path):
                    result = summarizer.summarize(source)
                else:
                    result = summarizer.summarize(source)
                results = [result]
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except PermissionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.verbose:
        for r in results:
            print(
                f"[{r.source}] format={r.log_format} lines={r.total_lines:,} "
                f"errors={len(r.errors)} warnings={len(r.warnings)} "
                f"tracebacks={len(r.tracebacks)} suppressed={r.suppressed_line_count:,} "
                f"parsed_in={r.parse_duration_ms}ms",
                file=sys.stderr,
            )

    outputs: list[str] = []
    for r in results:
        if args.format == "json":
            outputs.append(json.dumps(r.to_json(), indent=2))
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


def _apply_file_window(path: Path, tail: int | None, head: int | None):
    """Return path unchanged (no window), or a closed-over generator for tail/head."""
    if tail is None and head is None:
        return path
    return _windowed_file(path, tail, head)


def _windowed_file(path: Path, tail: int | None, head: int | None):
    """Generator that opens the file in a with-block and delegates windowing to _apply_window."""
    with open(path, "rb") as f:
        yield from _apply_window(f, tail, head)


def _apply_window(source, tail: int | None, head: int | None):
    """Apply tail/head windowing to any line iterable (file or stdin)."""
    import itertools
    if tail is not None:
        buf: deque = deque(maxlen=tail)
        for line in source:
            buf.append(line)
        return iter(buf)
    elif head is not None:
        return itertools.islice(source, head)
    return source


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
