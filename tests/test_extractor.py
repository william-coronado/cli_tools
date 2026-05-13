"""Tests for pdf_extractor.

OCR tests mock the backend to avoid requiring Tesseract/Poppler in CI.
A single integration test is gated on shutil.which("tesseract").
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pdf_extractor.extractor import (
    PDFExtractor,
    ExtractionResult,
    PageResult,
    _parse_page_range,
    _clean_text,
    _table_to_markdown,
)
from pdf_extractor.ocr import PytesseractBackend, EasyOCRBackend, get_backend


# ── _parse_page_range ──────────────────────────────────────────────────────────

class TestParsePageRange:
    def test_range(self):
        assert _parse_page_range("1-3") == {1, 2, 3}

    def test_list(self):
        assert _parse_page_range("1,3,7") == {1, 3, 7}

    def test_single(self):
        assert _parse_page_range("5") == {5}

    def test_mixed(self):
        assert _parse_page_range("1-2,5") == {1, 2, 5}


# ── _clean_text ────────────────────────────────────────────────────────────────

class TestCleanText:
    def test_strips_null_bytes(self):
        assert "\x00" not in _clean_text("hello\x00world")

    def test_collapses_blank_lines(self):
        result = _clean_text("a\n\n\n\n\nb")
        assert "\n\n\n" not in result

    def test_dehyphenates(self):
        assert "computation" in _clean_text("computa-\ntion")

    def test_normalizes_unicode(self):
        assert _clean_text("ﬁle") == "file"


# ── _table_to_markdown ─────────────────────────────────────────────────────────

class TestTableToMarkdown:
    def test_basic_table(self):
        table = [["A", "B"], ["1", "2"]]
        md = _table_to_markdown(table)
        assert "| A" in md
        assert "| ---" in md
        assert "| 1" in md

    def test_empty_table(self):
        assert _table_to_markdown([]) == ""

    def test_handles_none_cells(self):
        md = _table_to_markdown([["A", None], ["1", "2"]])
        assert "| A" in md


# ── ExtractionResult formatting ────────────────────────────────────────────────

class TestExtractionResult:
    def _make_result(self, method: str = "text_layer") -> ExtractionResult:
        pages = [
            PageResult(1, "Hello world.", "pdfplumber", None, False),
            PageResult(2, "Page two.", "pdfplumber", None, False),
        ]
        return ExtractionResult(
            source_path="/tmp/test.pdf",
            total_pages=2,
            pages=pages,
            method=method,
            ocr_backend=None if method == "text_layer" else "pytesseract",
            elapsed_seconds=0.5,
        )

    def test_to_markdown_has_page_markers(self):
        md = self._make_result().to_markdown()
        assert "<!-- Page 1 -->" in md
        assert "<!-- /Page 1 -->" in md
        assert "<!-- Page 2 -->" in md

    def test_to_markdown_has_header(self):
        md = self._make_result().to_markdown()
        assert "# Extracted: test.pdf" in md

    def test_to_markdown_method_label_text_layer(self):
        md = self._make_result("text_layer").to_markdown()
        assert "text_layer (pdfplumber)" in md

    def test_to_markdown_method_label_ocr(self):
        md = self._make_result("ocr").to_markdown()
        assert "ocr (pytesseract)" in md

    def test_to_json_round_trips(self):
        result = self._make_result()
        d = result.to_json()
        assert d["total_pages"] == 2
        assert d["pages"][0]["text"] == "Hello world."
        json.dumps(d)  # must be serialisable

    def test_to_text_no_page_markers(self):
        text = self._make_result().to_text()
        assert "<!-- Page" not in text
        assert "Hello world." in text


# ── OCR backend factory ────────────────────────────────────────────────────────

class TestGetBackend:
    def test_pytesseract_backend(self):
        b = get_backend("pytesseract")
        assert isinstance(b, PytesseractBackend)

    def test_easyocr_backend(self):
        b = get_backend("easyocr")
        assert isinstance(b, EasyOCRBackend)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown OCR backend"):
            get_backend("imaginary")


# ── PDFExtractor with text-layer PDF ──────────────────────────────────────────

class TestPDFExtractorTextLayer:
    def test_extracts_text(self, text_pdf):
        extractor = PDFExtractor()
        result = extractor.extract(text_pdf)
        assert result.method == "text_layer"
        assert result.total_pages >= 1
        full = " ".join(p.text for p in result.pages)
        assert "Hello" in full or len(full) > 10

    def test_page_range(self, text_pdf):
        extractor = PDFExtractor()
        result = extractor.extract(text_pdf, pages="1")
        assert result.total_pages == 1

    def test_to_markdown_page_markers(self, text_pdf):
        result = PDFExtractor().extract(text_pdf)
        md = result.to_markdown()
        assert "<!-- Page 1 -->" in md
        assert "<!-- /Page 1 -->" in md


# ── PDFExtractor error handling ───────────────────────────────────────────────

class TestPDFExtractorErrors:
    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            PDFExtractor().extract("/nonexistent/path/file.pdf")

    def test_non_pdf_raises(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        with pytest.raises(ValueError, match="Not a PDF"):
            PDFExtractor().extract(f)

    def test_empty_pdf_does_not_crash(self, tmp_path):
        # fpdf2 always adds 1 blank page; test that extraction completes without error
        try:
            from fpdf import FPDF  # type: ignore[import]
        except ImportError:
            pytest.skip("fpdf2 not installed")
        p = tmp_path / "empty.pdf"
        pdf = FPDF()
        pdf.output(str(p))
        result = PDFExtractor().extract(p)
        assert isinstance(result, ExtractionResult)

    def test_zero_page_pdf_returns_empty(self, tmp_path):
        # Test the 0-pages code path: force pdfplumber path, mock it to return 0 pages
        try:
            from fpdf import FPDF  # type: ignore[import]
        except ImportError:
            pytest.skip("fpdf2 not installed")
        p = tmp_path / "zero.pdf"
        pdf = FPDF()
        pdf.output(str(p))

        import pdfplumber
        mock_doc = MagicMock()
        mock_doc.__enter__ = lambda s: mock_doc
        mock_doc.__exit__ = MagicMock(return_value=False)
        mock_doc.pages = []

        extractor = PDFExtractor()
        with patch.object(extractor, "_has_text_layer", return_value=True):
            with patch.object(pdfplumber, "open", return_value=mock_doc):
                result = extractor.extract(p)

        assert result.pages == []
        assert result.total_pages == 0


# ── PDFExtractor with mocked OCR ──────────────────────────────────────────────

class TestPDFExtractorOCRMocked:
    def test_force_ocr_uses_ocr_method(self, text_pdf):
        mock_backend = MagicMock()
        mock_backend.image_to_text.return_value = ("mocked ocr text", 95.0)

        with patch("pdf_extractor.extractor.get_backend", return_value=mock_backend):
            with patch("pdf_extractor.extractor.convert_from_path") as mock_convert:
                from PIL import Image as PILImage
                mock_convert.return_value = [PILImage.new("RGB", (100, 100))]
                result = PDFExtractor().extract(text_pdf, force_ocr=True)

        assert result.method == "ocr"
        assert result.ocr_backend == "pytesseract"
        assert result.pages[0].text == "mocked ocr text"
        assert result.pages[0].confidence == 95.0

    def test_ocr_page_failure_is_partial(self, text_pdf):
        mock_backend = MagicMock()
        mock_backend.image_to_text.side_effect = RuntimeError("OCR exploded")

        with patch("pdf_extractor.extractor.get_backend", return_value=mock_backend):
            with patch("pdf_extractor.extractor.convert_from_path") as mock_convert:
                from PIL import Image as PILImage
                mock_convert.return_value = [PILImage.new("RGB", (100, 100))]
                result = PDFExtractor().extract(text_pdf, force_ocr=True)

        assert result.pages[0].text == ""
        assert result.pages[0].confidence is None

    def test_scanned_pdf_triggers_ocr(self, scanned_pdf):
        mock_backend = MagicMock()
        mock_backend.image_to_text.return_value = ("scanned text", 80.0)

        with patch("pdf_extractor.extractor.get_backend", return_value=mock_backend):
            with patch("pdf_extractor.extractor.convert_from_path") as mock_convert:
                from PIL import Image as PILImage
                mock_convert.return_value = [PILImage.new("RGB", (100, 100))]
                result = PDFExtractor().extract(scanned_pdf)

        assert result.method == "ocr"


# ── CLI ────────────────────────────────────────────────────────────────────────

class TestCLI:
    def test_invalid_path_exits_1(self):
        from pdf_extractor.cli import main
        rc = main(["/no/such/file.pdf"])
        assert rc == 1

    def test_text_layer_markdown(self, text_pdf):
        from pdf_extractor.cli import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main([str(text_pdf)])
        assert rc == 0
        assert "<!-- Page 1 -->" in buf.getvalue()

    def test_pages_flag_limits_output(self, text_pdf):
        from pdf_extractor.cli import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main([str(text_pdf), "--pages", "1"])
        assert rc == 0
        out = buf.getvalue()
        assert "<!-- Page 1 -->" in out
        assert "<!-- Page 2 -->" not in out

    def test_format_json(self, text_pdf):
        from pdf_extractor.cli import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main([str(text_pdf), "--format", "json"])
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert "pages" in data

    def test_missing_dep_exits_4(self, text_pdf):
        from pdf_extractor.cli import main
        with patch("pdf_extractor.extractor.PDFExtractor.extract") as mock_extract:
            mock_extract.side_effect = RuntimeError("tesseract not found on this machine")
            rc = main([str(text_pdf), "--force-ocr"])
        assert rc == 4

    def test_directory_mode(self, tmp_path, text_pdf):
        import shutil as _shutil
        dest = tmp_path / "pdfs"
        dest.mkdir()
        _shutil.copy(text_pdf, dest / "a.pdf")
        from pdf_extractor.cli import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main([str(dest)])
        assert rc == 0
        assert "<!-- Page 1 -->" in buf.getvalue()


# ── Integration test (requires Tesseract) ─────────────────────────────────────

@pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="Tesseract not installed",
)
def test_ocr_integration(scanned_pdf):
    result = PDFExtractor(ocr_backend="pytesseract").extract(scanned_pdf, force_ocr=True)
    assert result.method == "ocr"
    assert result.total_pages >= 1
