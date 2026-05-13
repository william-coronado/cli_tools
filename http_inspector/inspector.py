from __future__ import annotations

import json
import time
from dataclasses import dataclass, field


# Headers to keep (lowercase); everything else is dropped unless --show-all-headers
_KEEP_HEADERS = {
    "content-type", "content-length", "content-encoding",
    "transfer-encoding", "location", "date", "server",
    "retry-after", "last-modified", "etag",
}
_KEEP_PREFIXES = ("x-ratelimit-", "x-rate-limit-", "ratelimit-", "x-request-id", "x-correlation-")
_REDACT_HEADERS = {"set-cookie", "cookie", "authorization"}


@dataclass
class HeaderInfo:
    name: str
    value: str
    redacted: bool = False


@dataclass
class BodySummary:
    content_type: str
    detected_format: str          # json | xml | text | binary
    size_bytes: int
    # JSON
    json_shape: str | None = None
    json_sample: list | None = None
    json_array_len: int | None = None
    # Text / XML
    text_preview: str | None = None
    total_lines: int | None = None
    suppressed_lines: int = 0
    # Binary
    binary_stub: str | None = None
    # Shared
    truncated: bool = False
    parse_error: str | None = None


@dataclass
class TimingInfo:
    total_ms: int
    elapsed_ms: int | None = None


@dataclass
class HttpResult:
    url: str
    method: str
    status_code: int
    reason_phrase: str | None
    headers: list[HeaderInfo]
    body: BodySummary
    timing: TimingInfo
    warnings: list[str]
    redirect_history: list[int] = field(default_factory=list)

    def to_markdown(self) -> str:
        from .renderer import Renderer
        return Renderer().render_markdown(self)

    def to_json(self) -> dict:
        from .renderer import Renderer
        return Renderer().render_json(self)

    def to_text(self) -> str:
        from .renderer import Renderer
        return Renderer().render_text(self)


@dataclass
class InspectorOptions:
    method: str = "GET"
    headers: list[tuple[str, str]] = field(default_factory=list)
    data: bytes | None = None
    content_type: str | None = None
    max_body_lines: int = 50
    max_array_items: int = 5
    shape_only: bool = False
    no_redact_cookies: bool = False
    show_all_headers: bool = False
    follow_redirects: bool = True
    timeout: float = 10.0


