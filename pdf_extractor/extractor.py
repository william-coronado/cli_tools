from __future__ import annotations

import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .ocr import OCRBackend, get_backend

try:
    from pdf2image import convert_from_path
except ImportError:
    convert_from_path = None  # type: ignore[assignment]

_MIN_CHARS_THRESHOLD = 50


@dataclass
class PageResult:
    page_number: int
    text: str
    method: str
    confidence: float | None
    had_tables: bool


@dataclass
class ExtractionResult:
    source_path: str
    total_pages: int
    pages: list[PageResult]
    method: str
    ocr_backend: str | None
    elapsed_seconds: float

    def to_markdown(self) -> str:
        filename = Path(self.source_path).name
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        method_label = (
            f"text_layer (pdfplumber)"
            if self.method == "text_layer"
            else f"ocr ({self.ocr_backend})"
        )
        lines: list[str] = [
            f"# Extracted: {filename}",
            "",
            f"- **Pages:** {self.total_pages}",
            f"- **Method:** {method_label}",
            f"- **Extracted:** {ts}",
            "",
            "---",
            "",
        ]
        for page in self.pages:
            lines.append(f"<!-- Page {page.page_number} -->")
            lines.append("")
            lines.append(page.text)
            lines.append("")
            lines.append(f"<!-- /Page {page.page_number} -->")
            lines.append("")
        return "\n".join(lines)

    def to_text(self) -> str:
        parts: list[str] = []
        for page in self.pages:
            parts.append(page.text)
        return "\n\n".join(parts)

    def to_json(self) -> dict:
        return {
            "source_path": self.source_path,
            "total_pages": self.total_pages,
            "method": self.method,
            "ocr_backend": self.ocr_backend,
            "elapsed_seconds": self.elapsed_seconds,
            "pages": [
                {
                    "page_number": p.page_number,
                    "text": p.text,
                    "method": p.method,
                    "confidence": p.confidence,
                    "had_tables": p.had_tables,
                }
                for p in self.pages
            ],
        }


