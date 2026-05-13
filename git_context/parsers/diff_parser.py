from __future__ import annotations
import re

from ..context import FileDiff, DiffHunk, DiffLine


class DiffParser:
    DIFF_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")
    HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
    RENAME_FROM = re.compile(r"^rename from (.+)$")
    RENAME_TO = re.compile(r"^rename to (.+)$")
    BINARY_LINE = re.compile(r"^Binary files .+ differ$")

    def parse(self, raw_diff: str) -> list[FileDiff]:
        diffs: list[FileDiff] = []
        if not raw_diff.strip():
            return diffs

        lines = raw_diff.split("\n")
        i = 0

        while i < len(lines):
            m = self.DIFF_HEADER.match(lines[i])
            if not m:
                i += 1
                continue

            b_path = m.group(2)
            old_path: str | None = None
            status = "modified"
            is_binary = False
            hunks: list[DiffHunk] = []
            insertions = 0
            deletions = 0
            i += 1

            while i < len(lines):
                line = lines[i]

                if self.DIFF_HEADER.match(line):
                    break

                rm = self.RENAME_FROM.match(line)
                if rm:
                    old_path = rm.group(1)
                    status = "renamed"
                    i += 1
                    continue

                rt = self.RENAME_TO.match(line)
                if rt:
                    b_path = rt.group(1)
                    i += 1
                    continue

                if self.BINARY_LINE.match(line):
                    is_binary = True
                    i += 1
                    continue

                if line.startswith("new file mode"):
                    status = "added"
                    i += 1
                    continue

                if line.startswith("deleted file mode"):
                    status = "deleted"
                    i += 1
                    continue

                hm = self.HUNK_HEADER.match(line)
                if hm:
                    hunk_lines: list[str] = []
                    i += 1
                    while i < len(lines):
                        if self.HUNK_HEADER.match(lines[i]) or self.DIFF_HEADER.match(lines[i]):
                            break
                        hunk_lines.append(lines[i])
                        i += 1
                    hunk = self._parse_hunk(hm, b_path, hunk_lines)
                    hunks.append(hunk)
                    insertions += sum(1 for dl in hunk.lines if dl.type == "added")
                    deletions += sum(1 for dl in hunk.lines if dl.type == "removed")
                    continue

                i += 1

            diffs.append(FileDiff(
                path=b_path,
                old_path=old_path,
                status=status,
                insertions=insertions,
                deletions=deletions,
                is_binary=is_binary,
                hunks=hunks,
            ))

        return diffs

    def _parse_hunk(
        self,
        header_match: re.Match,
        file_path: str,
        hunk_lines: list[str],
    ) -> DiffHunk:
        old_start = int(header_match.group(1))
        old_count = int(header_match.group(2) if header_match.group(2) is not None else 1)
        new_start = int(header_match.group(3))
        new_count = int(header_match.group(4) if header_match.group(4) is not None else 1)
        header_text = header_match.group(5).strip() or None

        diff_lines: list[DiffLine] = []
        old_ln = old_start
        new_ln = new_start

        for line in hunk_lines:
            if not line:
                # Empty line within hunk — treat as context
                diff_lines.append(DiffLine(
                    type="context",
                    content="",
                    line_number_old=old_ln,
                    line_number_new=new_ln,
                ))
                old_ln += 1
                new_ln += 1
                continue

            prefix = line[0]
            content = line[1:]

            if prefix == "+":
                diff_lines.append(DiffLine(
                    type="added",
                    content=content,
                    line_number_old=None,
                    line_number_new=new_ln,
                ))
                new_ln += 1
            elif prefix == "-":
                diff_lines.append(DiffLine(
                    type="removed",
                    content=content,
                    line_number_old=old_ln,
                    line_number_new=None,
                ))
                old_ln += 1
            elif prefix == " ":
                diff_lines.append(DiffLine(
                    type="context",
                    content=content,
                    line_number_old=old_ln,
                    line_number_new=new_ln,
                ))
                old_ln += 1
                new_ln += 1
            elif prefix == "\\":
                # "\ No newline at end of file"
                pass

        return DiffHunk(
            file_path=file_path,
            old_start=old_start,
            old_count=old_count,
            new_start=new_start,
            new_count=new_count,
            header=header_text,
            lines=diff_lines,
        )

    def parse_stat(self, raw_stat: str) -> dict[str, tuple[int, int]]:
        result: dict[str, tuple[int, int]] = {}
        for line in raw_stat.splitlines():
            m = re.match(r"^\s*(.+?)\s*\|\s*(\d+)\s*([+\-]*)$", line)
            if m:
                path = m.group(1).strip()
                changes = m.group(3)
                result[path] = (changes.count("+"), changes.count("-"))
        return result

    def summarize(self, diffs: list[FileDiff]) -> str:
        total_ins = sum(d.insertions for d in diffs)
        total_del = sum(d.deletions for d in diffs)
        n = len(diffs)
        files_str = f"{n} file{'s' if n != 1 else ''} changed"
        paths = [d.path for d in diffs]
        paths_preview = ", ".join(paths[:3])
        if len(paths) > 3:
            paths_preview += ", ..."
        return f"{files_str}: +{total_ins} -{total_del}  [{paths_preview}]"
