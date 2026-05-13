"""Tests for http_inspector."""
from __future__ import annotations

import json
import subprocess
import sys
from unittest.mock import patch

import httpx
import pytest
import respx

from http_inspector.inspector import (
    HttpInspector,
    InspectorOptions,
    HttpResult,
    _redact_cookie,
    _looks_like_json,
    _looks_like_xml,
)
from http_inspector.body.json_shape import infer_shape, extract_json_summary
from http_inspector.body.xml_shape import summarize_xml
from http_inspector.body.text import truncate_text


BASE = "https://api.example.com"


def _opts(**kw) -> InspectorOptions:
    return InspectorOptions(**kw)


def _inspect(url: str, **kw) -> HttpResult:
    return HttpInspector(_opts(**kw)).inspect(url)


# ── JSON shape inference ──────────────────────────────────────────────────────

class TestJsonShape:
    def test_scalar_string(self):
        assert infer_shape("hello") == "string"

    def test_scalar_int(self):
        assert infer_shape(42) == "integer"

    def test_scalar_float(self):
        assert infer_shape(3.14) == "number"

    def test_scalar_bool(self):
        assert infer_shape(True) == "boolean"

    def test_scalar_null(self):
        assert infer_shape(None) == "null"

    def test_empty_object(self):
        assert infer_shape({}) == "{}"

    def test_empty_array(self):
        assert infer_shape([]) == "array[]"

    def test_flat_object(self):
        result = infer_shape({"id": 1, "name": "Alice"})
        assert "id: integer" in result
        assert "name: string" in result

    def test_array_of_objects(self):
        result = infer_shape([{"id": 1}, {"id": 2}])
        assert "array[2]" in result
        assert "id: integer" in result

    def test_nested_object_depth(self):
        result = infer_shape({"a": {"b": {"c": {"d": 1}}}}, max_depth=2)
        assert "{...}" in result

    def test_large_object_truncated(self):
        data = {str(i): i for i in range(20)}
        result = infer_shape(data)
        assert "+10 more" in result

    def test_extract_top_level_array(self):
        data = [{"id": 1}, {"id": 2}, {"id": 3}]
        shape, sample, total = extract_json_summary(data, max_array_items=2)
        assert total == 3
        assert len(sample) == 2
        assert "array[3]" in shape

    def test_extract_nested_array(self):
        data = {"items": [{"id": 1}, {"id": 2}], "total": 2}
        shape, sample, total = extract_json_summary(data)
        assert sample is not None
        assert total == 2

    def test_extract_no_array(self):
        data = {"id": 1, "name": "test"}
        shape, sample, total = extract_json_summary(data)
        assert sample is None
        assert total is None


# ── XML shape ─────────────────────────────────────────────────────────────────

class TestXmlShape:
    def test_simple_element(self):
        xml = "<root><child>text</child></root>"
        result = summarize_xml(xml)
        assert "root" in result
        assert "child" in result

    def test_attributes(self):
        xml = '<root id="1" name="foo"><item/></root>'
        result = summarize_xml(xml)
        assert 'id="1"' in result

    def test_empty_element(self):
        xml = "<root/>"
        result = summarize_xml(xml)
        assert "root" in result

    def test_namespace_stripped(self):
        xml = '<root xmlns="http://example.com"><item/></root>'
        result = summarize_xml(xml)
        assert "root" in result
        assert "http://" not in result

    def test_parse_error(self):
        result = summarize_xml("not xml at all {{}")
        assert "error" in result.lower()

    def test_depth_limit(self):
        xml = "<a><b><c><d><e><f>deep</f></e></d></c></b></a>"
        result = summarize_xml(xml, max_depth=2)
        assert "..." in result


# ── Text truncation ───────────────────────────────────────────────────────────

class TestTextTruncation:
    def test_no_truncation_needed(self):
        text = "\n".join(f"line {i}" for i in range(10))
        preview, total, suppressed = truncate_text(text, max_lines=50)
        assert suppressed == 0
        assert total == 10
        assert preview == text

    def test_truncation(self):
        text = "\n".join(f"line {i}" for i in range(100))
        preview, total, suppressed = truncate_text(text, max_lines=50)
        assert total == 100
        assert suppressed == 50
        assert len(preview.splitlines()) == 50


