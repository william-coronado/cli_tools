from __future__ import annotations

import re

from .base import BaseExtractor, ExtractorOutput


class RawExtractor(BaseExtractor):
    REMOVE_TAGS = [
        "script", "style", "nav", "header", "footer",
        "aside", "form", "iframe", "svg", "button",
        "noscript", "meta", "link", "head",
    ]

    def extract(self, html: bytes, url: str) -> ExtractorOutput:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return ExtractorOutput(
                title=None, author=None, published_date=None,
                description=None, content_html="", content_text="",
                success=False,
            )

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        title: str | None = None
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True) or None

        for tag in self.REMOVE_TAGS:
            for el in soup.find_all(tag):
                el.decompose()

        text = soup.get_text(separator="\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = "\n".join(line.strip() for line in text.splitlines())
        text = text.strip()

        content_html = str(soup.body) if soup.body else f"<div>{text}</div>"

        return ExtractorOutput(
            title=title,
            author=None,
            published_date=None,
            description=None,
            content_html=content_html,
            content_text=text,
            success=True,
        )
