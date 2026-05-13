from __future__ import annotations
import re
from pathlib import Path

from ..context import BranchStatus


class StatusParser:
    _AB = re.compile(r"^# branch\.ab \+(\d+) -(\d+)$")

    def parse(self, raw_status: str, repo_root: Path | None = None) -> BranchStatus:
        current_branch = "(detached HEAD)"
        upstream: str | None = None
        ahead = 0
        behind = 0
        staged_files: list[str] = []
        unstaged_files: list[str] = []
        untracked_files: list[str] = []

        for line in raw_status.splitlines():
            if line.startswith("# branch.head "):
                val = line[len("# branch.head "):]
                if val == "(detached)":
                    current_branch = "(detached HEAD)"
                else:
                    current_branch = val

            elif line.startswith("# branch.upstream "):
                upstream = line[len("# branch.upstream "):]

            elif line.startswith("# branch.ab "):
                m = self._AB.match(line)
                if m:
                    ahead = int(m.group(1))
                    behind = int(m.group(2))

            elif line.startswith("1 ") or line.startswith("2 "):
                # Ordinary or renamed/copied entry
                parts = line.split(" ", 9)
                if len(parts) < 9:
                    continue
                xy = parts[1]
                if line.startswith("2 "):
                    # "2 XY ... score orig\tpath"
                    path_part = parts[9] if len(parts) > 9 else ""
                    # path is after the tab
                    if "\t" in path_part:
                        path = path_part.split("\t", 1)[1]
                    else:
                        path = path_part
                else:
                    path = parts[8] if len(parts) > 8 else ""

                is_staged, is_unstaged = self._parse_xy(xy)
                if is_staged:
                    staged_files.append(path)
                if is_unstaged:
                    unstaged_files.append(path)

            elif line.startswith("? "):
                untracked_files.append(line[2:])

        merge_ip, rebase_ip, cherry_pick_ip = self._check_in_progress(repo_root)

        return BranchStatus(
            current_branch=current_branch,
            upstream=upstream,
            ahead=ahead,
            behind=behind,
            has_staged=bool(staged_files),
            has_unstaged=bool(unstaged_files),
            has_untracked=bool(untracked_files),
            staged_files=staged_files,
            unstaged_files=unstaged_files,
            untracked_files=untracked_files,
            merge_in_progress=merge_ip,
            rebase_in_progress=rebase_ip,
            cherry_pick_in_progress=cherry_pick_ip,
        )

    def _parse_xy(self, xy: str) -> tuple[bool, bool]:
        if len(xy) < 2:
            return False, False
        x, y = xy[0], xy[1]
        is_staged = x not in (".", "?")
        is_unstaged = y not in (".", "?")
        return is_staged, is_unstaged

    def _check_in_progress(self, repo_root: Path | None) -> tuple[bool, bool, bool]:
        if repo_root is None:
            return False, False, False
        git_dir = repo_root / ".git"
        if not git_dir.is_dir():
            return False, False, False
        merge = (git_dir / "MERGE_HEAD").exists()
        rebase = (git_dir / "REBASE_HEAD").exists()
        cherry = (git_dir / "CHERRY_PICK_HEAD").exists()
        return merge, rebase, cherry
