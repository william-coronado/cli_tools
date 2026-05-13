from __future__ import annotations
import time
from dataclasses import dataclass, field
from pathlib import Path

from shared.duration import age_human, parse_duration


# ── Data Models ────────────────────────────────────────────────────────────────

@dataclass
class Commit:
    hash: str
    short_hash: str
    author_name: str
    author_email: str
    timestamp: str          # ISO 8601
    age_human: str
    subject: str
    body: str | None
    files_changed: list[str]
    insertions: int
    deletions: int


@dataclass
class DiffLine:
    type: str               # "context" | "added" | "removed"
    content: str
    line_number_old: int | None
    line_number_new: int | None


@dataclass
class DiffHunk:
    file_path: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str | None
    lines: list[DiffLine]


@dataclass
class FileDiff:
    path: str
    old_path: str | None
    status: str             # "modified" | "added" | "deleted" | "renamed" | "copied" | "untracked"
    insertions: int
    deletions: int
    is_binary: bool
    hunks: list[DiffHunk]
    staged: bool | None = None   # Set in uncommitted diff context


@dataclass
class BlameEntry:
    line_number: int
    content: str
    commit_hash: str
    short_hash: str
    author_name: str
    timestamp: str
    age_human: str
    subject: str


@dataclass
class AuthorContribution:
    name: str
    email: str
    line_count: int
    percentage: float
    most_recent_commit: str
    most_recent_date: str


@dataclass
class AgeDistribution:
    last_week: int
    last_month: int
    last_quarter: int
    last_year: int
    older: int


@dataclass
class BlameSummary:
    file_path: str
    total_lines: int
    authors: list[AuthorContribution]
    age_distribution: AgeDistribution
    recent_changes: list[BlameEntry]


@dataclass
class BranchStatus:
    current_branch: str
    upstream: str | None
    ahead: int
    behind: int
    has_staged: bool
    has_unstaged: bool
    has_untracked: bool
    staged_files: list[str]
    unstaged_files: list[str]
    untracked_files: list[str]
    merge_in_progress: bool
    rebase_in_progress: bool
    cherry_pick_in_progress: bool


@dataclass
class RepoContext:
    root_path: str
    branch_status: BranchStatus
    recent_commits: list[Commit]
    active_files: list[str]
    uncommitted_diff: list[FileDiff]
    stash_count: int
    tag_on_head: str | None


@dataclass
class FileContext:
    file_path: str
    repo_root: str
    current_branch: str
    recent_commits: list[Commit]
    diff_vs_base: list[FileDiff]
    blame_summary: BlameSummary | None
    related_files: list[str]


# ── Orchestrator ───────────────────────────────────────────────────────────────

