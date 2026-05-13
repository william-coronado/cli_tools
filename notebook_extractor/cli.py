from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _parse_slice(s: str | None) -> slice | None:
    if s is None:
        return None
    # Accept "3", "0:20", "5:", ":10"
    if ":" not in s:
        idx = int(s)
        return slice(idx, idx + 1)
    parts = s.split(":", 1)
    start = int(parts[0]) if parts[0] else None
    stop = int(parts[1]) if parts[1] else None
    return slice(start, stop)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m notebook_extractor.cli",
        description=(
            "Extract code and markdown from a Jupyter notebook (.ipynb), "
            "stripping heavy outputs (base64 images, long streams) to reduce tokens."
        ),
    )
    p.add_argument("path", help=".ipynb file or directory")

    p.add_argument("--output", "-o", default=None)
    p.add_argument("--format", choices=["markdown", "json", "text"], default="markdown")

    # Cell filtering
    p.add_argument("--cells", default=None,
                   help='Python-style slice, e.g. "0:20", "5:", ":10", "3"')
    p.add_argument("--code-only", action="store_true", dest="code_only")
    p.add_argument("--markdown-only", action="store_true", dest="markdown_only")
    p.add_argument("--no-code", action="store_true", dest="no_code")
    p.add_argument("--tag", action="append", default=None, dest="tags",
                   metavar="TAG", help="Only cells with this metadata tag (repeatable)")

    # Output handling
    p.add_argument("--no-outputs", action="store_true", dest="no_outputs")
    p.add_argument("--max-output-lines", type=int, default=30, dest="max_output_lines")
    p.add_argument("--no-dedup", action="store_true", dest="no_dedup")

    # Directory mode
    p.add_argument("--pattern", default="*.ipynb")
    p.add_argument("--recursive", action="store_true")

    p.add_argument("--verbose", "-v", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    from .extractor import NotebookExtractor, ExtractorOptions

    # Resolve conflicting type filters
    markdown_only = args.markdown_only or args.no_code
    code_only = args.code_only and not markdown_only

    opts = ExtractorOptions(
        cells_slice=_parse_slice(args.cells),
        code_only=code_only,
        markdown_only=markdown_only,
        tags=args.tags,
        no_outputs=args.no_outputs,
        max_output_lines=args.max_output_lines,
        no_dedup=args.no_dedup,
    )
    extractor = NotebookExtractor(opts)

    target = Path(args.path)
    if not target.exists():
        print(f"error: path not found: {target}", file=sys.stderr)
        return 1

    try:
        if target.is_dir():
            results = _extract_directory(target, args.pattern, args.recursive, extractor)
            if not results:
                print(f"error: no {args.pattern} files found in {target}", file=sys.stderr)
                return 3
        else:
            results = [extractor.extract(target)]
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.verbose:
        for r in results:
            print(
                f"[{r.source}] lang={r.language or '?'} "
                f"total={r.total_cells} shown={r.shown_cells} "
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


def _extract_directory(
    target: Path, pattern: str, recursive: bool, extractor
) -> list:
    from shared.walker import ExclusionRules
    rules = ExclusionRules(target, ignore_filename=".indexignore")
    walker = target.rglob if recursive else target.glob
    files = sorted(
        f for f in walker(pattern)
        if f.is_file() and not rules.is_excluded(f)
    )
    results = []
    for f in files:
        try:
            results.append(extractor.extract(f))
        except (ValueError, FileNotFoundError) as e:
            import sys
            print(f"warning: skipped {f}: {e}", file=sys.stderr)
    return results


if __name__ == "__main__":
    sys.exit(main())
