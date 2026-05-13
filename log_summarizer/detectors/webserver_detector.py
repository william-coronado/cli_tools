from __future__ import annotations

import regex

from ..summarizer import LogLine
from .base import BaseDetector


COMBINED_PATTERN = regex.compile(
    r'^(?P<ip>\S+)\s+\S+\s+\S+\s+\[(?P<time>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+\S+"\s+'
    r'(?P<status>\d{3})\s+(?P<size>\S+)'
    r'(?:\s+"(?P<referer>[^"]*)"\s+"(?P<ua>[^"]*)")?'
)

NGINX_ERROR_PATTERN = regex.compile(
    r'^(?P<ts>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s+'
    r'\[(?P<level>\w+)\]\s+\d+#\d+:\s+(?P<msg>.+)$'
)


class WebserverDetector(BaseDetector):
    FORMAT_NAME = "webserver"

    def score(self, sample_lines: list[str]) -> float:
        if not sample_lines:
            return 0.0
        hits = sum(
            1 for line in sample_lines
            if COMBINED_PATTERN.match(line.strip()) or NGINX_ERROR_PATTERN.match(line.strip())
        )
        return hits / len(sample_lines)

    def extract(self, line: str, line_number: int) -> LogLine:
        stripped = line.strip()

        m = COMBINED_PATTERN.match(stripped)
        if m:
            status = int(m.group("status"))
            path = m.group("path")
            ts = m.group("time")
            if status >= 500:
                category, level = "error", "ERROR"
            elif status >= 400:
                category, level = "warning", "WARNING"
            else:
                category, level = "info", None
            return LogLine(
                line_number=line_number, raw=line,
                level=level, timestamp=ts,
                message=f"{m.group('method')} {path} {status}",
                category=category, source=m.group("ip"),
            )

        m2 = NGINX_ERROR_PATTERN.match(stripped)
        if m2:
            lvl = m2.group("level").upper()
            level_map = {"ERROR": "error", "WARN": "warning", "CRIT": "error", "EMERG": "error"}
            category = level_map.get(lvl, "info")
            return LogLine(
                line_number=line_number, raw=line,
                level=lvl, timestamp=m2.group("ts"),
                message=m2.group("msg"),
                category=category, source=None,
            )

        return LogLine(
            line_number=line_number, raw=line, level=None,
            timestamp=None, message=stripped, category="info", source=None,
        )

    def is_key_event(self, line: LogLine) -> bool:
        return line.category == "error"