class HttpInspector:
    def __init__(self, options: InspectorOptions | None = None) -> None:
        self.options = options or InspectorOptions()

    def inspect(self, url: str) -> HttpResult:
        try:
            import httpx
        except ImportError:
            raise RuntimeError(
                "httpx is required. Install it with: pip install httpx"
            )

        opts = self.options
        warnings: list[str] = []

        # Build request headers
        req_headers: dict[str, str] = {}
        for name, value in opts.headers:
            req_headers[name] = value
        if opts.data and "content-type" not in {k.lower() for k in req_headers}:
            ct = opts.content_type or "application/json"
            req_headers["Content-Type"] = ct

        t0 = time.monotonic()
        try:
            with httpx.Client(
                follow_redirects=opts.follow_redirects,
                timeout=opts.timeout,
            ) as client:
                response = client.request(
                    method=opts.method.upper(),
                    url=url,
                    headers=req_headers,
                    content=opts.data,
                )
        except httpx.TimeoutException as e:
            raise ValueError(f"Request timed out after {opts.timeout}s: {e}") from e
        except httpx.RequestError as e:
            raise ValueError(f"Request failed: {e}") from e

        total_ms = int((time.monotonic() - t0) * 1000)
        elapsed_ms = int(response.elapsed.total_seconds() * 1000) if response.elapsed else None

        redirect_history = [r.status_code for r in response.history]

        headers = self._process_headers(response.headers, opts, warnings)
        body = self._process_body(response, opts, warnings)

        return HttpResult(
            url=str(response.url),
            method=opts.method.upper(),
            status_code=response.status_code,
            reason_phrase=response.reason_phrase,
            headers=headers,
            body=body,
            timing=TimingInfo(total_ms=total_ms, elapsed_ms=elapsed_ms),
            warnings=warnings,
            redirect_history=redirect_history,
        )

    def _process_headers(
        self, headers, opts: InspectorOptions, warnings: list[str]
    ) -> list[HeaderInfo]:
        result: list[HeaderInfo] = []
        for name, value in headers.items():
            lower = name.lower()
            if lower in _REDACT_HEADERS:
                if opts.no_redact_cookies:
                    result.append(HeaderInfo(name=name, value=value, redacted=False))
                else:
                    redacted = _redact_cookie(value)
                    result.append(HeaderInfo(name=name, value=redacted, redacted=True))
                continue
            if opts.show_all_headers:
                result.append(HeaderInfo(name=name, value=value))
                continue
            if lower in _KEEP_HEADERS or any(lower.startswith(p) for p in _KEEP_PREFIXES):
                val = value[:200] if lower == "server" else value
                result.append(HeaderInfo(name=name, value=val))
        return result

    def _process_body(
        self, response, opts: InspectorOptions, warnings: list[str]
    ) -> BodySummary:
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        raw = response.content
        size_bytes = len(raw)

        # Binary check (non-text content types)
        if _is_binary(content_type, raw):
            ext = content_type.split("/")[-1].split("+")[0]
            return BodySummary(
                content_type=content_type,
                detected_format="binary",
                size_bytes=size_bytes,
                binary_stub=f"<binary: {content_type}, {size_bytes / 1024:.1f} KB>",
            )

        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = ""

        # JSON
        if "json" in content_type or _looks_like_json(text):
            return self._process_json(text, content_type, size_bytes, opts, warnings)

        # XML
        if "xml" in content_type or _looks_like_xml(text):
            return self._process_xml(text, content_type, size_bytes, opts)

        # Text fallback
        return self._process_text(text, content_type, size_bytes, opts)

    def _process_json(
        self, text: str, content_type: str, size_bytes: int,
        opts: InspectorOptions, warnings: list[str],
    ) -> BodySummary:
        from .body.json_shape import extract_json_summary
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            warnings.append(f"Body has JSON content-type but failed to parse: {e}")
            preview, total_lines, suppressed = _truncate(text, opts.max_body_lines)
            return BodySummary(
                content_type=content_type,
                detected_format="text",
                size_bytes=size_bytes,
                text_preview=preview,
                total_lines=total_lines,
                suppressed_lines=suppressed,
                truncated=suppressed > 0,
                parse_error=str(e),
            )

        shape, sample, array_len = extract_json_summary(
            data,
            max_array_items=opts.max_array_items,
            max_depth=3,
        )

        json_sample = None
        if sample is not None and not opts.shape_only:
            json_sample = sample

        return BodySummary(
            content_type=content_type,
            detected_format="json",
            size_bytes=size_bytes,
            json_shape=shape,
            json_sample=json_sample,
            json_array_len=array_len,
        )

    def _process_xml(
        self, text: str, content_type: str, size_bytes: int, opts: InspectorOptions
    ) -> BodySummary:
        from .body.xml_shape import summarize_xml
        preview = summarize_xml(text)
        return BodySummary(
            content_type=content_type,
            detected_format="xml",
            size_bytes=size_bytes,
            text_preview=preview,
        )

    def _process_text(
        self, text: str, content_type: str, size_bytes: int, opts: InspectorOptions
    ) -> BodySummary:
        preview, total_lines, suppressed = _truncate(text, opts.max_body_lines)
        return BodySummary(
            content_type=content_type,
            detected_format="text",
            size_bytes=size_bytes,
            text_preview=preview,
            total_lines=total_lines,
            suppressed_lines=suppressed,
            truncated=suppressed > 0,
        )


def _redact_cookie(value: str) -> str:
    # Only redact the first name=value pair (the actual cookie value).
    # Subsequent attributes (Path=/, HttpOnly, Secure, SameSite=...) are kept verbatim.
    parts = [p.strip() for p in value.split(";")]
    if not parts:
        return value
    first = parts[0]
    if "=" in first:
        name = first.split("=", 1)[0]
        parts[0] = f"{name}=<redacted>"
    return "; ".join(parts)


def _is_binary(content_type: str, raw: bytes) -> bool:
    text_types = ("text/", "application/json", "application/xml", "application/xhtml",
                  "application/javascript", "application/ld+json")
    if any(content_type.startswith(t) for t in text_types):
        return False
    if content_type in ("", "application/octet-stream"):
        # Sniff: check for null bytes in first 512 bytes
        return b"\x00" in raw[:512]
    return True


def _looks_like_json(text: str) -> bool:
    t = text.lstrip()
    return t.startswith("{") or t.startswith("[")


def _looks_like_xml(text: str) -> bool:
    t = text.lstrip()
    return t.startswith("<")


def _truncate(text: str, max_lines: int) -> tuple[str, int, int]:
    from .body.text import truncate_text
    return truncate_text(text, max_lines)