def _clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\x00", "").replace("\r", "")
    text = re.sub(r"[^\S\n\t ]+", " ", text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    lines = [line.rstrip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _join_paragraph_lines(text: str) -> str:
    """Merge lines within paragraphs that were split by the PDF layout engine."""
    result_lines: list[str] = []
    for line in text.splitlines():
        if (
            result_lines
            and result_lines[-1]
            and line
            and not result_lines[-1].endswith((".", "!", "?", ":"))
            and len(result_lines[-1]) > 40
        ):
            result_lines[-1] = result_lines[-1] + " " + line
        else:
            result_lines.append(line)
    return "\n".join(result_lines)


def _table_to_markdown(table: list[list[str | None]]) -> str:
    if not table:
        return ""
    rows = [[cell or "" for cell in row] for row in table]
    col_count = max(len(r) for r in rows)
    rows = [r + [""] * (col_count - len(r)) for r in rows]
    widths = [max(len(rows[r][c]) for r in range(len(rows))) for c in range(col_count)]

    def fmt_row(row: list[str]) -> str:
        cells = [row[c].ljust(widths[c]) for c in range(col_count)]
        return "| " + " | ".join(cells) + " |"

    sep = "| " + " | ".join("-" * max(3, w) for w in widths) + " |"
    md_lines = [fmt_row(rows[0]), sep]
    for row in rows[1:]:
        md_lines.append(fmt_row(row))
    return "\n".join(md_lines)


class PDFExtractor:
    def __init__(
        self,
        ocr_backend: str = "pytesseract",
        ocr_language: str = "eng",
        dpi: int = 300,
        verbose: bool = False,
    ) -> None:
        self.ocr_backend_name = ocr_backend
        self.ocr_language = ocr_language
        self.dpi = dpi
        self.verbose = verbose
        self._backend: OCRBackend | None = None

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg, file=sys.stderr)

    def _get_ocr_backend(self) -> OCRBackend:
        if self._backend is None:
            kwargs: dict = {}
            if self.ocr_backend_name == "pytesseract":
                kwargs["language"] = self.ocr_language
            elif self.ocr_backend_name == "easyocr":
                kwargs["languages"] = [self.ocr_language]
            self._backend = get_backend(self.ocr_backend_name, **kwargs)
        return self._backend

    def extract(
        self,
        pdf_path: str | Path,
        pages: str | None = None,
        force_ocr: bool = False,
        force_text: bool = False,
    ) -> ExtractionResult:
        path = Path(pdf_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Not a PDF file: {path}")

        page_range = _parse_page_range(pages) if pages else None

        t0 = time.monotonic()

        use_ocr = force_ocr
        if not use_ocr and not force_text:
            use_ocr = not self._has_text_layer(path)

        if use_ocr:
            self._log(f"[pdf_extractor] using OCR ({self.ocr_backend_name}) for {path.name}")
            page_results = self._extract_with_ocr(path, page_range=page_range)
            method = "ocr"
            ocr_backend = self.ocr_backend_name
        else:
            self._log(f"[pdf_extractor] using pdfplumber for {path.name}")
            page_results = self._extract_with_pdfplumber(path, page_range=page_range)
            method = "text_layer"
            ocr_backend = None

        elapsed = time.monotonic() - t0
        self._log(f"[pdf_extractor] done in {elapsed:.2f}s — {len(page_results)} pages")

        return ExtractionResult(
            source_path=str(path),
            total_pages=len(page_results),
            pages=page_results,
            method=method,
            ocr_backend=ocr_backend,
            elapsed_seconds=elapsed,
        )

    def _has_text_layer(self, pdf_path: Path, sample_pages: int = 3) -> bool:
        try:
            import pdfplumber
        except ImportError:
            raise RuntimeError(
                "pdfplumber is not installed. Install it with:\n  pip install pdfplumber"
            )

        try:
            with pdfplumber.open(pdf_path) as pdf:
                pages_to_check = pdf.pages[:sample_pages]
                total_chars = sum(len(p.extract_text() or "") for p in pages_to_check)
            return total_chars >= _MIN_CHARS_THRESHOLD
        except Exception:
            return False

    def _extract_with_pdfplumber(
        self, pdf_path: Path, page_range: set[int] | None = None
    ) -> list[PageResult]:
        try:
            import pdfplumber
        except ImportError:
            raise RuntimeError(
                "pdfplumber is not installed. Install it with:\n  pip install pdfplumber"
            )

        results: list[PageResult] = []

        try:
            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) == 0:
                    return []
                for i, page in enumerate(pdf.pages):
                    page_num = i + 1
                    if page_range and page_num not in page_range:
                        continue

                    had_tables = False
                    tables = page.extract_tables() or []
                    table_bboxes: list[object] = []
                    table_md_blocks: list[str] = []

                    for table in tables:
                        if table:
                            had_tables = True
                            table_md_blocks.append(_table_to_markdown(table))
                            ts = page.find_tables()
                            if ts:
                                table_bboxes.extend(ts)

                    raw_text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
                    cleaned = _clean_text(_join_paragraph_lines(raw_text))

                    if had_tables and table_md_blocks:
                        cleaned = cleaned + "\n\n" + "\n\n".join(table_md_blocks)
                        cleaned = _clean_text(cleaned)

                    results.append(
                        PageResult(
                            page_number=page_num,
                            text=cleaned,
                            method="pdfplumber",
                            confidence=None,
                            had_tables=had_tables,
                        )
                    )
        except Exception as e:
            msg = str(e).lower()
            if "password" in msg or "encrypt" in msg:
                raise PermissionError(
                    f"PDF is password-protected: {pdf_path.name}"
                ) from e
            raise

        return results

    def _extract_with_ocr(
        self, pdf_path: Path, page_range: set[int] | None = None
    ) -> list[PageResult]:
        if convert_from_path is None:
            raise RuntimeError(
                "pdf2image is not installed. Install it with:\n"
                "  pip install pdf2image\n"
                "and ensure Poppler is installed:\n"
                "  Ubuntu: sudo apt install poppler-utils\n"
                "  macOS:  brew install poppler"
            )

        try:
            images = convert_from_path(str(pdf_path), dpi=self.dpi)
        except Exception as e:
            msg = str(e).lower()
            if "poppler" in msg or "pdftoppm" in msg:
                raise RuntimeError(
                    "Poppler is required for PDF-to-image conversion:\n"
                    "  Ubuntu: sudo apt install poppler-utils\n"
                    "  macOS:  brew install poppler"
                ) from e
            if "password" in msg or "encrypt" in msg:
                raise PermissionError(
                    f"PDF is password-protected: {pdf_path.name}"
                ) from e
            raise

        backend = self._get_ocr_backend()
        results: list[PageResult] = []

        for i, image in enumerate(images):
            page_num = i + 1
            if page_range and page_num not in page_range:
                continue

            self._log(f"[pdf_extractor] OCR page {page_num}/{len(images)}")
            try:
                raw_text, confidence = backend.image_to_text(image)
                cleaned = _clean_text(raw_text)
            except Exception as e:
                print(
                    f"warning: OCR failed on page {page_num}: {e}", file=sys.stderr
                )
                cleaned = ""
                confidence = None

            results.append(
                PageResult(
                    page_number=page_num,
                    text=cleaned,
                    method=self.ocr_backend_name,
                    confidence=confidence,
                    had_tables=False,
                )
            )

        return results


def _parse_page_range(spec: str) -> set[int]:
    """Parse '1-5' or '1,3,7' into a set of 1-indexed page numbers."""
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start_s, _, end_s = part.partition("-")
            try:
                pages.update(range(int(start_s), int(end_s) + 1))
            except ValueError:
                pass
        else:
            try:
                pages.add(int(part))
            except ValueError:
                pass
    return pages
