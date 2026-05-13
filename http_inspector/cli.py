from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _parse_header(s: str) -> tuple[str, str]:
    if ":" not in s:
        raise argparse.ArgumentTypeError(f"Header must be 'Name: Value', got: {s!r}")
    name, _, value = s.partition(":")
    return name.strip(), value.strip()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m http_inspector.cli",
        description=(
            "Make an HTTP request and return a token-efficient summary: "
            "status, selected headers, and a shape + sample of the response body."
        ),
    )
    p.add_argument("url", help="URL to request")

    p.add_argument("-X", "--method", default=None, metavar="METHOD",
                   help="HTTP method (default: GET, or POST when --data is set)")
    p.add_argument("-H", "--header", action="append", default=[], dest="headers",
                   metavar="Name: Value", help="Request header (repeatable)")
    p.add_argument("--data", "-d", default=None,
                   help="Request body: @file.json, - for stdin, or inline string")
    p.add_argument("--content-type", default=None, dest="content_type",
                   help="Content-Type for --data (default: application/json)")

    p.add_argument("--output", "-o", default=None)
    p.add_argument("--format", choices=["markdown", "json", "text"], default="markdown")

    p.add_argument("--max-body-lines", type=int, default=50, dest="max_body_lines",
                   help="Max text/error lines to show (default 50)")
    p.add_argument("--max-array-items", type=int, default=5, dest="max_array_items",
                   help="Max JSON array items to include in sample (default 5)")
    p.add_argument("--shape-only", action="store_true", dest="shape_only",
                   help="Show JSON shape only, no sample records")
    p.add_argument("--no-redact-cookies", action="store_true", dest="no_redact_cookies",
                   help="Show full Set-Cookie values (default: cookie values redacted)")
    p.add_argument("--show-all-headers", action="store_true", dest="show_all_headers",
                   help="Show all response headers (default: show only relevant ones)")
    p.add_argument("--no-follow-redirects", action="store_false", dest="follow_redirects",
                   help="Do not follow HTTP redirects")
    p.add_argument("--timeout", type=float, default=10.0,
                   help="Request timeout in seconds (default 10)")
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    from .inspector import HttpInspector, InspectorOptions

    # Parse headers
    headers: list[tuple[str, str]] = []
    for raw in args.headers:
        try:
            headers.append(_parse_header(raw))
        except argparse.ArgumentTypeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    # Parse body
    body: bytes | None = None
    if args.data is not None:
        if args.data.startswith("@"):
            path_str = args.data[1:]
            if path_str == "-":
                body = sys.stdin.buffer.read()
            else:
                p = Path(path_str)
                if not p.exists():
                    print(f"error: file not found: {p}", file=sys.stderr)
                    return 1
                body = p.read_bytes()
        elif args.data == "-":
            body = sys.stdin.buffer.read()
        else:
            body = args.data.encode("utf-8")

    method = args.method
    if method is None:
        method = "POST" if body is not None else "GET"

    opts = InspectorOptions(
        method=method,
        headers=headers,
        data=body,
        content_type=args.content_type,
        max_body_lines=args.max_body_lines,
        max_array_items=args.max_array_items,
        shape_only=args.shape_only,
        no_redact_cookies=args.no_redact_cookies,
        show_all_headers=args.show_all_headers,
        follow_redirects=args.follow_redirects,
        timeout=args.timeout,
    )

    try:
        result = HttpInspector(opts).inspect(args.url)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 4

    if args.verbose:
        print(
            f"[http] {result.method} {result.url} → {result.status_code} "
            f"in {result.timing.elapsed_ms or result.timing.total_ms}ms "
            f"({result.body.size_bytes} bytes, {result.body.detected_format})",
            file=sys.stderr,
        )

    if args.format == "json":
        output = json.dumps(result.to_json(), indent=2)
    elif args.format == "text":
        output = result.to_text()
    else:
        output = result.to_markdown()

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