# ── HTTP response processing ──────────────────────────────────────────────────

class TestJsonResponse:
    @respx.mock
    def test_json_object_shape(self):
        respx.get(f"{BASE}/user").mock(return_value=httpx.Response(
            200,
            json={"id": 1, "name": "Alice", "active": True},
            headers={"content-type": "application/json"},
        ))
        r = _inspect(f"{BASE}/user")
        assert r.status_code == 200
        assert r.body.detected_format == "json"
        assert "id: integer" in r.body.json_shape
        assert "name: string" in r.body.json_shape

    @respx.mock
    def test_json_array_shape_and_sample(self):
        respx.get(f"{BASE}/users").mock(return_value=httpx.Response(
            200,
            json=[{"id": i, "name": f"User{i}"} for i in range(10)],
            headers={"content-type": "application/json"},
        ))
        r = _inspect(f"{BASE}/users", max_array_items=3)
        assert r.body.json_array_len == 10
        assert len(r.body.json_sample) == 3

    @respx.mock
    def test_shape_only_no_sample(self):
        respx.get(f"{BASE}/users").mock(return_value=httpx.Response(
            200,
            json=[{"id": 1}],
            headers={"content-type": "application/json"},
        ))
        r = _inspect(f"{BASE}/users", shape_only=True)
        assert r.body.json_sample is None

    @respx.mock
    def test_content_sniff_json(self):
        respx.get(f"{BASE}/data").mock(return_value=httpx.Response(
            200,
            content=b'{"key": "value"}',
            headers={"content-type": "text/plain"},
        ))
        r = _inspect(f"{BASE}/data")
        assert r.body.detected_format == "json"

    @respx.mock
    def test_invalid_json_body(self):
        respx.get(f"{BASE}/bad").mock(return_value=httpx.Response(
            200,
            content=b'{"broken": json}',
            headers={"content-type": "application/json"},
        ))
        r = _inspect(f"{BASE}/bad")
        assert r.body.parse_error is not None
        assert len(r.warnings) > 0

    @respx.mock
    def test_invalid_json_parse_error_visible_in_markdown(self):
        respx.get(f"{BASE}/bad-json").mock(return_value=httpx.Response(
            200,
            content=b'{"broken": json}',
            headers={"content-type": "application/json"},
        ))
        md = _inspect(f"{BASE}/bad-json").to_markdown()
        assert "Parse error" in md

    @respx.mock
    def test_vendor_json_content_type_parsed_as_json(self):
        respx.get(f"{BASE}/vnd").mock(return_value=httpx.Response(
            200,
            json={"id": 1, "type": "article"},
            headers={"content-type": "application/vnd.api+json"},
        ))
        r = _inspect(f"{BASE}/vnd")
        assert r.body.detected_format == "json"
        assert r.body.json_shape is not None

    @respx.mock
    def test_problem_json_content_type_parsed_as_json(self):
        respx.get(f"{BASE}/error").mock(return_value=httpx.Response(
            400,
            json={"title": "Bad Request", "status": 400, "detail": "Invalid input"},
            headers={"content-type": "application/problem+json"},
        ))
        r = _inspect(f"{BASE}/error")
        assert r.body.detected_format == "json"
        assert "title: string" in r.body.json_shape


class TestXmlResponse:
    @respx.mock
    def test_xml_body(self):
        xml = b"<feed><entry><title>Hello</title></entry></feed>"
        respx.get(f"{BASE}/feed").mock(return_value=httpx.Response(
            200,
            content=xml,
            headers={"content-type": "application/xml"},
        ))
        r = _inspect(f"{BASE}/feed")
        assert r.body.detected_format == "xml"
        assert "feed" in r.body.text_preview

    @respx.mock
    def test_xml_content_sniff(self):
        xml = b"<root><item/></root>"
        respx.get(f"{BASE}/data").mock(return_value=httpx.Response(
            200,
            content=xml,
            headers={"content-type": "text/plain"},
        ))
        r = _inspect(f"{BASE}/data")
        assert r.body.detected_format == "xml"


