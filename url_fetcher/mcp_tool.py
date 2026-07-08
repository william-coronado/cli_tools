"""MCP handler for url_fetcher. Exposed via the unified server (mcp_server.py)."""
from __future__ import annotations


def _handle(params: dict) -> str:
    from .fetcher import FetchConfig, URLFetcher

    url = params["url"]
    use_js = bool(params.get("use_js", False))
    no_cache = bool(params.get("no_cache", False))
    include_links = bool(params.get("include_links", True))

    config = FetchConfig(js_fallback=use_js, use_cache=not no_cache)
    fetcher = URLFetcher(config)
    result = fetcher.fetch_with_options(url, include_links=include_links)
    return result.to_markdown()
