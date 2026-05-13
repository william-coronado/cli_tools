from __future__ import annotations
import re
import time
from datetime import datetime, timezone

from shared.duration import age_human as _age_human
from ..context import Commit, AuthorContribution


class LogParser:
    LOG_FORMAT = (
        "%x00"
        "%H%x1f"
        "%h%x1f"
        "%an%x1f"
        "%ae%x1f"
        "%aI%x1f"
        "%s%x1f"
        "%b"
    )

    _STAT_SUMMARY = re.compile(
        r"^\s+(\d+) files? changed"
        r"(?:,\s*(\d+) insertions?\(\+\))?"
        r"(?:,\s*(\d+) deletions?\(-\))?",
    )

    def parse(self, raw_output: str, now: float | None = None) -> list[Commit]:
        if now is None:
            now = time.time()

        commits = []
        records = raw_output.split("\x00")

        for record in records:
            if not record.strip():
                continue

            parts = record.split("\x1f", maxsplit=6)
            if len(parts) < 6:
                continue

            hash_ = parts[0].strip()
            short_hash = parts[1].strip()
            author_name = parts[2].strip()
            author_email = parts[3].strip()
            timestamp_iso = parts[4].strip()
            subject = parts[5].strip()
            tail = parts[6] if len(parts) > 6 else ""

            body, files_changed, insertions, deletions = self._parse_tail(tail)

            try:
                ts = datetime.fromisoformat(timestamp_iso).timestamp()
            except (ValueError, OSError):
                ts = now

            commits.append(Commit(
                hash=hash_,
                short_hash=short_hash,
                author_name=author_name,
                author_email=author_email,
                timestamp=timestamp_iso,
                age_human=_age_human(ts, now),
                subject=subject,
                body=body if body else None,
                files_changed=files_changed,
                insertions=insertions,
                deletions=deletions,
            ))

        return commits

    def _parse_tail(self, tail: str) -> tuple[str | None, list[str], int, int]:
        """Parse the body + name-only file list + stat from the tail of a record."""
        lines = tail.split("\n")

        # Find stat summary line from the end
        stat_idx = None
        for i in range(len(lines) - 1, -1, -1):
            if self._STAT_SUMMARY.match(lines[i]):
                stat_idx = i
                break

        if stat_idx is None:
            # No stat found — body is everything, no files, no counts
            body = tail.strip() or None
            return body, [], 0, 0

        insertions, deletions = self._parse_stat_line(lines[stat_idx])

        # File list: continuous non-empty lines immediately before the stat
        # (there is a blank line between files and stat)
        file_end = stat_idx - 1
        while file_end >= 0 and not lines[file_end].strip():
            file_end -= 1

        file_start = file_end
        while file_start > 0 and lines[file_start - 1].strip():
            file_start -= 1

        files = [lines[i].strip() for i in range(file_start, file_end + 1) if lines[i].strip()]

        # Body is everything before the file list
        body_lines = lines[:file_start]
        body = "\n".join(body_lines).strip() or None

        return body, files, insertions, deletions

    def _parse_stat_line(self, line: str) -> tuple[int, int]:
        m = self._STAT_SUMMARY.match(line)
        if not m:
            return 0, 0
        insertions = int(m.group(2) or 0)
        deletions = int(m.group(3) or 0)
        return insertions, deletions

    def parse_shortlog(self, raw_output: str) -> list[AuthorContribution]:
        entries = []
        for line in raw_output.splitlines():
            line = line.strip()
            if not line:
                continue
            # Format: "  42\tAuthor Name <email@example.com>"
            m = re.match(r"^(\d+)\t(.+?)\s+<([^>]+)>$", line)
            if m:
                entries.append(AuthorContribution(
                    name=m.group(2).strip(),
                    email=m.group(3).strip(),
                    line_count=int(m.group(1)),
                    percentage=0.0,
                    most_recent_commit="",
                    most_recent_date="",
                ))
        return entries
