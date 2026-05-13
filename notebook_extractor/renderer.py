from __future__ import annotations

from .extractor import CellOutput, NotebookCell, NotebookResult


class Renderer:
    def render_markdown(self, r: NotebookResult) -> str:
        lines: list[str] = []

        # Header
        lines.append(f"# Notebook: {r.source}")
        lines.append("")
        code_count = sum(1 for c in r.cells if c.cell_type == "code")
        md_count = sum(1 for c in r.cells if c.cell_type == "markdown")
        lang = r.language or r.kernel_name or "unknown"
        lines.append(
            f"**Language:** {lang}  |  "
            f"**Cells:** {r.total_cells} (code: {code_count}, markdown: {md_count})  |  "
            f"**Showing:** {r.shown_cells}"
        )
        lines.append("")
        excluded = r.total_cells - r.shown_cells
        if excluded:
            lines.append(f"> _{excluded} cell{'s' if excluded != 1 else ''} excluded by filters_")
            lines.append("")
        for w in r.warnings:
            lines.append(f"> {w}")
        if r.warnings:
            lines.append("")

        for cell in r.cells:
            lines.extend(self._render_cell(cell))

        return "\n".join(lines).rstrip() + "\n"

    def _render_cell(self, cell: NotebookCell) -> list[str]:
        lines: list[str] = ["---", ""]

        # Cell header
        ec = f"  _In [{cell.execution_count}]_" if cell.execution_count is not None else ""
        lines.append(f"**[{cell.cell_type}]**{ec}")
        lines.append("")

        if cell.source.strip():
            if cell.cell_type == "code":
                lines.append("```python")
                lines.append(cell.source)
                lines.append("```")
            else:
                lines.append(cell.source)
            lines.append("")

        for out in cell.outputs:
            lines.extend(self._render_output(out))

        return lines

    def _render_output(self, out: CellOutput) -> list[str]:
        lines: list[str] = []
        if out.image_stub:
            lines.append(f"**Output:** `{out.image_stub}`")
            lines.append("")
            return lines

        if out.output_type == "error":
            lines.append("**Error:**")
            lines.append("```")
            lines.append(out.text or "")
            lines.append("```")
            if out.truncated:
                lines.append("> _traceback truncated_")
            lines.append("")
            return lines

        if out.text:
            label = "**Output (stream):**" if out.output_type == "stream" else "**Output:**"
            meta_parts = []
            if out.suppressed_lines:
                total = (out.text.count("\n") + 1) + out.suppressed_lines
                meta_parts.append(f"{total} lines → {out.text.count(chr(10)) + 1} shown, {out.suppressed_lines} suppressed")
            if out.truncated and not out.suppressed_lines:
                shown = out.text.count("\n") + 1
                meta_parts.append(f"truncated to {shown} lines")
            if meta_parts:
                lines.append(f"{label} _({'; '.join(meta_parts)})_")
            else:
                lines.append(label)
            lines.append("```")
            lines.append(out.text)
            lines.append("```")
            lines.append("")
        return lines

    def render_json(self, r: NotebookResult) -> dict:
        def _out(o: CellOutput) -> dict:
            return {
                "output_type": o.output_type,
                "text": o.text,
                "image_stub": o.image_stub,
                "truncated": o.truncated,
                "suppressed_lines": o.suppressed_lines,
            }

        def _cell(c: NotebookCell) -> dict:
            return {
                "index": c.index,
                "cell_type": c.cell_type,
                "source": c.source,
                "execution_count": c.execution_count,
                "tags": c.tags,
                "outputs": [_out(o) for o in c.outputs],
            }

        return {
            "source": r.source,
            "kernel_name": r.kernel_name,
            "language": r.language,
            "total_cells": r.total_cells,
            "shown_cells": r.shown_cells,
            "parse_duration_ms": r.parse_duration_ms,
            "warnings": r.warnings,
            "cells": [_cell(c) for c in r.cells],
        }

    def render_text(self, r: NotebookResult) -> str:
        parts: list[str] = []
        for c in r.cells:
            if c.source.strip():
                parts.append(c.source)
        return "\n\n".join(parts)