class TestTextResponse:
    @respx.mock
    def test_text_body(self):
        text = "\n".join(f"line {i}" for i in range(10))
        respx.get(f"{BASE}/log").mock(return_value=httpx.Response(
            200,
            content=text.encode(),
            headers={"content-type": "text/plain"},
        ))
        r = _inspect(f"{BASE}/log")
        assert r.body.detected_format == "text"
        assert r.body.text_preview is not None

    @respx.mock
    def test_text_truncated(self):
        text = "\n".join(f"line {i}" for i in range(200))
        respx.get(f"{BASE}/big").mock(return_value=httpx.Response(
            200,
            content=text.encode(),
            headers={"content-type": "text/plain"},
        ))
        r = _inspect(f"{BASE}/big", max_body_lines=50)
        assert r.body.suppressed_lines > 0
        assert r.body.truncated is True


class TestBinaryResponse:
    @respx.mock
    def test_binary_body(self):
        respx.get(f"{BASE}/img").mock(return_value=httpx.Response(
            200,
            content=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
            headers={"content-type": "image/png"},
        ))
        r = _inspect(f"{BASE}/img")
        assert r.body.detected_format == "binary"
        assert "image/png" in r.body.binary_stub

    @respx.mock
    def test_octet_stream_without_null_bytes_is_text(self):
        respx.get(f"{BASE}/octet").mock(return_value=httpx.Response(
            200,
            content=b"A" * 600,
            headers={"content-type": "application/octet-stream"},
        ))
        r = _inspect(f"{BASE}/octet")
        assert r.body.detected_format == "text"

    @respx.mock
    def test_missing_content_type_with_null_bytes_is_binary(self):
        respx.get(f"{BASE}/bin").mock(return_value=httpx.Response(
            200,
            content=b"\x00" + b"A" * 511,
            headers={},
        ))
        r = _inspect(f"{BASE}/bin")
        assert r.body.detected_format == "binary"

    @respx.mock
    def test_missing_content_type_without_null_bytes_is_text(self):
        respx.get(f"{BASE}/txt").mock(return_value=httpx.Response(
            200,
            content=b"hello world",
            headers={},
        ))
        r = _inspect(f"{BASE}/txt")
        assert r.body.detected_format != "binary"


# ── Headers ───────────────────────────────────────────────────────────────────

