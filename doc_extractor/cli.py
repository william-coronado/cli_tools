from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m doc_extractor.cli",
        description=(
            "Extract markdown from office/document formats (DOCX, PPTX, XLSX, "
            "EPUB, MSG) via markitdown. Use pdf_extractor for PDFs, "
            "notebook_extractor for .ipynb, data_summarizer for data files."
        ),
    )
    p.add_argument("path", help="Path to the document")
    p.add_argument("--format", choices=["markdown", "json", "text"], default="markdown")
    p.add_argument(
        "--max-chars",
        type=int,
        default=200_000,
        dest="max_chars",
        help="Truncate extracted markdown beyond this many characters (default: 200000)",
    )
    p.add_argument("--output", "-o", default=None)
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    from .extractor import (
        DocExtractor,
        ExtractorOptions,
        MissingOptionalDep,
        WrongContentType,
    )

    extractor = DocExtractor(ExtractorOptions(max_chars=args.max_chars))
    try:
        result = extractor.extract(Path(args.path))
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except WrongContentType as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    except MissingOptionalDep as e:
        print(f"error: {e}", file=sys.stderr)
        return 4
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.format == "json":
        output = json.dumps(result.to_json(), indent=2, ensure_ascii=False)
    elif args.format == "text":
        output = result.to_text()
    else:
        output = result.to_markdown()

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        if args.verbose:
            print(f"wrote {len(output)} chars to {args.output}", file=sys.stderr)
    else:
        print(output)

    if args.verbose:
        print(
            f"extracted {result.char_count:,} chars from {args.path} "
            f"in {result.parse_duration_ms}ms",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
