from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m url_fetcher.cli",
        description="Fetch a URL and return clean markdown.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("url", nargs="?", default=None, help="URL to fetch")
    group.add_argument("--batch", metavar="FILE", help="File with one URL per line")

    parser.add_argument("--output", "-o", default=None, help="Output file (default: stdout)")
    parser.add_argument(
        "--format", choices=["markdown", "json", "text"], default="markdown"
    )
    parser.add_argument("--no-cache", action="store_true", dest="no_cache")
    parser.add_argument("--clear-cache", action="store_true", dest="clear_cache")
    parser.add_argument("--cache-ttl", default="1h", dest="cache_ttl",
                        help="Cache TTL, e.g. 1h, 30m, 7d (default: 1h)")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--user-agent", dest="user_agent", default=None)
    parser.add_argument("--no-robots", action="store_true", dest="no_robots")
    parser.add_argument("--js", action="store_true", dest="js")
    parser.add_argument("--js-wait", type=float, default=3.0, dest="js_wait")
    parser.add_argument("--include-images", action="store_true", dest="include_images")
    parser.add_argument("--no-links", action="store_true", dest="no_links")
    parser.add_argument(
        "--header", action="append", default=[], metavar="Name: Value",
        help="Custom request header (repeatable)"
    )
    parser.add_argument("--batch-workers", type=int, default=5, dest="batch_workers")
    parser.add_argument("--batch-delay", type=float, default=1.0, dest="batch_delay")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args(argv)

    if args.clear_cache:
        from .cache import DiskCache
        n = DiskCache().clear()
        print(f"cleared {n} cache entries", file=sys.stderr)
        return 0

    from shared.duration import parse_duration
    try:
        cache_ttl_seconds = parse_duration(args.cache_ttl)
    except ValueError as e:
        print(f"error: --cache-ttl: {e}", file=sys.stderr)
        return 1

    extra_headers: dict[str, str] = {}
    for h in args.header:
        if ":" not in h:
            print(f"error: invalid header {h!r} — expected 'Name: Value'", file=sys.stderr)
            return 1
        name, _, value = h.partition(":")
        extra_headers[name.strip()] = value.strip()

    from .fetcher import (
        FetchConfig, URLFetcher,
        NetworkError, TimeoutError, HTTPError,
        RobotsBlocked, ContentTypeError, JSRequiredError, FetchError,
    )

    config = FetchConfig(
        timeout_seconds=args.timeout,
        user_agent=args.user_agent or FetchConfig.user_agent,
        respect_robots=not args.no_robots,
        use_cache=not args.no_cache,
        cache_ttl_seconds=cache_ttl_seconds,
        js_fallback=args.js,
        js_wait_seconds=args.js_wait,
        extra_headers=extra_headers or None,
    )
    fetcher = URLFetcher(config)

    include_links = not args.no_links

    if args.batch:
        batch_file = Path(args.batch)
        if not batch_file.exists():
            print(f"error: batch file not found: {batch_file}", file=sys.stderr)
            return 1
        urls = [
            line.strip()
            for line in batch_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        if not urls:
            print("error: batch file contains no URLs", file=sys.stderr)
            return 1

        batch = fetcher.fetch_batch(urls, max_workers=args.batch_workers, delay_between_requests=args.batch_delay)

        if args.verbose:
            print(
                f"batch: {batch.success_count}/{batch.total_urls} ok, "
                f"{batch.failed_count} failed, {batch.total_duration_ms}ms",
                file=sys.stderr,
            )
            for f in batch.failed:
                print(f"  failed: {f.url} — {f.error}", file=sys.stderr)

        if args.format == "json":
            output = json.dumps({
                "results": [r.to_json() for r in batch.results],
                "failed": [{"url": f.url, "error": f.error, "error_type": f.error_type} for f in batch.failed],
                "summary": {
                    "total": batch.total_urls,
                    "success": batch.success_count,
                    "failed": batch.failed_count,
                },
            }, indent=2)
        elif args.format == "text":
            output = "\n\n---\n\n".join(r.to_text() for r in batch.results)
        else:
            output = "\n\n---\n\n".join(r.to_markdown() for r in batch.results)

        _write_output(output, args.output)
        return 0 if batch.failed_count == 0 else 1

    # Single URL mode
    try:
        result = fetcher.fetch_with_options(args.url, include_links=include_links)
    except RobotsBlocked as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except ContentTypeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    except JSRequiredError as e:
        print(f"error: {e}", file=sys.stderr)
        return 4
    except (NetworkError, TimeoutError, HTTPError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except FetchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.verbose:
        print(
            f"fetched {result.url} in {result.fetch_duration_ms}ms "
            f"[{result.extractor_used}, "
            f"{'cache' if result.from_cache else 'live'}, "
            f"{result.content_length_original}→{result.content_length_extracted} bytes]",
            file=sys.stderr,
        )
        for w in result.warnings:
            print(f"warning: {w}", file=sys.stderr)

    if args.format == "json":
        output = json.dumps(result.to_json(), indent=2)
    elif args.format == "text":
        output = result.to_text()
    else:
        output = result.to_markdown()

    _write_output(output, args.output)
    return 0


def _write_output(output: str, path: str | None) -> None:
    if path:
        Path(path).write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    sys.exit(main())
