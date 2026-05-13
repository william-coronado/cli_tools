from __future__ import annotations

import regex
from collections import deque

from .summarizer import LogLine, DedupGroup


class Deduplicator:
    _NUM = regex.compile(r"\b\d+(?:\.\d+)?\b")
    _UUID = regex.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", regex.IGNORECASE)
    _HEX = regex.compile(r"\b0x[0-9a-f]{4,}\b", regex.IGNORECASE)
    _TS = regex.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[,\.]\d+)?")

    NEVER_SUPPRESS = frozenset({"error", "traceback"})

    def __init__(
        self,
        exact_threshold: int = 3,
        fuzzy_threshold: float = 0.85,
        window_size: int = 100,
        never_suppress: list[str] | None = None,
    ) -> None:
        self.exact_threshold = exact_threshold
        self.fuzzy_threshold = fuzzy_threshold
        self.window_size = window_size
        self._never_suppress = frozenset(never_suppress or self.NEVER_SUPPRESS)

        # key: normalized text → (LogLine representative, count, first_line, last_line)
        self._groups: dict[str, tuple[LogLine, int, int, int]] = {}
        # Sliding window of normalized keys (bounded)
        self._window: deque[str] = deque(maxlen=window_size)
        # Counts within the current window
        self._window_counts: dict[str, int] = {}

    def process(self, line: LogLine) -> LogLine | None:
        if line.category in self._never_suppress:
            return line

        key = self._normalize(line.message)

        # Maintain window counts
        if len(self._window) == self.window_size:
            evicted = self._window[0]
            if evicted in self._window_counts:
                self._window_counts[evicted] -= 1
                if self._window_counts[evicted] <= 0:
                    del self._window_counts[evicted]

        self._window.append(key)
        self._window_counts[key] = self._window_counts.get(key, 0) + 1

        count_in_window = self._window_counts[key]

        if count_in_window > self.exact_threshold:
            # Update or create dedup group
            if key in self._groups:
                rep, cnt, first, last = self._groups[key]
                self._groups[key] = (rep, cnt + 1, first, line.line_number)
            else:
                self._groups[key] = (line, 1, line.line_number, line.line_number)
            return None

        # Track all occurrences for group assembly
        if key in self._groups:
            rep, cnt, first, last = self._groups[key]
            self._groups[key] = (rep, cnt + 1, first, line.line_number)

        return line

    def get_dedup_groups(self) -> list[DedupGroup]:
        result = []
        for key, (rep, cnt, first, last) in self._groups.items():
            if cnt > self.exact_threshold:
                result.append(DedupGroup(
                    representative=rep,
                    count=cnt,
                    first_line=first,
                    last_line=last,
                ))
        return sorted(result, key=lambda g: g.count, reverse=True)

    def _normalize(self, text: str) -> str:
        t = text.lower().strip()
        t = self._TS.sub("{TS}", t)
        t = self._UUID.sub("{ID}", t)
        t = self._HEX.sub("{ID}", t)
        t = self._NUM.sub("{N}", t)
        return t
