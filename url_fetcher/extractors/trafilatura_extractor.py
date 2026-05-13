from __future__ import annotations

import xml.etree.ElementTree as ET

from .base import BaseExtractor, ExtractorOutput


class TrafilaturaExtractor(BaseExtractor):
    def extract(self, html: bytes, url: str) -> ExtractorOutput:
        try:
            import trafilatura
        except ImportError:
            return ExtractorOutput(
                title=None, author=None, published_date=None,
                description=None, content_html="", content_text="",
                success=False,
            )

        try:
            xml_output = trafilatura.extract(
                html,
                url=url,
                include_tables=True,
                include_links=True,
                include_images=False,
                favor_recall=True,
                output_format="xml",
            )

            title: str | None = None
            author: str | None = None
            published_date: str | None = None
            description: str | None = None
            content_html = ""
            content_text = ""

            if xml_output:
                try:
                    root = ET.fromstring(xml_output)
                    title = root.findtext("head/title") or root.findtext("title")
                    author = root.findtext("head/author") or root.findtext("author")
                    published_date = (
                        root.findtext("head/date")
                        or root.findtext("date")
                        or root.findtext("head/pubdate")
                    )
                    description = root.findtext("head/description") or root.findtext("description")

                    body_el = root.find("body")
                    if body_el is not None:
                        content_text = "".join(body_el.itertext()).strip()
                        content_html = ET.tostring(body_el, encoding="unicode")
                    else:
                        content_text = "".join(root.itertext()).strip()
                        content_html = xml_output
                except ET.ParseError:
                    # fall back to plain extraction
                    plain = trafilatura.extract(
                        html,
                        url=url,
                        include_tables=True,
                        include_links=True,
                        include_images=False,
                        favor_recall=True,
                    )
                    content_text = plain or ""
                    content_html = f"<div>{content_text}</div>"

            return ExtractorOutput(
                title=title,
                author=author,
                published_date=published_date,
                description=description,
                content_html=content_html,
                content_text=content_text,
                success=self._is_sufficient(content_text),
            )

        except Exception:
            return ExtractorOutput(
                title=None, author=None, published_date=None,
                description=None, content_html="", content_text="",
                success=False,
            )
