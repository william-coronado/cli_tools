from __future__ import annotations

import json

from ..summarizer import LogLine
from .base import BaseDetector


class JSONDetector(BaseDetector):
    FORMAT_NAME = "json_lines"

    LEVEL_FIELDS = ["level", "severity", "log_level", "lvl"]
    MESSAGE_FIELDS = ["message", "msg", "text", "body"]
    TIMESTAMP_FIELDS = ["timestamp", "time", "ts", "@timestamp", "datetime"]
    ERROR_FIELDS = ["error", "exception", "stack_trace", "traceback", "err"]

    _LEVEL_TO_CATEGORY = {
        "error": "error", "err": "error", "fatal": "error", "critical": "error",
        "warning": "warning", "warn": "warning",
        "info": "info", "information": "info",
        "debug": "info",
    }

    def score(self, sample_lines: list[str]) -> float:
        if not sample_lines:
            return 0.0
        parsed = sum(1 for line in sample_lines if self._try_parse(line) is not None)
        return parsed / len(sample_lines)

    def extract(self, line: str, line_number: int) -> LogLine:
        obj = self._try_parse(line)
        if obj is None:
            return LogLine(
                line_number=line_number, raw=line, level=None,
                timestamp=None, message=line.strip(), category="info", source=None,
            )

        level_raw = self._find_field(obj, self.LEVEL_FIELDS) or ""
        level = level_raw.upper() if isinstance(level_raw, str) else ""
        category = self._LEVEL_TO_CATEGORY.get(level_raw.lower() if isinstance(level_raw, str) else "", "info")

        message = self._find_field(obj, self.MESSAGE_FIELDS) or line.strip()
        timestamp = self._find_field(obj, self.TIMESTAMP_FIELDS)
        error = self._find_field(obj, self.ERROR_FIELDS)
        if error:
            category = "error"
            if isinstance(error, str):
                message = error

        # Source = all remaining fields as compact repr
        known = set(self.LEVEL_FIELDS + self.MESSAGE_FIELDS + self.TIMESTAMP_FIELDS + self.ERROR_FIELDS)
        extra = {k: v for k, v in obj.items() if k not in known}
        source = json.dumps(extra, ensure_ascii=False) if extra else None

        return LogLine(
            line_number=line_number, raw=line,
            level=level or None,
            timestamp=str(timestamp) if timestamp is not None else None,
            message=str(message),
            category=category,
            source=source,
        )

    def _try_parse(self, line: str):
        stripped = line.strip()
        if not stripped.startswith("{"):
            return None
        try:
            obj = json.loads(stripped)
            return obj if isinstance(obj, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None

    def _find_field(self, obj: dict, candidates: list[str]):
        for key in candidates:
            if key in obj:
                return obj[key]
        # Case-insensitive fallback
        lower_obj = {k.lower(): v for k, v in obj.items()}
        for key in candidates:
            if key.lower() in lower_obj:
                return lower_obj[key.lower()]
        return None
