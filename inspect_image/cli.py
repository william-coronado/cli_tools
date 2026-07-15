from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m inspect_image.cli",
        description=(
            "Report image metadata: dimensions, color mode, format, and file "
            "size. Use instead of shelling out to Python/PIL for a quick "
            "dimension check."
        ),
    )
    p.add_argument("path", help="Path to an image file")
    p.add_argument("--output", "-o", default=None)
    p.add_argument("--format", choices=["markdown", "json", "text"], default="markdown")
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    from .inspector import MissingOptionalDep, WrongContentType, inspect_image

    try:
        info = inspect_image(args.path)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except MissingOptionalDep as e:
        print(f"error: {e}", file=sys.stderr)
        return 4
    except WrongContentType as e:
        print(f"error: {e}", file=sys.stderr)
        return 3

    if args.verbose:
        print(
            f"[inspect_image] {info.path} {info.width}x{info.height} "
            f"{info.format} ({info.file_size_bytes:,} bytes)",
            file=sys.stderr,
        )

    if args.format == "json":
        output = json.dumps(info.to_json(), indent=2)
    elif args.format == "text":
        output = info.to_text()
    else:
        output = info.to_markdown()

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
