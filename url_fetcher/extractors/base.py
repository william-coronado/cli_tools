from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ExtractorOutput:
    title: str | None
    author: str | None
    published_date: str | None
    description: str | None
    content_html: str
    content_text: str
    success: bool


class BaseExtractor(ABC):
    MIN_CONTENT_CHARS = 200

    @abstractmethod
    def extract(self, html: bytes, url: str) -> ExtractorOutput:
        """Extract main content from raw HTML bytes. Must never raise."""
        ...

    def _is_sufficient(self, text: str) -> bool:
        return len(text.strip()) >= self.MIN_CONTENT_CHARS
