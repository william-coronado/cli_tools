from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m codebase_indexer.cli",
        description="Walk a code repository and produce a structured index.",
    )
    p.add_argument(
        "repo_path",
        nargs="?",
        default=".",
        help="Path to the repository root (default: current directory)",
    )
    p.add_argument("-o", "--output", help="Output file path (default: stdout)")
    p.add_argument(
        "--format",
        choices=["markdown", "json", "outline"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    p.add_argument(
        "--detail",
        choices=["low", "normal", "high"],
        default="normal",
        help="Detail level for markdown output (default: normal)",
    )
    p.add_argument(
        "--exclude",
        action="append",
        dest="excludes",
        metavar="PATTERN",
        help="Additional glob patterns to exclude (repeatable)",
    )
    p.add_argument(
        "--include-ext",
        action="append",
        dest="include_ext",
        metavar="EXT",
        help="Only index files with these extensions, e.g. .py .ts (repeatable)",
    )
    p.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Ignore .gitignore patterns",
    )
    p.add_argument(
        "--max-file-size",
        type=int,
        default=500,
        metavar="KB",
        help="Max file size in KB to parse (default: 500)",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Parallel workers for parsing (default: auto)",
    )
    p.add_argument(
        "--estimate-tokens",
        action="store_true",
        help="Print estimated token count of output to stderr",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show per-file progress",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    from .indexer import CodebaseIndexer

    try:
        indexer = CodebaseIndexer(
            root=args.repo_path,
            extra_excludes=args.excludes,
            respect_gitignore=not args.no_gitignore,
            max_file_size_kb=args.max_file_size,
            include_extensions=args.include_ext,
            show_progress=args.verbose,
            workers=args.workers,
        )
        index = indexer.build()
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "outline":
        output = index.to_outline()
    elif args.format == "json":
        output = json.dumps(index.to_json(), indent=2, default=str)
    else:
        output = index.to_markdown(detail=args.detail)

    if args.estimate_tokens:
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            n = len(enc.encode(output))
            print(f"Estimated tokens: ~{n:,}", file=sys.stderr)
        except ImportError:
            print("Warning: tiktoken not installed; skipping token estimate.", file=sys.stderr)

    if args.output:
        try:
            Path(args.output).write_text(output, encoding="utf-8")
        except OSError as exc:
            print(f"Error writing output file: {exc}", file=sys.stderr)
            return 1
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
