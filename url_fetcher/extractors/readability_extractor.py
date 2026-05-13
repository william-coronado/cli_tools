from __future__ import annotations

from .base import BaseExtractor, ExtractorOutput


class ReadabilityExtractor(BaseExtractor):
    def extract(self, html: bytes, url: str) -> ExtractorOutput:
        try:
            from readability import Document
        except ImportError:
            return ExtractorOutput(
                title=None, author=None, published_date=None,
                description=None, content_html="", content_text="",
                success=False,
            )

        try:
            doc = Document(html)
            title = doc.title() or None
            summary_html = doc.summary()

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(summary_html, "lxml")
            content_text = soup.get_text(separator="\n").strip()

            return ExtractorOutput(
                title=title,
                author=None,
                published_date=None,
                description=None,
                content_html=summary_html,
                content_text=content_text,
                success=self._is_sufficient(content_text),
            )
        except Exception:
            return ExtractorOutput(
                title=None, author=None, published_date=None,
                description=None, content_html="", content_text="",
                success=False,
            )
