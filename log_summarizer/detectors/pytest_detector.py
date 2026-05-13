from __future__ import annotations

import regex

from ..summarizer import LogLine, TracebackBlock
from .base import BaseDetector


class PytestDetector(BaseDetector):
    FORMAT_NAME = "pytest"

    RESULT_PATTERN = regex.compile(
        r"^(PASSED|FAILED|ERROR|SKIPPED)\s+(.+?)(?:\s+-\s+(.+))?$"
    )
    SECTION_PATTERN = regex.compile(r"^=+ (.+?) =+$")
    COLLECTED_PATTERN = regex.compile(r"^collected (\d+) items?")
    SUMMARY_PATTERN = regex.compile(
        r"(\d+) (?:passed|failed|error|skipped|warning)"
    )
    TEST_ID_PATTERN = regex.compile(r"test_\w+\.py::test_\w+")
    DIVIDER_PATTERN = regex.compile(r"^_+ .+ _+$")

    def score(self, sample_lines: list[str]) -> float:
        signals = 0
        for line in sample_lines:
            stripped = line.strip()
            if self.RESULT_PATTERN.match(stripped):
                signals += 2
            elif self.SECTION_PATTERN.match(stripped):
                signals += 1
            elif self.TEST_ID_PATTERN.search(stripped):
                signals += 1
            elif self.COLLECTED_PATTERN.match(stripped):
                signals += 2
            elif "short test summary info" in stripped or "warnings summary" in stripped:
                signals += 2
        return min(1.0, signals / max(len(sample_lines), 1) * 3)

    def extract(self, line: str, line_number: int) -> LogLine:
        stripped = line.strip()
        m = self.RESULT_PATTERN.match(stripped)
        if m:
            status = m.group(1)
            test_id = m.group(2).strip()
            level = "ERROR" if status in ("FAILED", "ERROR") else None
            category = "error" if status in ("FAILED", "ERROR") else "info"
            return LogLine(
                line_number=line_number, raw=line, level=level,
                timestamp=None, message=stripped, category=category, source=test_id,
            )
        if self.SECTION_PATTERN.match(stripped):
            return LogLine(
                line_number=line_number, raw=line, level=None,
                timestamp=None, message=stripped, category="info", source=None,
            )
        if stripped.startswith("WARNINGS"):
            return LogLine(
                line_number=line_number, raw=line, level="WARNING",
                timestamp=None, message=stripped, category="warning", source=None,
            )
        return LogLine(
            line_number=line_number, raw=line, level=None,
            timestamp=None, message=stripped, category="info", source=None,
        )

    def is_key_event(self, line: LogLine) -> bool:
        return line.category == "error" and self.RESULT_PATTERN.match(line.message or "")

    def extract_failure_blocks(self, lines: list[str]) -> list[TracebackBlock]:
        blocks: list[TracebackBlock] = []
        in_failure = False
        current: list[str] = []
        start_line = 0

        for i, line in enumerate(lines):
            stripped = line.strip()
            if self.DIVIDER_PATTERN.match(stripped) and "FAILURES" not in stripped:
                if in_failure and current:
                    blocks.append(self._make_tb_block(current, start_line, i))
                    current = []
                in_failure = True
                start_line = i + 1
            elif self.SECTION_PATTERN.match(stripped):
                if in_failure and current:
                    blocks.append(self._make_tb_block(current, start_line, i))
                    current = []
                in_failure = False
            elif in_failure:
                current.append(line)

        if in_failure and current:
            blocks.append(self._make_tb_block(current, start_line, len(lines)))
        return blocks

    def _make_tb_block(self, lines: list[str], start: int, end: int) -> TracebackBlock:
        full = "\n".join(lines)
        exc_type = exc_msg = None
        for line in reversed(lines):
            s = line.strip()
            if s and "::" not in s and "=" not in s:
                if "Error" in s or "Exception" in s or "assert" in s.lower():
                    if ":" in s:
                        exc_type, _, exc_msg = s.partition(":")
                        exc_type = exc_type.strip()
                        exc_msg = exc_msg.strip()
                    else:
                        exc_type = s
                    break
        frames = [l for l in lines if l.strip().startswith("File ") or l.strip().startswith("  File ")]
        return TracebackBlock(
            start_line=start, end_line=end,
            exception_type=exc_type, exception_message=exc_msg,
            frames=frames[-5:], full_text=full,
        )
