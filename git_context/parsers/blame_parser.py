from __future__ import annotations
import re
import time
from collections import defaultdict
from datetime import datetime, timezone

from shared.duration import age_human as _age_human
from ..context import (
    AgeDistribution,
    AuthorContribution,
    BlameEntry,
    BlameSummary,
)


class BlameParser:
    _HASH_LINE = re.compile(r"^([0-9a-f]{40}) \d+ (\d+)")

    def parse(self, raw_blame: str, now: float | None = None) -> list[BlameEntry]:
        if now is None:
            now = time.time()

        entries: list[BlameEntry] = []
        # commit_hash -> {author, author_email, timestamp, subject}
        commit_cache: dict[str, dict] = {}
        current_hash: str | None = None
        current_final_line: int = 0

        for line in raw_blame.splitlines():
            hm = self._HASH_LINE.match(line)
            if hm:
                current_hash = hm.group(1)
                current_final_line = int(hm.group(2))
                if current_hash not in commit_cache:
                    commit_cache[current_hash] = {}
                continue

            if current_hash is None:
                continue

            meta = commit_cache[current_hash]

            if line.startswith("author ") and not line.startswith("author-"):
                meta["author"] = line[7:]
            elif line.startswith("author-mail "):
                meta["author_email"] = line[12:].strip().strip("<>")
            elif line.startswith("author-time "):
                meta["timestamp"] = int(line[12:].strip())
            elif line.startswith("summary "):
                meta["subject"] = line[8:]
            elif line.startswith("\t"):
                content = line[1:]
                ts = meta.get("timestamp", 0)
                try:
                    iso_ts = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                except (OSError, ValueError, OverflowError):
                    iso_ts = ""

                entries.append(BlameEntry(
                    line_number=current_final_line,
                    content=content,
                    commit_hash=current_hash,
                    short_hash=current_hash[:8],
                    author_name=meta.get("author", ""),
                    timestamp=iso_ts,
                    age_human=_age_human(ts, now),
                    subject=meta.get("subject", ""),
                ))

        return entries

    def summarize(
        self,
        entries: list[BlameEntry],
        file_path: str,
        recent_window_seconds: int = 86_400 * 30,
        max_recent: int = 20,
        now: float | None = None,
    ) -> BlameSummary:
        total = len(entries)
        if now is None:
            now = time.time()

        # Author aggregation
        author_lines: dict[str, list[BlameEntry]] = defaultdict(list)
        for e in entries:
            author_lines[e.author_name].append(e)

        author_contribs: list[AuthorContribution] = []
        for name, author_entries in author_lines.items():
            most_recent = max(author_entries, key=lambda e: e.timestamp)
            author_contribs.append(AuthorContribution(
                name=name,
                email="",
                line_count=len(author_entries),
                percentage=round(len(author_entries) / total * 100, 1) if total else 0.0,
                most_recent_commit=most_recent.short_hash,
                most_recent_date=most_recent.timestamp,
            ))
        author_contribs.sort(key=lambda a: -a.line_count)

        # Age distribution
        week_s = 86_400 * 7
        month_s = 86_400 * 30
        quarter_s = 86_400 * 91
        year_s = 86_400 * 365

        dist = AgeDistribution(
            last_week=0, last_month=0, last_quarter=0, last_year=0, older=0
        )
        for e in entries:
            try:
                ts = datetime.fromisoformat(e.timestamp).timestamp()
            except (ValueError, OSError):
                dist.older += 1
                continue
            delta = now - ts
            if delta <= week_s:
                dist.last_week += 1
            elif delta <= month_s:
                dist.last_month += 1
            elif delta <= quarter_s:
                dist.last_quarter += 1
            elif delta <= year_s:
                dist.last_year += 1
            else:
                dist.older += 1

        # Recent changes
        recent: list[BlameEntry] = []
        for e in entries:
            try:
                ts = datetime.fromisoformat(e.timestamp).timestamp()
            except (ValueError, OSError):
                continue
            if (now - ts) <= recent_window_seconds:
                recent.append(e)
        recent.sort(key=lambda e: e.timestamp, reverse=True)
        recent = recent[:max_recent]

        return BlameSummary(
            file_path=file_path,
            total_lines=total,
            authors=author_contribs,
            age_distribution=dist,
            recent_changes=recent,
        )