class GitContextExtractor:
    def __init__(
        self,
        repo_path: str | Path,
        max_commits: int = 10,
        max_diff_lines: int = 200,
        diff_context_lines: int = 3,
        blame_recent_window: str = "30d",
        max_blame_entries: int = 20,
        max_related_files: int = 5,
        verbose: bool = False,
    ):
        from .git_runner import GitRunner
        self._runner = GitRunner(Path(repo_path))
        self.max_commits = max_commits
        self.max_diff_lines = max_diff_lines
        self.diff_context_lines = diff_context_lines
        self.blame_recent_window_seconds = parse_duration(blame_recent_window)
        self.max_blame_entries = max_blame_entries
        self.max_related_files = max_related_files
        self.verbose = verbose

    # ── File Mode ──────────────────────────────────────────────────────────────

    def get_file_context(
        self,
        file_path: str | Path,
        base: str | None = None,
        skip_blame: bool = False,
        skip_diff: bool = False,
        skip_related: bool = False,
    ) -> FileContext:
        from .git_runner import FileNotTrackedError

        repo_root = self._runner.get_repo_root()
        abs_path = Path(file_path).resolve()
        try:
            rel_path = str(abs_path.relative_to(repo_root))
        except ValueError:
            rel_path = str(file_path)

        if not self._runner.file_exists_in_git(rel_path):
            raise FileNotTrackedError(
                f"File is not tracked by git: {rel_path}",
                command=["git", "ls-files", "--error-unmatch", rel_path],
                returncode=1,
            )

        resolved_base = base or self._resolve_base()
        commits = self._get_file_commits(rel_path)
        diffs = [] if skip_diff else self._get_file_diff(rel_path, resolved_base)
        blame = None if skip_blame else self._get_blame_summary(rel_path)
        related = [] if skip_related else self._get_related_files(rel_path, commits)

        branch = self._runner.run("rev-parse", "--abbrev-ref", "HEAD").strip()

        return FileContext(
            file_path=rel_path,
            repo_root=str(repo_root),
            current_branch=branch,
            recent_commits=commits,
            diff_vs_base=diffs,
            blame_summary=blame,
            related_files=related,
        )

    def _get_file_commits(self, rel_path: str) -> list[Commit]:
        from .parsers.log_parser import LogParser

        raw = self._runner.run(
            "log",
            f"--format={LogParser.LOG_FORMAT}",
            "--name-only",
            "--stat",
            f"-n{self.max_commits}",
            "--",
            rel_path,
        )
        return LogParser().parse(raw)

    def _get_file_diff(self, rel_path: str, base: str) -> list[FileDiff]:
        from .git_runner import GitError
        from .parsers.diff_parser import DiffParser

        try:
            raw = self._runner.run(
                "diff",
                f"-U{self.diff_context_lines}",
                f"{base}...HEAD",
                "--",
                rel_path,
            )
        except GitError:
            raw = self._runner.run(
                "diff",
                f"-U{self.diff_context_lines}",
                "HEAD",
                "--",
                rel_path,
            )

        parser = DiffParser()
        diffs = parser.parse(raw)
        return self._truncate_diffs(diffs)

    def _get_blame_summary(self, rel_path: str) -> BlameSummary | None:
        from .git_runner import GitError
        from .parsers.blame_parser import BlameParser

        try:
            raw = self._runner.run("blame", "--porcelain", "--", rel_path)
        except GitError:
            return None

        if not raw.strip():
            return None

        parser = BlameParser()
        try:
            entries = parser.parse(raw)
        except Exception:
            return None

        if not entries:
            return None

        return parser.summarize(
            entries,
            file_path=rel_path,
            recent_window_seconds=self.blame_recent_window_seconds,
            max_recent=self.max_blame_entries,
        )  # now=None → uses time.time() which is fine for production

    def _get_related_files(self, rel_path: str, commits: list[Commit]) -> list[str]:
        from collections import Counter

        counts: Counter[str] = Counter()
        for commit in commits:
            for f in commit.files_changed:
                if f != rel_path:
                    counts[f] += 1

        return [f for f, _ in counts.most_common(self.max_related_files)]

    # ── Repo Mode ─────────────────────────────────────────────────────────────

    def get_repo_context(self, skip_diff: bool = False) -> RepoContext:
        from .git_runner import GitError

        repo_root = self._runner.get_repo_root()
        branch_status = self._get_branch_status()
        recent_commits = self._get_recent_commits()

        active_files: dict[str, int] = {}
        for commit in recent_commits:
            for f in commit.files_changed:
                active_files[f] = active_files.get(f, 0) + 1
        sorted_active = sorted(active_files, key=lambda f: -active_files[f])

        uncommitted = [] if skip_diff else self._get_uncommitted_diff()

        stash_count = self._get_stash_count()

        try:
            tag = self._runner.run("describe", "--exact-match", "--tags", "HEAD", check=False).strip()
        except GitError:
            tag = None
        if not tag:
            tag = None

        return RepoContext(
            root_path=str(repo_root),
            branch_status=branch_status,
            recent_commits=recent_commits,
            active_files=sorted_active,
            uncommitted_diff=uncommitted,
            stash_count=stash_count,
            tag_on_head=tag,
        )

    def _get_branch_status(self) -> BranchStatus:
        from .parsers.status_parser import StatusParser

        raw = self._runner.run("status", "--porcelain=v2", "--branch")
        repo_root = self._runner.get_repo_root()
        return StatusParser().parse(raw, repo_root=repo_root)

    def _get_recent_commits(self) -> list[Commit]:
        from .parsers.log_parser import LogParser

        raw = self._runner.run(
            "log",
            f"--format={LogParser.LOG_FORMAT}",
            "--name-only",
            "--stat",
            f"-n{self.max_commits}",
        )
        return LogParser().parse(raw)

    def _get_uncommitted_diff(self) -> list[FileDiff]:
        from .parsers.diff_parser import DiffParser

        parser = DiffParser()

        raw_cached = self._runner.run("diff", "--cached", check=False)
        staged_diffs = parser.parse(raw_cached)
        staged_paths = {d.path for d in staged_diffs}
        for d in staged_diffs:
            d.staged = True
            if d.status == "modified":
                d.status = "modified (staged)"

        raw_head = self._runner.run("diff", "HEAD", check=False)
        all_diffs = parser.parse(raw_head)

        unstaged = []
        for d in all_diffs:
            if d.path not in staged_paths:
                d.staged = False
                if d.status == "modified":
                    d.status = "modified (unstaged)"
                unstaged.append(d)

        return staged_diffs + unstaged

    def _get_stash_count(self) -> int:
        raw = self._runner.run("stash", "list", check=False)
        return len([l for l in raw.splitlines() if l.strip()])

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _resolve_base(self, file_path: str | None = None) -> str:
        from .git_runner import GitError

        # 1. Try merge-base with upstream
        try:
            base = self._runner.run("merge-base", "HEAD", "@{u}", check=False).strip()
            if base:
                return base
        except GitError:
            pass

        # 2. Try default branch (if different from current)
        try:
            current = self._runner.run("rev-parse", "--abbrev-ref", "HEAD").strip()
            default = self._runner.get_default_branch()
            if default and default != current:
                # Verify it exists
                result = self._runner.run("rev-parse", "--verify", default, check=False).strip()
                if result:
                    return default
        except GitError:
            pass

        # 3. Fall back to HEAD~1
        return "HEAD~1"

    def _truncate_diffs(self, diffs: list[FileDiff]) -> list[FileDiff]:
        total = 0
        result = []
        for d in diffs:
            line_count = sum(len(h.lines) for h in d.hunks)
            if total + line_count > self.max_diff_lines:
                remaining = self.max_diff_lines - total
                # Truncate hunks
                truncated_hunks = []
                hunk_lines_used = 0
                for hunk in d.hunks:
                    if hunk_lines_used >= remaining:
                        break
                    if hunk_lines_used + len(hunk.lines) <= remaining:
                        truncated_hunks.append(hunk)
                        hunk_lines_used += len(hunk.lines)
                    else:
                        # Partial hunk
                        from dataclasses import replace
                        partial = DiffHunk(
                            file_path=hunk.file_path,
                            old_start=hunk.old_start,
                            old_count=hunk.old_count,
                            new_start=hunk.new_start,
                            new_count=hunk.new_count,
                            header=hunk.header,
                            lines=hunk.lines[: remaining - hunk_lines_used],
                        )
                        truncated_hunks.append(partial)
                        hunk_lines_used = remaining
                        break
                truncated = FileDiff(
                    path=d.path,
                    old_path=d.old_path,
                    status=d.status + " [truncated]",
                    insertions=d.insertions,
                    deletions=d.deletions,
                    is_binary=d.is_binary,
                    hunks=truncated_hunks,
                    staged=d.staged,
                )
                result.append(truncated)
                break
            result.append(d)
            total += line_count
        return result
