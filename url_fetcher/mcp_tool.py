from __future__ import annotations

import json
import sys


TOOL_DEFINITIONS = [
    {
        "name": "fetch_url",
        "description": (
            "Fetch a URL and return clean, readable markdown. Strips navigation, ads, "
            "footers, and boilerplate HTML. Returns only the main content. Use this "
            "instead of reading raw HTML to save tokens."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch.",
                },
                "use_js": {
                    "type": "boolean",
                    "description": "Use Playwright for JS-rendered pages. Requires playwright installed.",
                },
                "no_cache": {
                    "type": "boolean",
                    "description": "Skip cache and always fetch fresh.",
                },
                "include_links": {
                    "type": "boolean",
                    "description": "Keep hyperlinks in markdown output. Default: true.",
                },
            },
            "required": ["url"],
        },
    }
]


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


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            name = request.get("name")
            params = request.get("parameters", {})
            if name == "fetch_url":
                result = _handle(params)
            else:
                result = json.dumps({"error": f"Unknown tool: {name}"})
            response = {"result": result}
        except Exception as e:
            response = {"error": str(e)}
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
