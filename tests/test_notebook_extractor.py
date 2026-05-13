"""Tests for notebook_extractor."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from notebook_extractor.extractor import (
    ExtractorOptions,
    NotebookExtractor,
    NotebookResult,
)
from notebook_extractor.dedup import dedup_stream, _cr_strip, _suppress_consecutive


def _extract(path, **opts) -> NotebookResult:
    return NotebookExtractor(ExtractorOptions(**opts)).extract(path)


# ── Cell extraction ───────────────────────────────────────────────────────────

class TestCellExtraction:
    def test_all_cell_types_parsed(self, tiny_notebook):
        r = _extract(tiny_notebook)
        types = {c.cell_type for c in r.cells}
        assert "code" in types and "markdown" in types

    def test_total_and_shown(self, tiny_notebook):
        r = _extract(tiny_notebook)
        assert r.total_cells == 5
        assert r.shown_cells == 5

    def test_source_preserved(self, tiny_notebook):
        r = _extract(tiny_notebook)
        code_cell = next(c for c in r.cells if c.cell_type == "code")
        assert "pd" in code_cell.source or "plt" in code_cell.source or "step" in code_cell.source

    def test_language_detected(self, tiny_notebook):
        r = _extract(tiny_notebook)
        assert r.language == "python"


# ── Cell filters ─────────────────────────────────────────────────────────────

class TestCellFilters:
    def test_code_only(self, tiny_notebook):
        r = _extract(tiny_notebook, code_only=True)
        assert all(c.cell_type == "code" for c in r.cells)
        assert r.shown_cells == 3

    def test_markdown_only(self, tiny_notebook):
        r = _extract(tiny_notebook, markdown_only=True)
        assert all(c.cell_type == "markdown" for c in r.cells)
        assert r.shown_cells == 2

    def test_cells_slice(self, tiny_notebook):
        r = _extract(tiny_notebook, cells_slice=slice(0, 2))
        assert r.shown_cells == 2

    def test_cells_slice_single(self, tiny_notebook):
        r = _extract(tiny_notebook, cells_slice=slice(1, 2))
        assert r.shown_cells == 1

    def test_tag_filter(self, tagged_notebook):
        r = _extract(tagged_notebook, tags=["training"])
        assert r.shown_cells == 1
        assert r.cells[0].tags == ["training"]

    def test_tag_filter_multiple_tags(self, tagged_notebook):
        r = _extract(tagged_notebook, tags=["setup", "viz"])
        assert r.shown_cells == 2

    def test_no_outputs(self, tiny_notebook):
        r = _extract(tiny_notebook, no_outputs=True)
        for cell in r.cells:
            assert cell.outputs == []

    def test_total_unchanged_by_filter(self, tiny_notebook):
        r = _extract(tiny_notebook, code_only=True)
        assert r.total_cells == 5


# ── Output processing ─────────────────────────────────────────────────────────

class TestOutputProcessing:
    def test_image_output_stubbed(self, tiny_notebook):
        r = _extract(tiny_notebook)
        image_outputs = [
            o for c in r.cells for o in c.outputs if o.image_stub
        ]
        assert len(image_outputs) == 1
        stub = image_outputs[0].image_stub
        assert "png" in stub
        assert "40" in stub and "30" in stub  # dimensions from fixture

    def test_text_output_present(self, tiny_notebook):
        r = _extract(tiny_notebook)
        text_outputs = [o for c in r.cells for o in c.outputs if o.text]
        assert text_outputs

    def test_stream_dedup(self, tiny_notebook):
        r = _extract(tiny_notebook)
        stream_cell = next(
            c for c in r.cells if any(o.output_type == "stream" for o in c.outputs)
        )
        out = next(o for o in stream_cell.outputs if o.output_type == "stream")
        assert out.suppressed_lines > 0

    def test_text_truncation(self, tiny_notebook):
        r = _extract(tiny_notebook, max_output_lines=2)
        text_outputs = [
            o for c in r.cells for o in c.outputs
            if o.text and o.output_type in ("execute_result", "display_data")
        ]
        for o in text_outputs:
            assert len(o.text.splitlines()) <= 2


# ── Deduplication ─────────────────────────────────────────────────────────────

class TestDedup:
    def test_cr_strip_keeps_last(self):
        result = _cr_strip("abc\rdef\rghi")
        assert result == "ghi"

    def test_cr_strip_multiline(self):
        result = _cr_strip("line1\nab\rcd\nline3")
        assert result == "line1\ncd\nline3"

    def test_consecutive_suppression(self):
        lines = ["step 1"] * 10
        out, suppressed = _suppress_consecutive(lines)
        assert suppressed > 0
        assert len(out) < 10

    def test_dedup_stream_step_pattern(self):
        text = "\n".join(f"step {i}" for i in range(100))
        cleaned, suppressed = dedup_stream(text)
        assert suppressed > 0
        assert len(cleaned.splitlines()) < 100

    def test_no_dedup_preserves_all(self, tiny_notebook):
        r = _extract(tiny_notebook, no_dedup=True)
        stream_cell = next(
            c for c in r.cells if any(o.output_type == "stream" for o in c.outputs)
        )
        out = next(o for o in stream_cell.outputs if o.output_type == "stream")
        assert out.suppressed_lines == 0


# ── Renderers ─────────────────────────────────────────────────────────────────

class TestRenderers:
    def test_markdown_has_cell_headers(self, tiny_notebook):
        md = _extract(tiny_notebook).to_markdown()
        assert "**[code]**" in md
        assert "**[markdown]**" in md

    def test_markdown_has_image_stub(self, tiny_notebook):
        md = _extract(tiny_notebook).to_markdown()
        assert "<image: png" in md

    def test_json_parses(self, tiny_notebook):
        d = _extract(tiny_notebook).to_json()
        json.dumps(d)
        assert d["language"] == "python"
        assert len(d["cells"]) == 5

    def test_json_cell_structure(self, tiny_notebook):
        d = _extract(tiny_notebook).to_json()
        cell = d["cells"][0]
        assert "cell_type" in cell and "source" in cell and "outputs" in cell

    def test_text_renderer_contains_source(self, tiny_notebook):
        text = _extract(tiny_notebook).to_text()
        assert "pd" in text or "plt" in text or "step" in text

    def test_text_renderer_no_headers(self, tiny_notebook):
        text = _extract(tiny_notebook).to_text()
        assert "**[code]**" not in text


# ── Directory mode ────────────────────────────────────────────────────────────

class TestDirectoryMode:
    def test_summarizes_multiple_notebooks(self, notebook_dir):
        r = subprocess.run(
            [sys.executable, "-m", "notebook_extractor.cli", str(notebook_dir), "--no-outputs"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0
        assert r.stdout.count("# Notebook:") == 2

    def test_excludes_node_modules(self, notebook_dir):
        r = subprocess.run(
            [sys.executable, "-m", "notebook_extractor.cli", str(notebook_dir), "--no-outputs"],
            capture_output=True, text=True,
        )
        assert "excluded.ipynb" not in r.stdout


# ── Exit codes ────────────────────────────────────────────────────────────────

class TestExitCodes:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "notebook_extractor.cli", *args],
            capture_output=True, text=True,
        )

    def test_zero_on_success(self, tiny_notebook):
        r = self._run(str(tiny_notebook))
        assert r.returncode == 0

    def test_one_on_missing_file(self):
        r = self._run("/no/such/file.ipynb")
        assert r.returncode == 1

    def test_one_on_non_notebook(self, tmp_path):
        p = tmp_path / "data.csv"
        p.write_text("a,b\n1,2\n")
        r = self._run(str(p))
        assert r.returncode == 1

    def test_three_on_empty_dir(self, tmp_path):
        r = self._run(str(tmp_path))
        assert r.returncode == 3

    def test_json_output_valid(self, tiny_notebook):
        r = self._run(str(tiny_notebook), "--format", "json")
        assert r.returncode == 0
        json.loads(r.stdout)


# ── MCP wrapper ───────────────────────────────────────────────────────────────

class TestMCPWrapper:
    def test_extract_notebook_returns_result(self, tiny_notebook):
        req = json.dumps({"name": "extract_notebook", "parameters": {"path": str(tiny_notebook)}})
        r = subprocess.run(
            [sys.executable, "-m", "notebook_extractor.mcp_tool"],
            input=req + "\n", capture_output=True, text=True,
        )
        assert r.returncode == 0
        d = json.loads(r.stdout.strip())
        assert "result" in d
        assert "# Notebook:" in d["result"]

    def test_unknown_tool_returns_error(self):
        r = subprocess.run(
            [sys.executable, "-m", "notebook_extractor.mcp_tool"],
            input='{"name":"nope","parameters":{}}\n', capture_output=True, text=True,
        )
        d = json.loads(r.stdout.strip())
        assert "error" in d
