from __future__ import annotations

import re
import time
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock


# ── Exceptions ─────────────────────────────────────────────────────────────────

class FetchError(Exception):
    def __init__(self, message: str, url: str, error_type: str) -> None:
        self.url = url
        self.error_type = error_type
        super().__init__(message)

class NetworkError(FetchError): ...
class TimeoutError(FetchError): ...

class HTTPError(FetchError):
    def __init__(self, message: str, url: str, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(message, url, "http")

class RobotsBlocked(FetchError): ...
class ContentTypeError(FetchError): ...
class JSRequiredError(FetchError): ...
class ExtractionError(FetchError): ...


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class FetchConfig:
    timeout_seconds: float = 15.0
    max_redirects: int = 10
    user_agent: str = (
        "Mozilla/5.0 (compatible; url-fetcher/1.0; +https://github.com/your-org/tools)"
    )
    respect_robots: bool = True
    use_cache: bool = True
    cache_ttl_seconds: int = 3600
    max_content_bytes: int = 10_485_760
    js_fallback: bool = False
    js_wait_seconds: float = 3.0
    extra_headers: dict[str, str] | None = None


@dataclass
class ExtractionResult:
    url: str
    original_url: str
    title: str | None
    author: str | None
    published_date: str | None
    description: str | None
    content_markdown: str
    content_text: str
    extractor_used: str
    used_js_fallback: bool
    from_cache: bool
    fetch_duration_ms: int
    content_length_original: int
    content_length_extracted: int
    compression_ratio: float
    status_code: int
    content_type: str
    warnings: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        orig_kb = self.content_length_original / 1024
        ext_kb = self.content_length_extracted / 1024
        ratio = f"{self.compression_ratio:.0f}x" if self.compression_ratio >= 2 else "1x"

        lines: list[str] = []
        lines.append(f"# {self.title or self.url}")
        lines.append("")
        lines.append(f"**URL:** {self.url}")
        parts = []
        if self.author:
            parts.append(f"**Author:** {self.author}")
        if self.published_date:
            parts.append(f"**Published:** {self.published_date}")
        if parts:
            lines.append("  |  ".join(parts))
        lines.append(
            f"**Extracted:** {ts}  |  **Method:** {self.extractor_used}"
        )
        lines.append(
            f"**Original size:** {orig_kb:.1f} KB  →  "
            f"**Extracted:** {ext_kb:.1f} KB ({ratio} reduction)"
        )
        if self.warnings:
            for w in self.warnings:
                lines.append(f"> **Warning:** {w}")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(self.content_markdown)
        return "\n".join(lines)

    def to_text(self) -> str:
        return self.content_text

    def to_json(self) -> dict:
        return {
            "url": self.url,
            "original_url": self.original_url,
            "title": self.title,
            "author": self.author,
            "published_date": self.published_date,
            "description": self.description,
            "content_markdown": self.content_markdown,
            "content_text": self.content_text,
            "extractor_used": self.extractor_used,
            "used_js_fallback": self.used_js_fallback,
            "from_cache": self.from_cache,
            "fetch_duration_ms": self.fetch_duration_ms,
            "content_length_original": self.content_length_original,
            "content_length_extracted": self.content_length_extracted,
            "compression_ratio": self.compression_ratio,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "warnings": self.warnings,
        }


@dataclass
class FailedFetch:
    url: str
    error: str
    status_code: int | None
    error_type: str


@dataclass
class BatchResult:
    results: list[ExtractionResult]
    failed: list[FailedFetch]
    total_urls: int
    success_count: int
    failed_count: int
    total_duration_ms: int


# ── Fetcher ────────────────────────────────────────────────────────────────────

_MIN_CONTENT_CHARS = 200
_THIN_CONTENT_CHARS = 500
_TRAFILATURA_MIN_RATIO = 0.30   # re-run readability if trafilatura returns < 30% of raw text


class URLFetcher:
    def __init__(self, config: FetchConfig | None = None) -> None:
        self.config = config or FetchConfig()
        from .cache import DiskCache
        from .robots import RobotsChecker
        from .extractors.trafilatura_extractor import TrafilaturaExtractor
        from .extractors.readability_extractor import ReadabilityExtractor
        from .extractors.raw_extractor import RawExtractor
        from .renderer import MarkdownRenderer

        self._cache = DiskCache(ttl=self.config.cache_ttl_seconds) if self.config.use_cache else None
        self._robots = RobotsChecker() if self.config.respect_robots else None
        self._extractor_chain = [
            TrafilaturaExtractor(),
            ReadabilityExtractor(),
            RawExtractor(),
        ]
        self._renderer = MarkdownRenderer()

    def fetch(self, url: str) -> ExtractionResult:
        t0 = time.monotonic()
        original_url = url

        url = self._normalize_url(url)

        # Cache lookup — before robots check so repeated fetches don't re-hit robots.txt
        if self._cache:
            cached = self._cache.get(url)
            if cached:
                content, meta = cached
                return self._build_result(
                    content=content,
                    meta=meta,
                    original_url=original_url,
                    from_cache=True,
                    used_js=False,
                    t0=t0,
                    include_links=True,
                )

        if self._robots and not self._robots.is_allowed(url):
            raise RobotsBlocked(
                f"Fetching {url} is disallowed by robots.txt",
                url=url,
                error_type="robots",
            )

        content, status_code, content_type, final_url = self._http_fetch(url)

        if not self._is_downloadable(content_type):
            raise ContentTypeError(
                f"Content-type {content_type!r} is not extractable text. "
                "If this is a PDF, use the pdf_extractor tool instead.",
                url=url,
                error_type="content_type",
            )

        used_js = False
        if self.config.js_fallback and self._needs_js(content, content_type):
            content, status_code, content_type, final_url = self._js_fetch(url)
            used_js = True
        elif not self.config.js_fallback and self._needs_js(content, content_type):
            # Warn but continue — don't raise unless js_fallback was explicitly requested
            pass

        meta = {
            "status_code": status_code,
            "content_type": content_type,
            "final_url": final_url,
        }

        if self._cache:
            self._cache.set(url, content, meta)

        return self._build_result(
            content=content,
            meta=meta,
            original_url=original_url,
            from_cache=False,
            used_js=used_js,
            t0=t0,
            include_links=True,
        )

    def fetch_with_options(
        self,
        url: str,
        include_links: bool = True,
    ) -> ExtractionResult:
        t0 = time.monotonic()
        original_url = url
        url = self._normalize_url(url)

        if self._cache:
            cached = self._cache.get(url)
            if cached:
                content, meta = cached
                return self._build_result(
                    content=content,
                    meta=meta,
                    original_url=original_url,
                    from_cache=True,
                    used_js=False,
                    t0=t0,
                    include_links=include_links,
                )

        if self._robots and not self._robots.is_allowed(url):
            raise RobotsBlocked(
                f"Fetching {url} is disallowed by robots.txt",
                url=url,
                error_type="robots",
            )

        content, status_code, content_type, final_url = self._http_fetch(url)

        if not self._is_downloadable(content_type):
            raise ContentTypeError(
                f"Content-type {content_type!r} is not extractable text. "
                "If this is a PDF, use the pdf_extractor tool instead.",
                url=url,
                error_type="content_type",
            )

        used_js = False
        if self.config.js_fallback and self._needs_js(content, content_type):
            content, status_code, content_type, final_url = self._js_fetch(url)
            used_js = True

        meta = {
            "status_code": status_code,
            "content_type": content_type,
            "final_url": final_url,
        }

        if self._cache:
            self._cache.set(url, content, meta)

        return self._build_result(
            content=content,
            meta=meta,
            original_url=original_url,
            from_cache=False,
            used_js=used_js,
            t0=t0,
            include_links=include_links,
        )

    def fetch_batch(
        self,
        urls: list[str],
        max_workers: int = 5,
        delay_between_requests: float = 1.0,
    ) -> BatchResult:
        t0 = time.monotonic()
        results: list[ExtractionResult] = []
        failed: list[FailedFetch] = []

        # Per-domain last-request timestamp + locks
        domain_last: dict[str, float] = defaultdict(float)
        domain_locks: dict[str, Lock] = defaultdict(Lock)

        def _fetch_one(url: str) -> ExtractionResult | FailedFetch:
            try:
                normalized = self._normalize_url(url)
            except ValueError as e:
                return FailedFetch(url=url, error=str(e), status_code=None, error_type="network")

            domain = urllib.parse.urlparse(normalized).netloc
            with domain_locks[domain]:
                now = time.monotonic()
                wait = delay_between_requests - (now - domain_last[domain])
                if wait > 0:
                    time.sleep(wait)
                domain_last[domain] = time.monotonic()

            try:
                return self.fetch(url)
            except FetchError as e:
                status = getattr(e, "status_code", None)
                return FailedFetch(url=url, error=str(e), status_code=status, error_type=e.error_type)
            except Exception as e:
                return FailedFetch(url=url, error=str(e), status_code=None, error_type="network")

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_fetch_one, url): url for url in urls}
            for future in as_completed(futures):
                outcome = future.result()
                if isinstance(outcome, ExtractionResult):
                    results.append(outcome)
                else:
                    failed.append(outcome)

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return BatchResult(
            results=results,
            failed=failed,
            total_urls=len(urls),
            success_count=len(results),
            failed_count=len(failed),
            total_duration_ms=elapsed_ms,
        )

    # ── Internal: HTTP ─────────────────────────────────────────────────────────

    def _http_fetch(self, url: str) -> tuple[bytes, int, str, str]:
        try:
            import httpx
        except ImportError:
            raise RuntimeError("httpx is not installed. Run: pip install httpx")

        headers = {"User-Agent": self.config.user_agent}
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)

        try:
            with httpx.Client(
                timeout=self.config.timeout_seconds,
                max_redirects=self.config.max_redirects,
                follow_redirects=True,
            ) as client:
                response = client.get(url, headers=headers)
        except httpx.TimeoutException as e:
            raise TimeoutError(f"Request timed out: {url}", url=url, error_type="timeout") from e
        except httpx.ConnectError as e:
            raise NetworkError(f"Connection failed: {url} — {e}", url=url, error_type="network") from e
        except httpx.RequestError as e:
            raise NetworkError(f"Network error: {url} — {e}", url=url, error_type="network") from e

        final_url = str(response.url)
        content_type = response.headers.get("content-type", "text/html").split(";")[0].strip()

        if response.status_code == 429:
            retry_after = response.headers.get("retry-after", "unknown")
            raise HTTPError(
                f"Rate limited (429). Retry-After: {retry_after}",
                url=url,
                status_code=429,
            )

        if not (200 <= response.status_code < 300):
            raise HTTPError(
                f"HTTP {response.status_code}: {url}",
                url=url,
                status_code=response.status_code,
            )

        content = response.content
        if len(content) > self.config.max_content_bytes:
            content = content[: self.config.max_content_bytes]

        return content, response.status_code, content_type, final_url

    def _js_fetch(self, url: str) -> tuple[bytes, int, str, str]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise JSRequiredError(
                "This page requires JavaScript but Playwright is not installed.\n"
                "Install it with:\n"
                "  pip install playwright\n"
                "  playwright install chromium",
                url=url,
                error_type="js_required",
            )

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(
                    user_agent=self.config.user_agent,
                    extra_http_headers=self.config.extra_headers or {},
                )
                response = page.goto(url, timeout=int(self.config.timeout_seconds * 1000))
                page.wait_for_load_state("networkidle")
                if self.config.js_wait_seconds > 0:
                    page.wait_for_timeout(int(self.config.js_wait_seconds * 1000))
                html = page.content().encode("utf-8")
                status_code = response.status if response else 200
                final_url = page.url
            finally:
                browser.close()

        return html, status_code, "text/html", final_url

    # ── Internal: Detection ────────────────────────────────────────────────────

    def _needs_js(self, content: bytes, content_type: str) -> bool:
        if "text/html" not in content_type:
            return False
        try:
            text = content.decode("utf-8", errors="replace")
        except Exception:
            return False

        # Empty-ish body
        stripped = re.sub(r"<[^>]+>", "", text).strip()
        if len(stripped) < 200:
            return True

        # Common JS shell markers
        js_markers = [
            r'<div\s+id="root"\s*>\s*</div>',
            r'<div\s+id="app"\s*>\s*</div>',
            r'Please enable JavaScript',
            r'You need to enable JavaScript',
            r'<noscript>.*?</noscript>',
        ]
        for pattern in js_markers:
            if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
                return True

        return False

    # ── Internal: URL ──────────────────────────────────────────────────────────

    def _normalize_url(self, url: str) -> str:
        url = url.strip()
        if not url:
            raise ValueError("URL cannot be empty")

        # Add scheme if missing
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", url):
            url = "https://" + url

        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                f"Unsupported URL scheme: {parsed.scheme!r}. Only http:// and https:// are allowed."
            )
        if not parsed.netloc or " " in parsed.netloc or not re.match(r"^[^\s/]+$", parsed.netloc):
            raise ValueError(f"Malformed URL (invalid host): {url!r}")

        return url

    def _is_downloadable(self, content_type: str) -> bool:
        ct = content_type.lower()
        extractable = ("text/html", "text/plain", "application/xhtml+xml")
        return any(ct.startswith(e) for e in extractable)

    # ── Internal: Extraction ───────────────────────────────────────────────────

    def _run_extractor_chain(
        self,
        html: bytes,
        url: str,
        content_type: str,
    ) -> tuple[str, str, str]:
        """Returns (content_html, extractor_name, title)."""
        from .extractors.trafilatura_extractor import TrafilaturaExtractor
        from .extractors.readability_extractor import ReadabilityExtractor

        # Decode for raw text comparison
        try:
            from charset_normalizer import from_bytes
            decoded = str(from_bytes(html).best() or html.decode("utf-8", errors="replace"))
        except ImportError:
            decoded = html.decode("utf-8", errors="replace")

        raw_text_len = len(re.sub(r"<[^>]+>", "", decoded).strip())

        best_output = None
        best_name = ""

        for extractor in self._extractor_chain:
            output = extractor.extract(html, url)
            if output.success:
                # Trafilatura over-prune check
                if isinstance(extractor, TrafilaturaExtractor) and raw_text_len > 0:
                    ratio = len(output.content_text) / raw_text_len
                    if ratio < _TRAFILATURA_MIN_RATIO:
                        # Try readability as secondary check
                        readability_output = ReadabilityExtractor().extract(html, url)
                        if readability_output.success and len(readability_output.content_text) > len(output.content_text):
                            return readability_output.content_html, "readability", readability_output.title or ""
                return output.content_html, type(extractor).__name__.replace("Extractor", "").lower(), output.title or ""

        # All failed — use raw extractor's output regardless
        raw = self._extractor_chain[-1].extract(html, url)
        return raw.content_html, "raw", raw.title or ""

    # ── Internal: Build result ─────────────────────────────────────────────────

    def _build_result(
        self,
        content: bytes,
        meta: dict,
        original_url: str,
        from_cache: bool,
        used_js: bool,
        t0: float,
        include_links: bool = True,
    ) -> ExtractionResult:
        final_url = meta.get("final_url", original_url)
        status_code = meta.get("status_code", 200)
        content_type = meta.get("content_type", "text/html")

        content_html, extractor_name, title = self._run_extractor_chain(
            content, final_url, content_type
        )

        # Extract metadata from the best extractor output
        from .extractors.trafilatura_extractor import TrafilaturaExtractor
        traf_out = self._extractor_chain[0].extract(content, final_url)
        author = traf_out.author
        published_date = traf_out.published_date
        description = traf_out.description
        if traf_out.title:
            title = traf_out.title

        if include_links:
            content_md = self._renderer.render(content_html, final_url)
        else:
            content_md = self._renderer.render_without_links(content_html, final_url)

        try:
            from bs4 import BeautifulSoup
            content_text = BeautifulSoup(content_html, "lxml").get_text(separator="\n").strip()
        except Exception:
            content_text = re.sub(r"<[^>]+>", "", content_html).strip()

        warnings: list[str] = []
        if len(content_text) < _THIN_CONTENT_CHARS:
            warnings.append(
                f"Extracted content is very short ({len(content_text)} chars) "
                "— page may require JS or login."
            )

        orig_len = len(content)
        ext_len = len(content_md.encode("utf-8"))
        ratio = orig_len / ext_len if ext_len > 0 else 1.0

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        return ExtractionResult(
            url=final_url,
            original_url=original_url,
            title=title or None,
            author=author,
            published_date=published_date,
            description=description,
            content_markdown=content_md,
            content_text=content_text,
            extractor_used=extractor_name,
            used_js_fallback=used_js,
            from_cache=from_cache,
            fetch_duration_ms=elapsed_ms,
            content_length_original=orig_len,
            content_length_extracted=ext_len,
            compression_ratio=ratio,
            status_code=status_code,
            content_type=content_type,
            warnings=warnings,
        )
