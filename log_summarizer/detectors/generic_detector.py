from __future__ import annotations

import regex

from ..summarizer import LogLine
from .base import BaseDetector


class GenericDetector(BaseDetector):
    FORMAT_NAME = "generic"

    ERROR_KEYWORDS = regex.compile(
        r"\b(error|exception|fatal|critical|fail(?:ed|ure)?|crash(?:ed)?|"
        r"abort(?:ed)?|panic|segfault|killed|oom)\b",
        regex.IGNORECASE,
    )
    WARNING_KEYWORDS = regex.compile(
        r"\b(warn(?:ing)?|deprecated|caution|notice)\b",
        regex.IGNORECASE,
    )

    def score(self, sample_lines: list[str]) -> float:
        return 0.1

    def extract(self, line: str, line_number: int) -> LogLine:
        if self.ERROR_KEYWORDS.search(line):
            category = "error"
            level = "ERROR"
        elif self.WARNING_KEYWORDS.search(line):
            category = "warning"
            level = "WARNING"
        else:
            category = "info"
            level = None

        return LogLine(
            line_number=line_number,
            raw=line,
            level=level,
            timestamp=None,
            message=line.strip(),
            category=category,
            source=None,
        )
