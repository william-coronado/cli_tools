from __future__ import annotations

import json

from .inspector import BodySummary, HeaderInfo, HttpResult


class Renderer:
    def render_markdown(self, r: HttpResult) -> str:
        lines: list[str] = []

        reason = f" {r.reason_phrase}" if r.reason_phrase else ""
        lines.append(f"# HTTP {r.method} {r.url}")
        lines.append("")

        timing = f"{r.timing.elapsed_ms}ms" if r.timing.elapsed_ms is not None else f"{r.timing.total_ms}ms"
        lines.append(f"**Status:** {r.status_code}{reason}  |  **Timing:** {timing}")

        if r.redirect_history:
            hops = " → ".join(str(s) for s in r.redirect_history) + f" → {r.status_code}"
            lines.append(f"**Redirects:** {hops}")

        for w in r.warnings:
            lines.append(f"> {w}")
        lines.append("")

        # Headers
        if r.headers:
            lines.append("## Headers")
            lines.append("")
            lines.append("| Name | Value |")
            lines.append("|------|-------|")
            for h in r.headers:
                val = h.value.replace("|", "\\|")
                redacted_note = " _(redacted)_" if h.redacted else ""
                lines.append(f"| `{h.name}` | {val}{redacted_note} |")
            lines.append("")

        # Body
        b = r.body
        size_str = _fmt_size(b.size_bytes)
        lines.append(f"## Body ({b.content_type or 'unknown'}, {size_str})")
        lines.append("")

        if b.detected_format == "binary":
            lines.append(f"`{b.binary_stub}`")

        elif b.detected_format == "json":
            if b.parse_error:
                lines.append(f"> Parse error: {b.parse_error}")
                lines.append("")
                if b.text_preview:
                    lines.append("```")
                    lines.append(b.text_preview)
                    lines.append("```")
            else:
                lines.append(f"**Shape:** `{b.json_shape}`")
                if b.json_array_len is not None:
                    lines.append(f"**Array length:** {b.json_array_len} items")
                lines.append("")
                if b.json_sample:
                    lines.append(f"**Sample ({len(b.json_sample)} item{'s' if len(b.json_sample) != 1 else ''}):**")
                    lines.append("```json")
                    lines.append(json.dumps(b.json_sample, indent=2, default=str))
                    lines.append("```")

        elif b.detected_format == "xml":
            lines.append("**Structure:**")
            lines.append("```")
            lines.append(b.text_preview or "")
            lines.append("```")

        elif b.detected_format == "html":
            if b.html_title:
                lines.append(f"**Title:** {b.html_title}")
                lines.append("")
            if b.suppressed_lines:
                lines.append(f"_Showing first {b.total_lines - b.suppressed_lines} of {b.total_lines} lines_")
                lines.append("")
            if b.text_preview:
                lines.append("```markdown")
                lines.append(b.text_preview)
                lines.append("```")

        else:  # text
            if b.suppressed_lines:
                lines.append(f"_Showing first {b.total_lines - b.suppressed_lines} of {b.total_lines} lines_")
                lines.append("")
            if b.text_preview:
                lines.append("```")
                lines.append(b.text_preview)
                lines.append("```")

        return "\n".join(lines).rstrip() + "\n"

    def render_json(self, r: HttpResult) -> dict:
        def _h(h: HeaderInfo) -> dict:
            return {"name": h.name, "value": h.value, "redacted": h.redacted}

        def _b(b: BodySummary) -> dict:
            return {
                "content_type": b.content_type,
                "detected_format": b.detected_format,
                "size_bytes": b.size_bytes,
                "json_shape": b.json_shape,
                "json_sample": b.json_sample,
                "json_array_len": b.json_array_len,
                "html_title": b.html_title,
                "text_preview": b.text_preview,
                "total_lines": b.total_lines,
                "suppressed_lines": b.suppressed_lines,
                "truncated": b.truncated,
                "binary_stub": b.binary_stub,
                "parse_error": b.parse_error,
            }

        return {
            "url": r.url,
            "method": r.method,
            "status_code": r.status_code,
            "reason_phrase": r.reason_phrase,
            "redirect_history": r.redirect_history,
            "timing": {
                "total_ms": r.timing.total_ms,
                "elapsed_ms": r.timing.elapsed_ms,
            },
            "warnings": r.warnings,
            "headers": [_h(h) for h in r.headers],
            "body": _b(r.body),
        }

    def render_text(self, r: HttpResult) -> str:
        parts = [f"{r.status_code} {r.url}"]
        b = r.body
        if b.json_shape:
            parts.append(f"shape: {b.json_shape}")
        elif b.text_preview:
            parts.append(b.text_preview)
        elif b.binary_stub:
            parts.append(b.binary_stub)
        return "\n".join(parts)


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"
