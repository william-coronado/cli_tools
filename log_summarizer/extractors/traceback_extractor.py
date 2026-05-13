from __future__ import annotations

import regex

from ..summarizer import TracebackBlock


class TracebackExtractor:
    TB_START = regex.compile(r"^Traceback \(most recent call last\):")
    TB_FRAME = regex.compile(r'^\s+File ".+", line \d+, in .+')
    TB_EXCEPTION = regex.compile(
        r"^([A-Z][a-zA-Z]+(?:Error|Exception|Warning|Interrupt|Exit|KeyboardInterrupt|SystemExit)[^\n]*)"
    )
    TB_CHAINED = regex.compile(
        r"^(?:During handling of the above|The above exception)"
    )
    JAVA_EXCEPTION = regex.compile(r"^(?:Exception|Error) in thread")
    JAVA_FRAME = regex.compile(r"^\s+at [\w\.\$]+\([\w\.]+:\d+\)")

    def __init__(self, max_frames: int = 5) -> None:
        self.max_frames = max_frames
        self._in_traceback = False
        self._current_block: list[str] = []
        self._start_line = 0
        self._current_end = 0

    def feed(self, line: str, line_number: int) -> TracebackBlock | None:
        stripped = line.strip()

        if self.TB_START.match(stripped) or self.JAVA_EXCEPTION.match(stripped):
            # Finish any in-progress block first
            completed = None
            if self._in_traceback and self._current_block:
                completed = self._parse_block(self._current_block, self._start_line, self._current_end)
            self._in_traceback = True
            self._current_block = [line]
            self._start_line = line_number
            self._current_end = line_number
            return completed

        if self._in_traceback:
            if (
                self.TB_FRAME.match(line)
                or stripped
                or self.TB_EXCEPTION.match(stripped)
                or self.TB_CHAINED.match(stripped)
                or self.JAVA_FRAME.match(line)
                or line.startswith(" ")
            ):
                self._current_block.append(line)
                self._current_end = line_number

                # End of block: exception line detected at end (not a frame or chained)
                if (
                    self.TB_EXCEPTION.match(stripped)
                    and not self.TB_CHAINED.match(stripped)
                    and not self.TB_FRAME.match(line)
                ):
                    block = self._parse_block(self._current_block, self._start_line, line_number)
                    self._in_traceback = False
                    self._current_block = []
                    return block
            else:
                # Blank or unrelated line — close the block
                if self._current_block:
                    block = self._parse_block(self._current_block, self._start_line, self._current_end)
                    self._in_traceback = False
                    self._current_block = []
                    return block

        return None

    def flush(self) -> TracebackBlock | None:
        if self._in_traceback and self._current_block:
            block = self._parse_block(self._current_block, self._start_line, self._current_end)
            self._in_traceback = False
            self._current_block = []
            return block
        return None

    def _parse_block(self, lines: list[str], start: int, end: int) -> TracebackBlock:
        full_text = "\n".join(lines)
        frames = [l for l in lines if self.TB_FRAME.match(l) or self.JAVA_FRAME.match(l)]
        frames = frames[-self.max_frames:]

        exception_type: str | None = None
        exception_message: str | None = None

        # Last non-empty, non-frame line is the exception
        for line in reversed(lines):
            stripped = line.strip()
            if stripped and not self.TB_FRAME.match(line) and not line.startswith("Traceback"):
                m = self.TB_EXCEPTION.match(stripped)
                if m:
                    exc_str = m.group(1)
                    if ":" in exc_str:
                        exception_type, _, exception_message = exc_str.partition(":")
                        exception_type = exception_type.strip()
                        exception_message = exception_message.strip()
                    else:
                        exception_type = exc_str.strip()
                break

        return TracebackBlock(
            start_line=start,
            end_line=end,
            exception_type=exception_type,
            exception_message=exception_message,
            frames=frames,
            full_text=full_text,
        )
