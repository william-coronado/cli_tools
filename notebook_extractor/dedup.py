"""Stream-output deduplication for notebook cell outputs."""
from __future__ import annotations

import re

_WINDOW = 5
_THRESHOLD = 3


def dedup_stream(text: str) -> tuple[str, int]:
    """Return (cleaned_text, suppressed_line_count).

    Two passes:
    1. CR-strip: split on \\r, keep last segment per sequence (tqdm in-place updates).
    2. Consecutive-line suppression: if the same normalized line appears >=3 times
       in a row, suppress the rest.
    """
    text = _cr_strip(text)
    lines = text.splitlines()
    out_lines, suppressed = _suppress_consecutive(lines)
    return "\n".join(out_lines), suppressed


def _cr_strip(text: str) -> str:
    """Handle carriage-return overwriting (tqdm-style progress bars)."""
    result_lines: list[str] = []
    for line in text.split("\n"):
        # Split on \r and keep only the last non-empty segment
        parts = line.split("\r")
        kept = parts[-1] if parts else ""
        result_lines.append(kept)
    return "\n".join(result_lines)


def _normalize(line: str) -> str:
    """Collapse whitespace + strip ANSI + replace digits with '#' for pattern matching."""
    line = re.sub(r"\x1b\[[0-9;]*m", "", line)
    line = re.sub(r"\s+", " ", line).strip()
    line = re.sub(r"\d+", "#", line)
    return line


def _suppress_consecutive(lines: list[str]) -> tuple[list[str], int]:
    out: list[str] = []
    suppressed = 0
    run_norm: str | None = None
    run_count = 0

    for line in lines:
        norm = _normalize(line)
        if norm == run_norm:
            run_count += 1
            if run_count > _THRESHOLD:
                suppressed += 1
                continue
        else:
            run_norm = norm
            run_count = 1
        out.append(line)

    return out, suppressed
