from __future__ import annotations

import urllib.error
import urllib.request


def fetch_spec(url: str, timeout: int = 10) -> tuple[str, str]:
    """Fetch a URL and return (content, content_type)."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "api_spec_extractor/1.0", "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            content_type = resp.headers.get("Content-Type", "")
            return content, content_type
    except urllib.error.HTTPError as e:
        raise ValueError(f"HTTP {e.code} fetching {url}") from e
    except urllib.error.URLError as e:
        raise ValueError(f"Failed to fetch {url}: {e.reason}") from e
