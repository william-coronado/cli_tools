from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _parse_severity(s: str | None) -> list[str] | None:
    if s is None:
        return None
    return [x.strip().lower() for x in s.split(",") if x.strip()]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m dep_inspector.cli",
        description=(
            "Inspect Python or JavaScript dependencies: declared / resolved / "
            "transitive summary, plus optional --outdated and --audit checks."
        ),
    )
    p.add_argument("path", help="Project directory OR a single manifest/lockfile path")
    p.add_argument("--ecosystem", choices=["pypi", "npm"], default=None)
    p.add_argument("--no-dev", action="store_true", dest="no_dev")

    p.add_argument("--output", "-o", default=None)
    p.add_argument("--format", choices=["markdown", "json", "text"], default="markdown")

    p.add_argument("--all", action="store_true", dest="show_all_transitives")
    p.add_argument("--top-transitives", type=int, default=10, dest="top_transitives_k")

    p.add_argument("--outdated", action="store_true")
    p.add_argument("--audit", action="store_true")
    p.add_argument("--severity", default=None,
                   help="Comma-separated: critical,high,medium,low")
    p.add_argument("--timeout", type=float, default=10.0,
                   dest="network_timeout_s")
    p.add_argument("--workers", type=int, default=16,
                   dest="network_workers")

    p.add_argument("--direct-only", action="store_true", dest="direct_only")
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    from .inspector import DepInspector, InspectorOptions
    from .parsers.base import WrongContentType, MissingOptionalDep

    opts = InspectorOptions(
        direct_only=args.direct_only,
        outdated=args.outdated,
        audit=args.audit,
        ecosystem=args.ecosystem,
        show_all_transitives=args.show_all_transitives,
        top_transitives_k=args.top_transitives_k,
        network_timeout_s=args.network_timeout_s,
        network_workers=args.network_workers,
        include_dev=not args.no_dev,
        severity_filter=_parse_severity(args.severity),
    )

    target = Path(args.path)
    try:
        result = DepInspector(opts).inspect(target)
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

    if args.verbose:
        for e in result.ecosystems:
            print(
                f"[{e.ecosystem}] manifest={e.manifest_path or '-'} "
                f"lockfile={e.lockfile_path or '-'} direct={len(e.direct_deps)} "
                f"transitives={e.transitive_count}",
                file=sys.stderr,
            )

    if args.format == "json":
        output = json.dumps(result.to_json(), indent=2, default=str)
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
