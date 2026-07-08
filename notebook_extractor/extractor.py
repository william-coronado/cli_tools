from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CellOutput:
    output_type: str            # stream | display_data | execute_result | error
    text: str | None            # extracted text (already truncated)
    image_stub: str | None      # e.g. "<image: png 800×600, 12.3 KB>"
    truncated: bool = False
    suppressed_lines: int = 0


@dataclass
class NotebookCell:
    index: int
    cell_type: str              # code | markdown | raw
    source: str
    outputs: list[CellOutput] = field(default_factory=list)
    execution_count: int | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class NotebookResult:
    source: str
    kernel_name: str | None
    language: str | None
    total_cells: int
    shown_cells: int
    cells: list[NotebookCell]
    warnings: list[str]
    parse_duration_ms: int

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
class ExtractorOptions:
    # Cell filtering
    cells_slice: slice | None = None
    code_only: bool = False
    markdown_only: bool = False
    tags: list[str] | None = None
    # Output handling
    no_outputs: bool = False
    max_output_lines: int = 30
    no_dedup: bool = False


class NotebookExtractor:
    def __init__(self, options: ExtractorOptions | None = None) -> None:
        self.options = options or ExtractorOptions()

    def extract(self, path: str | Path) -> NotebookResult:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if path.suffix.lower() != ".ipynb":
            raise ValueError(f"Not a Jupyter notebook: {path}")

        t0 = time.monotonic()
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid notebook JSON: {e}")

        kernel_name = (
            data.get("metadata", {}).get("kernelspec", {}).get("display_name")
            or data.get("metadata", {}).get("kernelspec", {}).get("name")
        )
        language = (
            data.get("metadata", {}).get("kernelspec", {}).get("language")
            or data.get("metadata", {}).get("language_info", {}).get("name")
        )

        all_cells = data.get("cells", [])
        total_cells = len(all_cells)
        warnings: list[str] = []

        opts = self.options
        indexed_cells: list[tuple[int, dict]] = list(enumerate(all_cells))
        if opts.cells_slice is not None:
            indexed_cells = indexed_cells[opts.cells_slice]

        cells: list[NotebookCell] = []
        for original_index, raw in indexed_cells:
            cell_type = raw.get("cell_type", "raw")
            # Type filter
            if opts.code_only and cell_type != "code":
                continue
            if opts.markdown_only and cell_type not in ("markdown", "raw"):
                continue
            # Tag filter
            cell_tags = raw.get("metadata", {}).get("tags", []) or []
            if opts.tags:
                if not any(t in cell_tags for t in opts.tags):
                    continue

            source = _join_source(raw.get("source", []))
            outputs: list[CellOutput] = []
            if cell_type == "code" and not opts.no_outputs:
                for out in raw.get("outputs", []):
                    co = self._process_output(out)
                    if co is not None:
                        outputs.append(co)

            cells.append(NotebookCell(
                index=original_index,
                cell_type=cell_type,
                source=source,
                outputs=outputs,
                execution_count=raw.get("execution_count"),
                tags=list(cell_tags),
            ))

        return NotebookResult(
            source=str(path),
            kernel_name=kernel_name,
            language=language,
            total_cells=total_cells,
            shown_cells=len(cells),
            cells=cells,
            warnings=warnings,
            parse_duration_ms=int((time.monotonic() - t0) * 1000),
        )

    def _process_output(self, out: dict) -> CellOutput | None:
        out_type = out.get("output_type", "")
        opts = self.options

        if out_type == "stream":
            text = _join_source(out.get("text", []))
            if not opts.no_dedup:
                from .dedup import dedup_stream
                text, suppressed = dedup_stream(text)
            else:
                suppressed = 0
            lines = text.splitlines()
            truncated = len(lines) > opts.max_output_lines
            shown = "\n".join(lines[:opts.max_output_lines])
            return CellOutput(
                output_type="stream",
                text=shown,
                image_stub=None,
                truncated=truncated,
                suppressed_lines=suppressed,
            )

        if out_type in ("display_data", "execute_result"):
            data = out.get("data", {})
            # Check for image first
            for mime in ("image/png", "image/jpeg", "image/gif", "image/svg+xml"):
                if mime in data:
                    raw_b64 = data[mime]
                    if isinstance(raw_b64, list):
                        raw_b64 = "".join(raw_b64)
                    stub = _image_stub(mime, raw_b64)
                    return CellOutput(output_type=out_type, text=None, image_stub=stub)
            # HTML-only outputs (no text/plain fallback, e.g. styled tables):
            # convert to markdown when a converter is available, else stub.
            if "text/html" in data and "text/plain" not in data:
                html = _join_source(data.get("text/html", []))
                converted = _html_to_markdown(html)
                if converted is None:
                    return CellOutput(
                        output_type=out_type,
                        text="<HTML output>",
                        image_stub=None,
                    )
                lines = converted.splitlines()
                truncated = len(lines) > opts.max_output_lines
                return CellOutput(
                    output_type=out_type,
                    text="\n".join(lines[:opts.max_output_lines]),
                    image_stub=None,
                    truncated=truncated,
                )
            # Plain text
            plain = data.get("text/plain", [])
            text = _join_source(plain)
            lines = text.splitlines()
            truncated = len(lines) > opts.max_output_lines
            shown = "\n".join(lines[:opts.max_output_lines])
            return CellOutput(
                output_type=out_type,
                text=shown or None,
                image_stub=None,
                truncated=truncated,
            )

        if out_type == "error":
            ename = out.get("ename", "Error")
            evalue = out.get("evalue", "")
            traceback = out.get("traceback", [])
            # Strip ANSI codes from traceback
            import re
            ansi = re.compile(r"\x1b\[[0-9;]*m")
            tb_clean = [ansi.sub("", line) for line in traceback]
            tb_lines = tb_clean[:opts.max_output_lines]
            truncated = len(tb_clean) > opts.max_output_lines
            return CellOutput(
                output_type="error",
                text=f"{ename}: {evalue}\n" + "\n".join(tb_lines),
                image_stub=None,
                truncated=truncated,
            )

        return None


def _join_source(src) -> str:
    if isinstance(src, list):
        return "".join(src)
    return str(src) if src else ""


def _html_to_markdown(html: str) -> str | None:
    """Convert an HTML-only cell output to markdown.

    Returns None when no converter is installed (markdownify is optional) or
    conversion fails — callers fall back to the "<HTML output>" stub.
    """
    try:
        from markdownify import markdownify
    except ImportError:
        return None
    try:
        md = markdownify(html, heading_style="ATX", bullets="-")
    except Exception:
        return None
    import re
    md = "\n".join(line.rstrip() for line in md.splitlines())
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md or None


def _image_stub(mime: str, b64: str) -> str:
    import base64
    ext = mime.split("/")[-1].split("+")[0].upper()
    size_kb = len(b64) * 3 / 4 / 1024  # approximate decoded size

    # Try to extract image dimensions
    w, h = None, None
    try:
        raw = base64.b64decode(b64 + "=" * (-len(b64) % 4))
        if raw[:4] == b"\x89PNG":
            import struct
            w, h = struct.unpack(">II", raw[16:24])
        elif raw[:2] in (b"\xff\xd8",):
            pass  # JPEG: skip dimension parsing for v1
    except Exception:
        pass

    dim = f"{w}×{h}" if w and h else "unknown dims"
    return f"<image: {ext.lower()} {dim}, {size_kb:.1f} KB>"
