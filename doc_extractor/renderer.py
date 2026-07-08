from __future__ import annotations

from .extractor import DocResult


class Renderer:
    def render_markdown(self, r: DocResult) -> str:
        lines: list[str] = [f"# Document: {r.source}", ""]
        meta = f"**Format:** {r.doc_format}  |  **Chars:** {r.char_count:,}"
        if r.title:
            meta = f"**Title:** {r.title}  |  " + meta
        lines += [meta, ""]
        for w in r.warnings:
            lines.append(f"> ⚠ {w}")
        if r.warnings:
            lines.append("")
        lines += ["---", "", r.markdown]
        return "\n".join(lines)

    def render_json(self, r: DocResult) -> dict:
        return {
            "source": r.source,
            "doc_format": r.doc_format,
            "title": r.title,
            "char_count": r.char_count,
            "truncated": r.truncated,
            "parse_duration_ms": r.parse_duration_ms,
            "warnings": r.warnings,
            "markdown": r.markdown,
        }

    def render_text(self, r: DocResult) -> str:
        return r.markdown
