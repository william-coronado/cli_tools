"""Core document extraction: office/document formats → markdown via markitdown."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path


class MissingOptionalDep(Exception):
    pass


class WrongContentType(Exception):
    pass


# Formats this tool owns. Everything else is either another tool's job or
# genuinely unsupported.
SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".docx": "Word document",
    ".pptx": "PowerPoint presentation",
    ".xlsx": "Excel workbook",
    ".epub": "EPUB book",
    ".msg": "Outlook message",
}

# Formats a sibling tool handles better — point there instead of converting.
_SIBLING_TOOLS: dict[str, str] = {
    ".pdf": "pdf_extractor (handles scanned PDFs/OCR)",
    ".ipynb": "notebook_extractor (image stubbing, output dedup)",
    ".csv": "data_summarizer (schema + stats)",
    ".tsv": "data_summarizer (schema + stats)",
    ".json": "data_summarizer (schema + stats)",
    ".jsonl": "data_summarizer (schema + stats)",
    ".parquet": "data_summarizer (schema + stats)",
    ".sqlite": "data_summarizer (schema + stats)",
    ".html": "url_fetcher (content extraction) or http_inspector",
}

_INSTALL_HINT = (
    "Install with: pip install 'markitdown[docx,pptx,xlsx]' "
    "(add the 'outlook' extra for .msg files)"
)


@dataclass
class DocResult:
    source: str
    doc_format: str
    title: str | None
    markdown: str
    char_count: int
    truncated: bool
    parse_duration_ms: int
    warnings: list[str] = field(default_factory=list)

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
    max_chars: int = 200_000


class DocExtractor:
    def __init__(self, options: ExtractorOptions | None = None) -> None:
        self.options = options or ExtractorOptions()

    def extract(self, path: str | Path) -> DocResult:
        t0 = time.monotonic()
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            sibling = _SIBLING_TOOLS.get(ext)
            if sibling:
                raise WrongContentType(
                    f"{ext} files are handled by {sibling}, not doc_extractor."
                )
            raise WrongContentType(
                f"Unsupported extension {ext!r}. Supported: "
                + ", ".join(sorted(SUPPORTED_EXTENSIONS))
            )

        try:
            from markitdown import MarkItDown
        except ImportError:
            raise MissingOptionalDep(
                f"doc_extractor requires markitdown. {_INSTALL_HINT}"
            )

        converter = MarkItDown(enable_plugins=False)
        try:
            result = converter.convert(str(path))
        except Exception as e:
            # markitdown raises MissingDependencyException when a
            # format-specific extra is absent; stay version-tolerant by
            # matching on the class name.
            if "MissingDependency" in type(e).__name__:
                raise MissingOptionalDep(f"{e} {_INSTALL_HINT}")
            raise ValueError(f"Conversion failed for {path.name}: {e}")

        markdown = (result.text_content or "").strip()
        warnings: list[str] = []
        truncated = False
        if len(markdown) > self.options.max_chars:
            markdown = markdown[: self.options.max_chars]
            truncated = True
            warnings.append(
                f"Output truncated to {self.options.max_chars:,} chars "
                f"(raise --max-chars to see more)"
            )
        if not markdown:
            warnings.append("Document produced no extractable text")

        return DocResult(
            source=str(path),
            doc_format=SUPPORTED_EXTENSIONS[ext],
            title=getattr(result, "title", None),
            markdown=markdown,
            char_count=len(markdown),
            truncated=truncated,
            parse_duration_ms=int((time.monotonic() - t0) * 1000),
            warnings=warnings,
        )
