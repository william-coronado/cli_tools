from __future__ import annotations
import argparse
import fnmatch
import re
import sys
import time
from datetime import datetime
from pathlib import Path


def _parse_size(s: str) -> int:
    m = re.match(r"^([\d.]+)\s*(B|KB|MB|GB)?$", s.strip(), re.IGNORECASE)
    if not m:
        raise argparse.ArgumentTypeError(f"Cannot parse size: {s!r}. Use e.g. '100KB', '1.5MB'")
    value = float(m.group(1))
    unit = (m.group(2) or "B").upper()
    multipliers = {"B": 1, "KB": 1_024, "MB": 1_048_576, "GB": 1_073_741_824}
    return int(value * multipliers[unit])


def _parse_duration_to_timestamp(s: str) -> float:
    """Return a Unix timestamp representing 'now minus duration', or parse ISO date."""
    import sys as _sys
    from pathlib import Path as _Path
    _root = _Path(__file__).parent.parent
    if str(_root) not in _sys.path:
        _sys.path.insert(0, str(_root))
    from shared.duration import parse_duration
    try:
        secs = parse_duration(s)
        return time.time() - secs
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Cannot parse date/duration: {s!r}. Use ISO date (2025-01-01) or relative (7d, 24h)"
        )


def _parse_recent_window(s: str) -> int:
    """Parse duration string to seconds using shared/duration.py."""
    import sys as _sys
    from pathlib import Path as _Path
    _root = _Path(__file__).parent.parent
    if str(_root) not in _sys.path:
        _sys.path.insert(0, str(_root))
    from shared.duration import parse_duration
    try:
        return parse_duration(s)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Cannot parse duration: {s!r}. Use e.g. '7d', '24h', '2w'"
        )


def _parse_threshold(s: str) -> int:
    return _parse_size(s)


def _is_glob(s: str) -> bool:
    return any(c in s for c in ("*", "?", "["))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m smart_file_tree.cli",
        description="Generate an annotated file tree for a directory.",
    )
    parser.add_argument("path", nargs="?", default=".", help="Directory to walk (default: .)")

    display = parser.add_argument_group("Display options")
    display.add_argument("--format", choices=["tree", "compact", "json"], default="tree")
    display.add_argument("--depth", "-d", type=int, default=None, metavar="N")
    display.add_argument("--dirs-only", action="store_true")
    display.add_argument("--files-only", action="store_true")
    display.add_argument("--sort", choices=["age", "alpha", "size"], default="age")
    display.add_argument("--focus", default=None, metavar="PATH_OR_GLOB")

    filt = parser.add_argument_group("Filtering options")
    filt.add_argument("--exclude", action="append", default=[], metavar="PATTERN")
    filt.add_argument("--include-ext", action="append", default=[], metavar="EXT")
    filt.add_argument("--no-gitignore", action="store_true")
    filt.add_argument("--show-hidden", action="store_true")
    filt.add_argument("--min-size", type=_parse_size, default=None)
    filt.add_argument("--max-size", type=_parse_size, default=None)
    filt.add_argument("--modified-after", type=_parse_duration_to_timestamp, default=None)
    filt.add_argument("--modified-before", type=_parse_duration_to_timestamp, default=None)

    ann = parser.add_argument_group("Annotation options")
    ann.add_argument("--recent-window", type=_parse_recent_window, default=None,
                     help="Duration for 'recently modified' annotation (default: 7d)")
    ann.add_argument("--large-threshold", type=_parse_threshold, default=1_048_576)

    out = parser.add_argument_group("Output options")
    out.add_argument("--output", "-o", default=None)
    out.add_argument("--no-summary", action="store_true")
    out.add_argument("--no-color", action="store_true")
    out.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args(argv)

    root = Path(args.path).resolve()

    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 1

    # Single-file mode
    if root.is_file():
        _print_single_file(root, args)
        return 0

    if not root.is_dir():
        print(f"error: not a directory or file: {root}", file=sys.stderr)
        return 1

    # Resolve focus
    focus_path: Path | None = None
    force_compact = False
    glob_pattern: str | None = None

    if args.focus:
        if _is_glob(args.focus):
            force_compact = True
            glob_pattern = args.focus
        else:
            candidate = root / args.focus
            if candidate.is_dir():
                focus_path = candidate
            else:
                print(
                    f"warning: --focus path not found: {candidate!r}, showing full tree",
                    file=sys.stderr,
                )

    fmt = args.format
    if force_compact:
        fmt = "compact"

    # recent_window is already in seconds (parsed by _parse_recent_window)
    recent_window = args.recent_window if args.recent_window is not None else 86_400 * 7

    from .tree import build

    start = time.time()
    result = build(
        root,
        respect_gitignore=not args.no_gitignore,
        extra_excludes=args.exclude or None,
        max_depth=args.depth,
        focus_path=focus_path,
        modified_after=args.modified_after,
        modified_before=args.modified_before,
        min_size=args.min_size,
        max_size=args.max_size,
        include_extensions=args.include_ext or None,
        dirs_only=args.dirs_only,
        files_only=args.files_only,
        large_threshold=args.large_threshold,
        recent_window=recent_window,
        show_hidden=args.show_hidden,
    )
    elapsed = time.time() - start

    # Apply glob filter post-build
    if glob_pattern:
        result.nodes = [
            n for n in result.nodes
            if n.is_dir or fnmatch.fnmatch(str(n.rel_path), glob_pattern)
        ]

    from .renderer import Renderer
    use_ansi = not args.no_color and (args.output is None)
    renderer = Renderer(use_ansi=use_ansi)
    output = renderer.render(result, fmt=fmt, sort=args.sort, no_summary=args.no_summary)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        if args.verbose:
            print(
                f"wrote {len(output)} chars to {args.output}",
                file=sys.stderr,
            )
    else:
        print(output)

    if args.verbose:
        print(
            f"scanned {result.total_files} files, {result.skipped_count} skipped, "
            f"{elapsed:.2f}s",
            file=sys.stderr,
        )

    return 0


def _print_single_file(path: Path, args: argparse.Namespace) -> None:
    from .annotator import FileAnnotator
    from .tree import TreeNode

    ann_obj = FileAnnotator()
    node = TreeNode(
        name=path.name,
        path=path,
        rel_path=path,
        is_dir=False,
        depth=0,
        annotation=None,
    )
    ann = ann_obj.annotate(node)
    lang = ann.language or "—"
    flags = "  " + "  ".join(f"[{f}]" for f in ann.flags) if ann.flags else ""
    print(f"{path.name}  {ann.size_human}  {lang}  {ann.modified_ago}{flags}")


if __name__ == "__main__":
    sys.exit(main())
