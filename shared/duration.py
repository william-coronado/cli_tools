from __future__ import annotations
import re


def age_human(timestamp: float, now: float) -> str:
    delta = now - timestamp
    if delta < 60:
        return "just now"
    if delta < 3_600:
        return f"{int(delta / 60)}m"
    if delta < 86_400:
        return f"{int(delta / 3_600)}h"
    if delta < 86_400 * 7:
        return f"{int(delta / 86_400)}d"
    if delta < 86_400 * 28:
        return f"{int(delta / (86_400 * 7))}w"
    if delta < 86_400 * 365:
        return f"{int(delta / (86_400 * 30))}mo"
    return f"{int(delta / (86_400 * 365))}y"


def parse_duration(s: str) -> int:
    """Parse duration string to seconds. Handles: 30m, 24h, 7d, 2w, 1mo, 1y"""
    m = re.match(r"^(\d+)(m|h|d|w|mo|y)$", s.strip())
    if not m:
        raise ValueError(
            f"Cannot parse duration: {s!r}. Use e.g. '30d', '7d', '24h', '2w', '1mo'"
        )
    n = int(m.group(1))
    unit = m.group(2)
    secs = {"m": 60, "h": 3600, "d": 86400, "w": 604800, "mo": 2_592_000, "y": 31_536_000}
    return n * secs[unit]
