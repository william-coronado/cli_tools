from __future__ import annotations

import regex

from ..summarizer import LogLine
from .base import BaseDetector


class PythonLoggingDetector(BaseDetector):
    FORMAT_NAME = "python_logging"

    FORMATS = [
        regex.compile(
            r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[,\.]\d+)"
            r"\s*-\s*(?P<name>[\w\.]+)\s*-\s*(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)"
            r"\s*-\s*(?P<msg>.+)$"
        ),
        regex.compile(
            r"^(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL):(?P<name>[\w\.]+):(?P<msg>.+)$"
        ),
        regex.compile(
            r"^\[(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\]\s+(?P<msg>.+)$"
        ),
    ]

    _LEVEL_TO_CATEGORY = {
        "ERROR": "error",
        "CRITICAL": "error",
        "WARNING": "warning",
        "INFO": "info",
        "DEBUG": "info",
    }

    def score(self, sample_lines: list[str]) -> float:
        if not sample_lines:
            return 0.0
        matches = sum(
            1
            for line in sample_lines
            if any(pat.match(line.strip()) for pat in self.FORMATS)
        )
        return matches / len(sample_lines)

    def extract(self, line: str, line_number: int) -> LogLine:
        for pat in self.FORMATS:
            m = pat.match(line.strip())
            if m:
                gd = m.groupdict()
                level = gd.get("level", "").upper()
                return LogLine(
                    line_number=line_number,
                    raw=line,
                    level=level or None,
                    timestamp=gd.get("ts"),
                    message=gd.get("msg", line).strip(),
                    category=self._LEVEL_TO_CATEGORY.get(level, "info"),
                    source=gd.get("name"),
                )
        # Fallback: check for traceback markers
        stripped = line.strip()
        if stripped.startswith("Traceback") or stripped.startswith("  File "):
            return LogLine(
                line_number=line_number, raw=line, level=None,
                timestamp=None, message=stripped, category="traceback", source=None,
            )
        return LogLine(
            line_number=line_number, raw=line, level=None,
            timestamp=None, message=stripped, category="info", source=None,
        )
