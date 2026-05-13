from __future__ import annotations


def truncate_text(content: str, max_lines: int = 50) -> tuple[str, int, int]:
    """Returns (preview, total_lines, suppressed_lines)."""
    lines = content.splitlines()
    total = len(lines)
    if total <= max_lines:
        return content, total, 0
    preview = "\n".join(lines[:max_lines])
    return preview, total, total - max_lines
