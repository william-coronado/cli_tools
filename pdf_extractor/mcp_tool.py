"""MCP handler for pdf_extractor. Exposed via the unified server (mcp_server.py)."""
from __future__ import annotations


def _handle(params: dict) -> str:
    from pathlib import Path
    from .extractor import PDFExtractor

    pdf_path = params["pdf_path"]
    pages = params.get("pages")
    force_ocr = bool(params.get("force_ocr", False))

    extractor = PDFExtractor()
    result = extractor.extract(Path(pdf_path), pages=pages, force_ocr=force_ocr)
    return result.to_markdown()