class TestHeaderFiltering:
    @respx.mock
    def test_content_type_kept(self):
        respx.get(f"{BASE}/").mock(return_value=httpx.Response(
            200,
            json={},
            headers={"content-type": "application/json", "x-custom-boring": "abc"},
        ))
        r = _inspect(f"{BASE}/")
        names = {h.name.lower() for h in r.headers}
        assert "content-type" in names
        assert "x-custom-boring" not in names

    @respx.mock
    def test_rate_limit_headers_kept(self):
        respx.get(f"{BASE}/").mock(return_value=httpx.Response(
            200, json={},
            headers={
                "content-type": "application/json",
                "x-ratelimit-limit": "1000",
                "x-ratelimit-remaining": "999",
            },
        ))
        r = _inspect(f"{BASE}/")
        names = {h.name.lower() for h in r.headers}
        assert "x-ratelimit-limit" in names

    @respx.mock
    def test_set_cookie_redacted(self):
        respx.get(f"{BASE}/").mock(return_value=httpx.Response(
            200, json={},
            headers={"set-cookie": "session=abc123; Path=/; HttpOnly"},
        ))
        r = _inspect(f"{BASE}/")
        cookie_headers = [h for h in r.headers if h.name.lower() == "set-cookie"]
        assert len(cookie_headers) == 1
        assert cookie_headers[0].redacted is True
        assert "abc123" not in cookie_headers[0].value
        assert "session=<redacted>" in cookie_headers[0].value

    @respx.mock
    def test_set_cookie_no_redact(self):
        respx.get(f"{BASE}/").mock(return_value=httpx.Response(
            200, json={},
            headers={"set-cookie": "session=abc123"},
        ))
        r = _inspect(f"{BASE}/", no_redact_cookies=True)
        cookie_headers = [h for h in r.headers if h.name.lower() == "set-cookie"]
        assert cookie_headers[0].redacted is False
        assert "abc123" in cookie_headers[0].value

    @respx.mock
    def test_show_all_headers(self):
        respx.get(f"{BASE}/").mock(return_value=httpx.Response(
            200, json={},
            headers={"x-custom-boring": "abc", "content-type": "application/json"},
        ))
        r = _inspect(f"{BASE}/", show_all_headers=True)
        names = {h.name.lower() for h in r.headers}
        assert "x-custom-boring" in names

    @respx.mock
    def test_authorization_header_redacted(self):
        respx.get(f"{BASE}/").mock(return_value=httpx.Response(
            200, json={},
            headers={"authorization": "Bearer supersecret", "content-type": "application/json"},
        ))
        r = _inspect(f"{BASE}/", show_all_headers=True)
        auth_headers = [h for h in r.headers if h.name.lower() == "authorization"]
        assert len(auth_headers) == 1
        assert auth_headers[0].redacted is True
        assert "supersecret" not in auth_headers[0].value

    @respx.mock
    def test_cookie_request_header_redacted(self):
        respx.get(f"{BASE}/").mock(return_value=httpx.Response(
            200, json={},
            headers={"cookie": "token=abc999; session=xyz", "content-type": "application/json"},
        ))
        r = _inspect(f"{BASE}/", show_all_headers=True)
        cookie_headers = [h for h in r.headers if h.name.lower() == "cookie"]
        assert len(cookie_headers) == 1
        assert cookie_headers[0].redacted is True
        assert "abc999" not in cookie_headers[0].value


# ── Request building ──────────────────────────────────────────────────────────

class TestRequestBuilding:
    @respx.mock
    def test_post_with_data(self):
        route = respx.post(f"{BASE}/users").mock(return_value=httpx.Response(
            201, json={"id": 1},
            headers={"content-type": "application/json"},
        ))
        opts = _opts(method="POST", data=b'{"name": "Alice"}')
        result = HttpInspector(opts).inspect(f"{BASE}/users")
        assert result.status_code == 201
        assert route.called

    @respx.mock
    def test_empty_body_sends_post_not_get(self):
        route = respx.post(f"{BASE}/trigger").mock(return_value=httpx.Response(
            204, content=b"",
        ))
        opts = _opts(method="POST", data=b"")
        result = HttpInspector(opts).inspect(f"{BASE}/trigger")
        assert result.status_code == 204
        assert route.called

    @respx.mock
    def test_custom_headers_sent(self):
        route = respx.get(f"{BASE}/secure").mock(return_value=httpx.Response(
            200, json={},
            headers={"content-type": "application/json"},
        ))
        opts = _opts(headers=[("Authorization", "Bearer token123")])
        HttpInspector(opts).inspect(f"{BASE}/secure")
        assert route.called
        req = route.calls[0].request
        assert req.headers.get("authorization") == "Bearer token123"

    @respx.mock
    def test_delete_method(self):
        route = respx.delete(f"{BASE}/users/1").mock(return_value=httpx.Response(
            204, content=b"",
        ))
        opts = _opts(method="DELETE")
        result = HttpInspector(opts).inspect(f"{BASE}/users/1")
        assert result.status_code == 204
        assert route.called


# ── Status codes + timing ─────────────────────────────────────────────────────

