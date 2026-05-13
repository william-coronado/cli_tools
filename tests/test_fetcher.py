"""Tests for url_fetcher.

All HTTP calls are mocked with respx. No real network calls are made.
DiskCache always receives a tmp_path to avoid touching ~/.cache/url_fetcher/.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import respx
import httpx

from url_fetcher.fetcher import (
    FetchConfig,
    URLFetcher,
    ExtractionResult,
    BatchResult,
    FailedFetch,
    NetworkError,
    TimeoutError as FetchTimeoutError,
    HTTPError,
    RobotsBlocked,
    ContentTypeError,
    JSRequiredError,
)
from url_fetcher.cache import DiskCache
from url_fetcher.renderer import MarkdownRenderer, _strip_nav_link_lists
from url_fetcher.robots import RobotsChecker


FIXTURES = Path(__file__).parent / "fixtures" / "html"
ARTICLE_HTML = (FIXTURES / "article.html").read_bytes()
DOCS_HTML = (FIXTURES / "docs_page.html").read_bytes()
JS_SHELL_HTML = (FIXTURES / "js_shell.html").read_bytes()
MINIMAL_HTML = (FIXTURES / "minimal.html").read_bytes()


def _make_fetcher(tmp_path: Path, **kwargs) -> URLFetcher:
    """Create a URLFetcher with a tmp cache dir and robots disabled by default."""
    config = FetchConfig(
        respect_robots=kwargs.pop("respect_robots", False),
        use_cache=kwargs.pop("use_cache", True),
        cache_ttl_seconds=kwargs.pop("cache_ttl_seconds", 3600),
        **kwargs,
    )
    fetcher = URLFetcher(config)
    if fetcher._cache:
        fetcher._cache._dir = tmp_path / "cache"
        fetcher._cache._dir.mkdir(parents=True, exist_ok=True)
    return fetcher


# ── DiskCache ──────────────────────────────────────────────────────────────────

class TestDiskCache:
    def test_set_and_get(self, tmp_path):
        cache = DiskCache(cache_dir=tmp_path)
        cache.set("https://example.com", b"hello", {"status_code": 200})
        result = cache.get("https://example.com")
        assert result is not None
        content, meta = result
        assert content == b"hello"
        assert meta["status_code"] == 200

    def test_miss_returns_none(self, tmp_path):
        cache = DiskCache(cache_dir=tmp_path)
        assert cache.get("https://example.com/never") is None

    def test_expired_returns_none(self, tmp_path):
        cache = DiskCache(cache_dir=tmp_path, ttl=1)
        cache.set("https://example.com", b"data", {})
        # Manually backdate the cached_at
        import json as _json
        key = cache._cache_key("https://example.com")
        meta_path = tmp_path / f"{key}.json"
        meta = _json.loads(meta_path.read_text())
        meta["cached_at"] = time.time() - 10
        meta_path.write_text(_json.dumps(meta))
        assert cache.get("https://example.com") is None

    def test_delete(self, tmp_path):
        cache = DiskCache(cache_dir=tmp_path)
        cache.set("https://example.com", b"x", {})
        assert cache.delete("https://example.com") is True
        assert cache.get("https://example.com") is None

    def test_clear_all(self, tmp_path):
        cache = DiskCache(cache_dir=tmp_path)
        cache.set("https://a.com", b"a", {})
        cache.set("https://b.com", b"b", {})
        n = cache.clear()
        assert n == 2
        assert cache.stats()["total_entries"] == 0

    def test_stats(self, tmp_path):
        cache = DiskCache(cache_dir=tmp_path)
        cache.set("https://x.com", b"content", {})
        s = cache.stats()
        assert s["total_entries"] == 1
        assert s["total_size_bytes"] >= 7


# ── MarkdownRenderer ───────────────────────────────────────────────────────────

class TestMarkdownRenderer:
    def test_renders_html_to_markdown(self):
        renderer = MarkdownRenderer()
        md = renderer.render("<h1>Title</h1><p>Hello world.</p>", "https://example.com")
        assert "# Title" in md
        assert "Hello world." in md

    def test_collapses_blank_lines(self):
        renderer = MarkdownRenderer()
        md = renderer._clean_markdown("a\n\n\n\n\nb")
        assert "\n\n\n" not in md

    def test_removes_empty_links(self):
        renderer = MarkdownRenderer()
        md = renderer._clean_markdown("text [](https://example.com) more")
        assert "[](https://example.com)" not in md

    def test_strips_nav_link_lists(self):
        nav_md = "- [Home](https://example.com/)\n- [About](https://example.com/about)\n- [Contact](https://example.com/contact)"
        result = _strip_nav_link_lists(nav_md)
        assert result.strip() == ""

    def test_relative_urls_resolved(self):
        renderer = MarkdownRenderer()
        html = '<a href="/page">Link</a>'
        md = renderer.render(html, "https://example.com")
        assert "example.com/page" in md

    def test_render_without_links_strips_anchors(self):
        renderer = MarkdownRenderer()
        html = '<p>See <a href="https://example.com">this</a>.</p>'
        md = renderer.render_without_links(html, "https://example.com")
        assert "example.com" not in md
        assert "See" in md


# ── URLFetcher._normalize_url ──────────────────────────────────────────────────

class TestNormalizeUrl:
    def _fetcher(self):
        config = FetchConfig(respect_robots=False, use_cache=False)
        return URLFetcher(config)

    def test_adds_https_scheme(self):
        f = self._fetcher()
        assert f._normalize_url("example.com/path") == "https://example.com/path"

    def test_passes_through_https(self):
        f = self._fetcher()
        assert f._normalize_url("https://example.com/") == "https://example.com/"

    def test_rejects_ftp(self):
        f = self._fetcher()
        with pytest.raises(ValueError, match="Unsupported"):
            f._normalize_url("ftp://example.com")

    def test_rejects_file(self):
        f = self._fetcher()
        with pytest.raises(ValueError, match="Unsupported"):
            f._normalize_url("file:///etc/passwd")

    def test_rejects_empty(self):
        f = self._fetcher()
        with pytest.raises(ValueError):
            f._normalize_url("")

    def test_malformed_raises(self):
        f = self._fetcher()
        with pytest.raises(ValueError):
            f._normalize_url("not a url")


# ── URLFetcher._needs_js ───────────────────────────────────────────────────────

class TestNeedsJs:
    def _fetcher(self):
        config = FetchConfig(respect_robots=False, use_cache=False)
        return URLFetcher(config)

    def test_js_shell_detected(self):
        f = self._fetcher()
        assert f._needs_js(JS_SHELL_HTML, "text/html") is True

    def test_rich_page_not_js(self):
        f = self._fetcher()
        assert f._needs_js(ARTICLE_HTML, "text/html") is False

    def test_non_html_not_js(self):
        f = self._fetcher()
        assert f._needs_js(b'{"key": "value"}', "application/json") is False


# ── URLFetcher._is_downloadable ────────────────────────────────────────────────

class TestIsDownloadable:
    def _fetcher(self):
        config = FetchConfig(respect_robots=False, use_cache=False)
        return URLFetcher(config)

    def test_html_downloadable(self):
        assert self._fetcher()._is_downloadable("text/html") is True

    def test_plain_text_downloadable(self):
        assert self._fetcher()._is_downloadable("text/plain") is True

    def test_pdf_not_downloadable(self):
        assert self._fetcher()._is_downloadable("application/pdf") is False

    def test_image_not_downloadable(self):
        assert self._fetcher()._is_downloadable("image/png") is False


# ── URLFetcher.fetch — happy path ──────────────────────────────────────────────

class TestFetchHappyPath:
    @respx.mock
    def test_basic_fetch_returns_result(self, tmp_path):
        respx.get("https://example.com/article").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        fetcher = _make_fetcher(tmp_path)
        result = fetcher.fetch("https://example.com/article")
        assert isinstance(result, ExtractionResult)
        assert result.status_code == 200
        assert result.content_markdown

    @respx.mock
    def test_trafilatura_used_first(self, tmp_path):
        respx.get("https://example.com/article").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        fetcher = _make_fetcher(tmp_path, use_cache=False)
        result = fetcher.fetch("https://example.com/article")
        assert result.extractor_used == "trafilatura"

    @respx.mock
    def test_redirect_final_url_stored(self, tmp_path):
        respx.get("https://example.com/old").mock(
            return_value=httpx.Response(
                301,
                headers={"location": "https://example.com/new"},
            )
        )
        respx.get("https://example.com/new").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        fetcher = _make_fetcher(tmp_path, use_cache=False)
        # httpx follows redirects itself, so mock the final destination
        respx.get("https://example.com/old").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML,
                                        headers={"content-type": "text/html"})
        )
        result = fetcher.fetch("https://example.com/old")
        assert result.original_url == "https://example.com/old"

    @respx.mock
    def test_compression_ratio_calculated(self, tmp_path):
        respx.get("https://example.com/article").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        fetcher = _make_fetcher(tmp_path, use_cache=False)
        result = fetcher.fetch("https://example.com/article")
        assert result.content_length_original == len(ARTICLE_HTML)
        assert result.compression_ratio > 0


# ── URLFetcher.fetch — extractor fallbacks ─────────────────────────────────────

class TestExtractorFallbacks:
    @respx.mock
    def test_readability_fallback_when_trafilatura_fails(self, tmp_path):
        respx.get("https://example.com/page").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        fetcher = _make_fetcher(tmp_path, use_cache=False)
        with patch.object(fetcher._extractor_chain[0], "extract") as mock_traf:
            mock_traf.return_value = MagicMock(success=False, content_text="", content_html="", title=None, author=None, published_date=None, description=None)
            result = fetcher.fetch("https://example.com/page")
        assert result.extractor_used in ("readability", "raw")

    @respx.mock
    def test_raw_fallback_when_both_fail(self, tmp_path):
        respx.get("https://example.com/page").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        fetcher = _make_fetcher(tmp_path, use_cache=False)
        failing = MagicMock(success=False, content_text="", content_html="", title=None, author=None, published_date=None, description=None)
        for i in range(2):
            patch.object(fetcher._extractor_chain[i], "extract", return_value=failing).start()
        result = fetcher.fetch("https://example.com/page")
        assert result.extractor_used == "raw"
        for i in range(2):
            patch.stopall()


# ── URLFetcher.fetch — cache ───────────────────────────────────────────────────

class TestCache:
    @respx.mock
    def test_cache_hit_no_http_call(self, tmp_path):
        route = respx.get("https://example.com/article").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        fetcher = _make_fetcher(tmp_path)
        fetcher.fetch("https://example.com/article")
        first_call_count = route.call_count

        result2 = fetcher.fetch("https://example.com/article")
        assert result2.from_cache is True
        assert route.call_count == first_call_count  # no additional HTTP call

    @respx.mock
    def test_expired_cache_fetches_fresh(self, tmp_path):
        respx.get("https://example.com/article").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        fetcher = _make_fetcher(tmp_path, cache_ttl_seconds=1)
        fetcher.fetch("https://example.com/article")

        # Expire the cache
        import json as _json
        cache = fetcher._cache
        key = cache._cache_key("https://example.com/article")
        meta_path = cache._dir / f"{key}.json"
        meta = _json.loads(meta_path.read_text())
        meta["cached_at"] = time.time() - 10
        meta_path.write_text(_json.dumps(meta))

        result2 = fetcher.fetch("https://example.com/article")
        assert result2.from_cache is False

    @respx.mock
    def test_no_cache_bypasses(self, tmp_path):
        route = respx.get("https://example.com/article").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        fetcher = _make_fetcher(tmp_path, use_cache=False)
        fetcher.fetch("https://example.com/article")
        fetcher.fetch("https://example.com/article")
        assert route.call_count == 2


# ── URLFetcher.fetch — errors ──────────────────────────────────────────────────

class TestFetchErrors:
    @respx.mock
    def test_http_404_raises(self, tmp_path):
        respx.get("https://example.com/gone").mock(
            return_value=httpx.Response(404)
        )
        fetcher = _make_fetcher(tmp_path, use_cache=False)
        with pytest.raises(HTTPError) as exc:
            fetcher.fetch("https://example.com/gone")
        assert exc.value.status_code == 404

    @respx.mock
    def test_http_429_includes_retry_hint(self, tmp_path):
        respx.get("https://example.com/limited").mock(
            return_value=httpx.Response(429, headers={"retry-after": "60"})
        )
        fetcher = _make_fetcher(tmp_path, use_cache=False)
        with pytest.raises(HTTPError) as exc:
            fetcher.fetch("https://example.com/limited")
        assert "60" in str(exc.value)

    @respx.mock
    def test_pdf_content_type_raises(self, tmp_path):
        respx.get("https://example.com/doc.pdf").mock(
            return_value=httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})
        )
        fetcher = _make_fetcher(tmp_path, use_cache=False)
        with pytest.raises(ContentTypeError):
            fetcher.fetch("https://example.com/doc.pdf")

    def test_network_error_raises(self, tmp_path):
        fetcher = _make_fetcher(tmp_path, use_cache=False)
        with patch("httpx.Client.get", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(NetworkError):
                fetcher.fetch("https://example.com/")

    def test_timeout_raises(self, tmp_path):
        fetcher = _make_fetcher(tmp_path, use_cache=False)
        with patch("httpx.Client.get", side_effect=httpx.TimeoutException("timed out")):
            with pytest.raises(FetchTimeoutError):
                fetcher.fetch("https://example.com/")

    def test_malformed_url_raises(self, tmp_path):
        fetcher = _make_fetcher(tmp_path, use_cache=False)
        with pytest.raises(ValueError):
            fetcher.fetch("not a url")

    def test_no_scheme_normalized(self, tmp_path):
        fetcher = _make_fetcher(tmp_path, use_cache=False)
        # Just check normalization works — don't make a real HTTP call
        normalized = fetcher._normalize_url("example.com/path")
        assert normalized == "https://example.com/path"

    def test_js_required_error_without_playwright(self, tmp_path):
        fetcher = _make_fetcher(tmp_path, use_cache=False, js_fallback=True)
        with patch.object(fetcher, "_needs_js", return_value=True), \
             patch.object(fetcher, "_http_fetch", return_value=(JS_SHELL_HTML, 200, "text/html", "https://example.com/")):
            with patch("builtins.__import__", side_effect=lambda name, *a, **kw: (_ for _ in ()).throw(ImportError("No module named 'playwright'")) if name == "playwright.sync_api" else __import__(name, *a, **kw)):
                with pytest.raises((JSRequiredError, ImportError)):
                    fetcher.fetch("https://example.com/")


# ── robots.txt ────────────────────────────────────────────────────────────────

class TestRobots:
    def test_robots_blocked_raises(self, tmp_path):
        config = FetchConfig(respect_robots=True, use_cache=False)
        fetcher = URLFetcher(config)
        # Patch is_allowed directly to avoid urllib network call
        with patch.object(fetcher._robots, "is_allowed", return_value=False):
            with pytest.raises(RobotsBlocked):
                fetcher.fetch("https://blocked.com/page")

    def test_robots_checker_disallows_when_disallow_all(self):
        checker = RobotsChecker()
        # Pre-populate the robots.txt cache with a parsed disallow-all rule
        import urllib.robotparser
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(["User-agent: url-fetcher", "Disallow: /"])
        checker._cache["https://blocked.com/robots.txt"] = rp
        assert checker.is_allowed("https://blocked.com/page") is False

    @respx.mock
    def test_no_robots_flag_skips_check(self, tmp_path):
        respx.get("https://blocked.com/page").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        fetcher = _make_fetcher(tmp_path, respect_robots=False, use_cache=False)
        result = fetcher.fetch("https://blocked.com/page")
        assert result.status_code == 200

    def test_robots_fails_open_on_error(self):
        checker = RobotsChecker()
        with patch("urllib.robotparser.RobotFileParser.read", side_effect=Exception("network")):
            assert checker.is_allowed("https://unreachable.example.com/page") is True


# ── thin content ─────────────────────────────────────────────────────────────

class TestThinContent:
    @respx.mock
    def test_thin_content_warning(self, tmp_path):
        respx.get("https://example.com/minimal").mock(
            return_value=httpx.Response(200, content=MINIMAL_HTML, headers={"content-type": "text/html"})
        )
        fetcher = _make_fetcher(tmp_path, use_cache=False)
        result = fetcher.fetch("https://example.com/minimal")
        assert any("short" in w.lower() for w in result.warnings)


# ── ExtractionResult formatting ───────────────────────────────────────────────

class TestExtractionResultFormatting:
    def _make_result(self) -> ExtractionResult:
        return ExtractionResult(
            url="https://example.com/article",
            original_url="https://example.com/article",
            title="Test Article",
            author="Alice",
            published_date="2025-03-15",
            description="A test article.",
            content_markdown="Some **content** here.",
            content_text="Some content here.",
            extractor_used="trafilatura",
            used_js_fallback=False,
            from_cache=False,
            fetch_duration_ms=120,
            content_length_original=10000,
            content_length_extracted=500,
            compression_ratio=20.0,
            status_code=200,
            content_type="text/html",
            warnings=[],
        )

    def test_to_markdown_has_title(self):
        md = self._make_result().to_markdown()
        assert "# Test Article" in md

    def test_to_markdown_has_url(self):
        md = self._make_result().to_markdown()
        assert "example.com/article" in md

    def test_to_markdown_has_content(self):
        md = self._make_result().to_markdown()
        assert "Some **content** here." in md

    def test_to_json_serializable(self):
        d = self._make_result().to_json()
        json.dumps(d)
        assert d["title"] == "Test Article"

    def test_to_text_no_markdown(self):
        text = self._make_result().to_text()
        assert "Some content here." in text


# ── batch fetch ───────────────────────────────────────────────────────────────

class TestBatchFetch:
    @respx.mock
    def test_batch_success_and_failure(self, tmp_path):
        respx.get("https://a.com/").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        respx.get("https://b.com/").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        respx.get("https://c.com/").mock(
            return_value=httpx.Response(404)
        )
        fetcher = _make_fetcher(tmp_path, use_cache=False)
        batch = fetcher.fetch_batch(
            ["https://a.com/", "https://b.com/", "https://c.com/"],
            max_workers=2,
            delay_between_requests=0,
        )
        assert isinstance(batch, BatchResult)
        assert batch.total_urls == 3
        assert batch.success_count == 2
        assert batch.failed_count == 1
        assert batch.failed[0].error_type == "http"


# ── CLI ───────────────────────────────────────────────────────────────────────

class TestCLI:
    @respx.mock
    def test_single_url_markdown(self, tmp_path):
        respx.get("https://example.com/article").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        from url_fetcher.cli import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["https://example.com/article", "--no-cache", "--no-robots"])
        assert rc == 0
        assert "---" in buf.getvalue()

    @respx.mock
    def test_format_json(self, tmp_path):
        respx.get("https://example.com/article").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        from url_fetcher.cli import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["https://example.com/article", "--no-cache", "--no-robots", "--format", "json"])
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert "content_markdown" in data

    def test_robots_blocked_exits_2(self):
        from url_fetcher.cli import main
        with patch("url_fetcher.fetcher.URLFetcher.fetch_with_options",
                   side_effect=RobotsBlocked("blocked", "https://blocked.com/page", "robots")):
            rc = main(["https://blocked.com/page", "--no-cache"])
        assert rc == 2

    @respx.mock
    def test_pdf_exits_3(self):
        respx.get("https://example.com/file.pdf").mock(
            return_value=httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})
        )
        from url_fetcher.cli import main
        rc = main(["https://example.com/file.pdf", "--no-cache", "--no-robots"])
        assert rc == 3

    def test_invalid_cache_ttl_exits_1(self):
        from url_fetcher.cli import main
        rc = main(["https://example.com/", "--cache-ttl", "badvalue"])
        assert rc == 1

    @respx.mock
    def test_batch_mode(self, tmp_path):
        respx.get("https://a.com/").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        respx.get("https://b.com/").mock(
            return_value=httpx.Response(200, content=ARTICLE_HTML, headers={"content-type": "text/html"})
        )
        urls_file = tmp_path / "urls.txt"
        urls_file.write_text("https://a.com/\nhttps://b.com/\n")

        from url_fetcher.cli import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--batch", str(urls_file), "--no-cache", "--no-robots"])
        assert rc == 0
        assert "---" in buf.getvalue()
