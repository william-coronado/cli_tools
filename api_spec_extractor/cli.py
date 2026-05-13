from __future__ import annotations

import argparse
import json
import sys


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m api_spec_extractor.cli",
        description=(
            "Extract a catalog or detail view from an OpenAPI (2/3) or GraphQL SDL spec file. "
            "Reduces a 50 KB+ spec to the key info at a fraction of the token cost."
        ),
    )
    p.add_argument("source", help="Path to spec file (.json/.yaml/.graphql) or URL")

    p.add_argument("--output", "-o", default=None)
    p.add_argument("--format", choices=["markdown", "json", "text"], default="markdown")

    p.add_argument(
        "--endpoint", default=None,
        help="Filter paths containing this substring (e.g. /users)",
    )
    p.add_argument(
        "--method", default=None,
        help="Comma-separated HTTP methods to include (e.g. GET,POST)",
    )
    p.add_argument(
        "--tag", default=None, dest="tag",
        help="Filter OpenAPI endpoints by tag",
    )
    p.add_argument(
        "--detail", action="store_true",
        help="Include parameters, request body, and response schemas",
    )
    p.add_argument(
        "--include-deprecated", action="store_true", dest="include_deprecated",
        help="Include deprecated endpoints (excluded by default)",
    )
    p.add_argument("--timeout", type=int, default=10, help="URL fetch timeout in seconds")
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    from .extractor import SpecExtractor, ExtractorOptions
    from .parsers.base import WrongContentType, MissingOptionalDep

    method_filter = None
    if args.method:
        method_filter = [m.strip().upper() for m in args.method.split(",") if m.strip()]

    opts = ExtractorOptions(
        endpoint_filter=args.endpoint,
        method_filter=method_filter,
        tag_filter=args.tag,
        detail=args.detail,
        include_deprecated=args.include_deprecated,
        url_timeout=args.timeout,
    )

    try:
        result = SpecExtractor(opts).extract(args.source)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except WrongContentType as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    except MissingOptionalDep as e:
        print(f"error: {e}", file=sys.stderr)
        return 4

    if args.verbose:
        print(
            f"[{result.spec_format}] source={result.source} "
            f"total={result.total_endpoints} shown={result.shown_endpoints} "
            f"parsed_in={result.parse_duration_ms}ms",
            file=sys.stderr,
        )

    if args.format == "json":
        output = json.dumps(result.to_json(), indent=2)
    elif args.format == "text":
        output = result.to_text()
    else:
        output = result.to_markdown()

    if args.output:
        from pathlib import Path
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
