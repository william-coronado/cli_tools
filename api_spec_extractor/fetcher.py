from __future__ import annotations

import urllib.error
import urllib.request

# Specs are text documents; anything past this is almost certainly not a spec
# and would otherwise be buffered into memory unbounded.
_MAX_SPEC_BYTES = 10 * 1024 * 1024


def fetch_spec(url: str, timeout: int = 10, max_bytes: int = _MAX_SPEC_BYTES) -> tuple[str, str]:
    """Fetch a URL and return (content, content_type)."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "api_spec_extractor/1.0", "Accept": "*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError(
                    f"Response from {url} exceeds the {max_bytes // (1024 * 1024)} MB "
                    f"spec size limit"
                )
            content = data.decode("utf-8", errors="replace")
            content_type = resp.headers.get("Content-Type", "")
            return content, content_type
    except urllib.error.HTTPError as e:
        raise ValueError(f"HTTP {e.code} fetching {url}") from e
    except urllib.error.URLError as e:
        raise ValueError(f"Failed to fetch {url}: {e.reason}") from e
