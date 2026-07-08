"""Tests for doc_extractor."""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from doc_extractor.extractor import (
    DocExtractor,
    ExtractorOptions,
    MissingOptionalDep,
    WrongContentType,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

_DOCX_DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>Quarterly Report</w:t></w:r></w:p>
    <w:p><w:r><w:t>Revenue grew twelve percent.</w:t></w:r></w:p>
  </w:body>
</w:document>
"""

_DOCX_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

_DOCX_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>
"""


@pytest.fixture
def tiny_docx(tmp_path) -> Path:
    """Minimal OOXML .docx built by hand (a zip of three XML parts)."""
    p = tmp_path / "report.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml", _DOCX_CONTENT_TYPES)
        z.writestr("_rels/.rels", _DOCX_RELS)
        z.writestr("word/document.xml", _DOCX_DOCUMENT_XML)
    return p


# ── Extension routing ─────────────────────────────────────────────────────────

class TestRouting:
    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            DocExtractor().extract("/no/such/file.docx")

    def test_pdf_redirects_to_sibling_tool(self, tmp_path):
        p = tmp_path / "x.pdf"
        p.write_bytes(b"%PDF-1.4")
        with pytest.raises(WrongContentType, match="pdf_extractor"):
            DocExtractor().extract(p)

    def test_ipynb_redirects_to_sibling_tool(self, tmp_path):
        p = tmp_path / "x.ipynb"
        p.write_text("{}")
        with pytest.raises(WrongContentType, match="notebook_extractor"):
            DocExtractor().extract(p)

    def test_unknown_extension_rejected(self, tmp_path):
        p = tmp_path / "x.xyz"
        p.write_text("data")
        with pytest.raises(WrongContentType, match="Unsupported extension"):
            DocExtractor().extract(p)


# ── Missing-dep path (always runs) ────────────────────────────────────────────

class TestMissingDep:
    def test_missing_markitdown_raises(self, monkeypatch, tmp_path):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.split(".")[0] == "markitdown":
                raise ImportError("markitdown not installed (simulated)")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        p = tmp_path / "x.docx"
        p.write_bytes(b"PK\x03\x04")
        with pytest.raises(MissingOptionalDep, match="pip install"):
            DocExtractor().extract(p)


# ── Conversion (needs markitdown installed) ───────────────────────────────────

class TestConversion:
    def test_docx_extracts_text(self, tiny_docx):
        pytest.importorskip("markitdown")
        r = DocExtractor().extract(tiny_docx)
        assert "Quarterly Report" in r.markdown
        assert "Revenue grew twelve percent." in r.markdown
        assert r.doc_format == "Word document"
        assert r.char_count == len(r.markdown)
        assert not r.truncated

    def test_truncation(self, tiny_docx):
        pytest.importorskip("markitdown")
        r = DocExtractor(ExtractorOptions(max_chars=10)).extract(tiny_docx)
        assert r.truncated
        assert r.char_count == 10
        assert any("truncated" in w.lower() for w in r.warnings)

    def test_corrupt_docx_raises_valueerror(self, tmp_path):
        pytest.importorskip("markitdown")
        p = tmp_path / "broken.docx"
        # Binary garbage — markitdown's DocxConverter raises BadZipFile.
        # (Plain-text content would instead hit its plain-text fallback.)
        p.write_bytes(bytes(range(256)) * 8)
        with pytest.raises(ValueError, match="Conversion failed"):
            DocExtractor().extract(p)


# ── Renderers ─────────────────────────────────────────────────────────────────

class TestRenderers:
    def test_markdown_has_header_and_body(self, tiny_docx):
        pytest.importorskip("markitdown")
        md = DocExtractor().extract(tiny_docx).to_markdown()
        assert md.startswith("# Document:")
        assert "**Format:** Word document" in md
        assert "Quarterly Report" in md

    def test_json_round_trips(self, tiny_docx):
        pytest.importorskip("markitdown")
        d = DocExtractor().extract(tiny_docx).to_json()
        json.dumps(d)  # raises if not serializable
        assert d["doc_format"] == "Word document"
        assert "Quarterly Report" in d["markdown"]

    def test_text_is_bare_markdown(self, tiny_docx):
        pytest.importorskip("markitdown")
        r = DocExtractor().extract(tiny_docx)
        assert r.to_text() == r.markdown


# ── CLI exit codes ────────────────────────────────────────────────────────────

class TestCLIExitCodes:
    def _run(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "doc_extractor.cli", *args],
            capture_output=True, text=True,
        )

    def test_zero_on_success(self, tiny_docx):
        pytest.importorskip("markitdown")
        r = self._run(str(tiny_docx))
        assert r.returncode == 0
        assert "Quarterly Report" in r.stdout

    def test_one_on_missing_file(self, tmp_path):
        r = self._run(str(tmp_path / "no_such.docx"))
        assert r.returncode == 1

    def test_three_on_wrong_type(self, tmp_path):
        p = tmp_path / "x.pdf"
        p.write_bytes(b"%PDF-1.4")
        r = self._run(str(p))
        assert r.returncode == 3

    def test_four_on_missing_markitdown(self, tiny_docx, tmp_path):
        # The CLI runs in a subprocess, so monkeypatching __import__ here
        # would not reach it. Instead, shadow markitdown with a stub that
        # raises ImportError on import, via PYTHONPATH (which precedes
        # site-packages on sys.path).
        import os
        stub_dir = tmp_path / "stub"
        stub_dir.mkdir()
        (stub_dir / "markitdown.py").write_text(
            'raise ImportError("markitdown not installed (simulated)")\n'
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(stub_dir) + os.pathsep + env.get("PYTHONPATH", "")
        r = subprocess.run(
            [sys.executable, "-m", "doc_extractor.cli", str(tiny_docx)],
            capture_output=True, text=True, env=env,
        )
        assert r.returncode == 4
        assert "markitdown" in r.stderr
        assert "pip install" in r.stderr

    def test_json_output_parses(self, tiny_docx):
        pytest.importorskip("markitdown")
        r = self._run(str(tiny_docx), "--format", "json")
        assert r.returncode == 0
        json.loads(r.stdout)


# ── MCP wrapper ───────────────────────────────────────────────────────────────

class TestMCPWrapper:
    def test_extract_document_returns_markdown(self, tiny_docx):
        pytest.importorskip("markitdown")
        from doc_extractor.mcp_tool import _handle
        result = _handle({"path": str(tiny_docx)})
        assert "# Document:" in result
        assert "Quarterly Report" in result