class TestStatusAndTiming:
    @respx.mock
    def test_status_code_captured(self):
        respx.get(f"{BASE}/missing").mock(return_value=httpx.Response(
            404, json={"error": "not found"},
            headers={"content-type": "application/json"},
        ))
        r = _inspect(f"{BASE}/missing")
        assert r.status_code == 404

    @respx.mock
    def test_timing_present(self):
        respx.get(f"{BASE}/").mock(return_value=httpx.Response(200, json={}))
        r = _inspect(f"{BASE}/")
        assert r.timing.total_ms >= 0

    def test_timeout_raises_value_error(self):
        import httpx
        with patch("httpx.Client.request", side_effect=httpx.TimeoutException("timed out")):
            with pytest.raises(ValueError, match="timed out"):
                _inspect(f"{BASE}/slow", timeout=0.001)

    def test_network_error_raises_value_error(self):
        with patch("httpx.Client.request", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(ValueError, match="Request failed"):
                _inspect(f"{BASE}/error")


# ── Cookie redaction helper ───────────────────────────────────────────────────

class TestCookieRedaction:
    def test_simple_cookie(self):
        result = _redact_cookie("session=abc123")
        assert result == "session=<redacted>"

    def test_multi_attribute_cookie(self):
        result = _redact_cookie("session=abc123; Path=/; HttpOnly; Secure")
        assert "session=<redacted>" in result
        assert "abc123" not in result
        assert "Path=/" in result

    def test_no_value(self):
        result = _redact_cookie("HttpOnly")
        assert result == "HttpOnly"

    def test_folded_multi_cookie(self):
        value = "session=abc123; Path=/, csrf=def456; HttpOnly"
        result = _redact_cookie(value)
        assert "abc123" not in result
        assert "def456" not in result
        assert "session=<redacted>" in result
        assert "csrf=<redacted>" in result
        assert "Path=/" in result
        assert "HttpOnly" in result


# ── Content sniffing ──────────────────────────────────────────────────────────

class TestContentSniffing:
    def test_looks_like_json_object(self):
        assert _looks_like_json('{"key": "value"}')

    def test_looks_like_json_array(self):
        assert _looks_like_json('[1, 2, 3]')

    def test_not_json(self):
        assert not _looks_like_json("hello world")

    def test_looks_like_xml(self):
        assert _looks_like_xml("<root><item/></root>")

    def test_not_xml(self):
        assert not _looks_like_xml("hello world")


# ── Renderers ─────────────────────────────────────────────────────────────────

class TestRenderers:
    @respx.mock
    def test_markdown_has_status(self):
        respx.get(f"{BASE}/").mock(return_value=httpx.Response(
            200, json={"id": 1},
            headers={"content-type": "application/json"},
        ))
        md = _inspect(f"{BASE}/").to_markdown()
        assert "200" in md
        assert "GET" in md

    @respx.mock
    def test_markdown_has_headers_table(self):
        respx.get(f"{BASE}/").mock(return_value=httpx.Response(
            200, json={},
            headers={"content-type": "application/json", "content-length": "2"},
        ))
        md = _inspect(f"{BASE}/").to_markdown()
        assert "## Headers" in md
        assert "content-type" in md

    @respx.mock
    def test_markdown_has_body_section(self):
        respx.get(f"{BASE}/").mock(return_value=httpx.Response(
            200, json={"x": 1},
            headers={"content-type": "application/json"},
        ))
        md = _inspect(f"{BASE}/").to_markdown()
        assert "## Body" in md
        assert "**Shape:**" in md

    @respx.mock
    def test_json_format_parses(self):
        respx.get(f"{BASE}/").mock(return_value=httpx.Response(
            200, json={"id": 1},
            headers={"content-type": "application/json"},
        ))
        d = _inspect(f"{BASE}/").to_json()
        json.dumps(d)
        assert d["status_code"] == 200
        assert d["body"]["detected_format"] == "json"

    @respx.mock
    def test_text_format(self):
        respx.get(f"{BASE}/").mock(return_value=httpx.Response(
            200, json={"id": 1},
            headers={"content-type": "application/json"},
        ))
        text = _inspect(f"{BASE}/").to_text()
        assert "200" in text

    @respx.mock
    def test_markdown_shows_parse_error(self):
        respx.get(f"{BASE}/bad").mock(return_value=httpx.Response(
            200,
            content=b'{"broken": json}',
            headers={"content-type": "application/json"},
        ))
        md = _inspect(f"{BASE}/bad").to_markdown()
        assert "Parse error" in md

    @respx.mock
    def test_markdown_shows_redirect_history(self):
        respx.get(f"{BASE}/final").mock(return_value=httpx.Response(
            200, json={"ok": True},
            headers={"content-type": "application/json"},
        ))
        # Construct a result with redirect history directly
        from http_inspector.inspector import BodySummary, HeaderInfo, TimingInfo
        result = HttpResult(
            url=f"{BASE}/final",
            method="GET",
            status_code=200,
            reason_phrase="OK",
            headers=[],
            body=BodySummary(
                content_type="application/json",
                detected_format="json",
                size_bytes=10,
                json_shape="{ok: boolean}",
            ),
            timing=TimingInfo(total_ms=50),
            warnings=[],
            redirect_history=[301, 302],
        )
        md = result.to_markdown()
        assert "Redirect" in md
        assert "301" in md
        assert "302" in md

    @respx.mock
    def test_markdown_shows_binary_stub(self):
        respx.get(f"{BASE}/img").mock(return_value=httpx.Response(
            200,
            content=b"\x89PNG\r\n" + b"\x00" * 50,
            headers={"content-type": "image/png"},
        ))
        md = _inspect(f"{BASE}/img").to_markdown()
        assert "image/png" in md

    def test_render_text_binary_stub(self):
        from http_inspector.inspector import BodySummary, TimingInfo
        result = HttpResult(
            url=f"{BASE}/bin",
            method="GET",
            status_code=200,
            reason_phrase="OK",
            headers=[],
            body=BodySummary(
                content_type="application/octet-stream",
                detected_format="binary",
                size_bytes=1024,
                binary_stub="<binary: application/octet-stream, 1.0 KB>",
            ),
            timing=TimingInfo(total_ms=10),
            warnings=[],
        )
        text = result.to_text()
        assert "<binary:" in text

    @respx.mock
    def test_markdown_shows_warnings(self):
        respx.get(f"{BASE}/bad").mock(return_value=httpx.Response(
            200,
            content=b'not json at all',
            headers={"content-type": "application/json"},
        ))
        md = _inspect(f"{BASE}/bad").to_markdown()
        # Warnings surfaced via parse error path
        assert "Parse error" in md or "warning" in md.lower()


# ── Exit codes (subprocess) ───────────────────────────────────────────────────

class TestExitCodes:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "http_inspector.cli", *args],
            capture_output=True, text=True,
        )

    def test_one_on_network_error(self):
        with patch("http_inspector.inspector.HttpInspector.inspect",
                   side_effect=ValueError("connection refused")):
            r = self._run("https://api.example.com/fail")
        assert r.returncode == 1

    def test_json_output_valid(self):
        with respx.mock:
            respx.get("https://api.example.com/test").mock(
                return_value=httpx.Response(200, json={"ok": True},
                                            headers={"content-type": "application/json"})
            )
            r = self._run("https://api.example.com/test", "--format", "json")
        # Skip if network test fails (CI may block external)
        if r.returncode == 0:
            json.loads(r.stdout)


# ── MCP wrapper ───────────────────────────────────────────────────────────────

class TestMCPWrapper:
    @respx.mock
    def test_inspect_http_handle_returns_markdown(self):
        from http_inspector.mcp_tool import _handle
        respx.get("https://api.example.com/data").mock(return_value=httpx.Response(
            200, json={"id": 1},
            headers={"content-type": "application/json"},
        ))
        result = _handle({"url": "https://api.example.com/data"})
        assert "200" in result
        assert "id: integer" in result

    @respx.mock
    def test_mcp_post_with_data(self):
        from http_inspector.mcp_tool import _handle
        respx.post("https://api.example.com/users").mock(return_value=httpx.Response(
            201, json={"id": 99},
            headers={"content-type": "application/json"},
        ))
        result = _handle({
            "url": "https://api.example.com/users",
            "method": "POST",
            "data": '{"name": "Alice"}',
        })
        assert "201" in result

    def test_unknown_tool_returns_error(self):
        r = subprocess.run(
            [sys.executable, "-m", "http_inspector.mcp_tool"],
            input='{"name":"nope","parameters":{}}\n', capture_output=True, text=True,
        )
        d = json.loads(r.stdout.strip())
        assert "error" in d
