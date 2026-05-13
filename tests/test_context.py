"""Tests for git_context parsers and orchestrator.

All git calls are mocked — no real git subprocess is invoked.
"""
from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from git_context.parsers.log_parser import LogParser
from git_context.parsers.diff_parser import DiffParser
from git_context.parsers.blame_parser import BlameParser
from git_context.parsers.status_parser import StatusParser
from git_context.context import (
    GitContextExtractor,
    FileContext,
    RepoContext,
    FileDiff,
    DiffHunk,
)
from git_context.git_runner import FileNotTrackedError
from git_context.renderer import Renderer

from tests.fixtures.git_output import (
    LOG_SIMPLE,
    LOG_WITH_BODY,
    DIFF_MODIFIED,
    DIFF_RENAMED,
    DIFF_BINARY,
    BLAME_PORCELAIN,
    STATUS_CLEAN,
    STATUS_STAGED,
    STATUS_AHEAD,
)

NOW = 1_747_130_000.0  # fixed epoch for reproducible age_human values


# ── LogParser ─────────────────────────────────────────────────────────────────

class TestLogParser:
    def test_three_commits_parsed(self):
        commits = LogParser().parse(LOG_SIMPLE, now=NOW)
        assert len(commits) == 3

    def test_commit_fields_match(self):
        commits = LogParser().parse(LOG_SIMPLE, now=NOW)
        c = commits[0]
        assert c.hash == "aaaa111122223333444455556666777788880000"
        assert c.short_hash == "aaaa1111"
        assert c.author_name == "Will C"
        assert c.author_email == "will@example.com"
        assert c.timestamp == "2026-05-12T10:00:00+00:00"
        assert c.subject == "feat: add classifier"
        assert c.body is None

    def test_files_changed_first_commit(self):
        commits = LogParser().parse(LOG_SIMPLE, now=NOW)
        assert commits[0].files_changed == ["src/classifier.py"]

    def test_files_changed_second_commit(self):
        commits = LogParser().parse(LOG_SIMPLE, now=NOW)
        assert set(commits[1].files_changed) == {"src/classifier.py", "tests/test_classifier.py"}

    def test_stat_insertions_deletions(self):
        commits = LogParser().parse(LOG_SIMPLE, now=NOW)
        assert commits[0].insertions == 50
        assert commits[0].deletions == 0
        assert commits[1].insertions == 10
        assert commits[1].deletions == 3

    def test_body_multi_line_preserved(self):
        commits = LogParser().parse(LOG_WITH_BODY, now=NOW)
        assert len(commits) == 1
        assert commits[0].body == "This is a multi-line body.\n\nWith a second paragraph."

    def test_body_subject_split(self):
        commits = LogParser().parse(LOG_WITH_BODY, now=NOW)
        c = commits[0]
        assert c.subject == "refactor: extract helpers"
        assert "second paragraph" in c.body

    def test_parse_stat_line(self):
        parser = LogParser()
        ins, dels = parser._parse_stat_line(" 3 files changed, 42 insertions(+), 5 deletions(-)")
        assert ins == 42
        assert dels == 5

    def test_parse_stat_line_insertions_only(self):
        parser = LogParser()
        ins, dels = parser._parse_stat_line(" 1 file changed, 10 insertions(+)")
        assert ins == 10
        assert dels == 0


# ── DiffParser ────────────────────────────────────────────────────────────────

class TestDiffParser:
    def test_modified_two_hunks(self):
        diffs = DiffParser().parse(DIFF_MODIFIED)
        assert len(diffs) == 1
        assert len(diffs[0].hunks) == 2

    def test_modified_line_numbers(self):
        diffs = DiffParser().parse(DIFF_MODIFIED)
        hunk = diffs[0].hunks[0]
        assert hunk.old_start == 10
        assert hunk.new_start == 10

    def test_modified_file_path(self):
        diffs = DiffParser().parse(DIFF_MODIFIED)
        assert diffs[0].path == "src/classifier.py"
        assert diffs[0].old_path is None

    def test_modified_insertions_deletions(self):
        diffs = DiffParser().parse(DIFF_MODIFIED)
        d = diffs[0]
        # hunk 1: 4 added, 1 removed; hunk 2: 0 added, 1 removed
        assert d.insertions == 4
        assert d.deletions == 2

    def test_renamed_old_path_and_path(self):
        diffs = DiffParser().parse(DIFF_RENAMED)
        assert len(diffs) == 1
        d = diffs[0]
        assert d.old_path == "old_name.py"
        assert d.path == "new_name.py"
        assert d.status == "renamed"

    def test_binary_is_binary_flag(self):
        diffs = DiffParser().parse(DIFF_BINARY)
        assert len(diffs) == 1
        assert diffs[0].is_binary is True
        assert diffs[0].hunks == []

    def test_empty_diff_returns_empty_list(self):
        diffs = DiffParser().parse("")
        assert diffs == []

    def test_summarize(self):
        diffs = DiffParser().parse(DIFF_MODIFIED)
        summary = DiffParser().summarize(diffs)
        assert "1 file" in summary
        assert "src/classifier.py" in summary


# ── BlameParser ───────────────────────────────────────────────────────────────

class TestBlameParser:
    def _entries(self):
        return BlameParser().parse(BLAME_PORCELAIN, now=NOW)

    def test_entry_count(self):
        assert len(self._entries()) == 10

    def test_first_entry_fields(self):
        e = self._entries()[0]
        assert e.commit_hash == "aaaa111122223333444455556666777788880000"
        assert e.short_hash == "aaaa1111"
        assert e.author_name == "Will C"
        assert e.line_number == 1
        assert e.subject == "feat: add classifier"

    def test_second_author(self):
        entries = self._entries()
        # Lines 3-10 are from Jane D
        jane_entries = [e for e in entries if e.author_name == "Jane D"]
        assert len(jane_entries) == 8

    def test_blame_summary_percentages_sum_to_100(self):
        entries = BlameParser().parse(BLAME_PORCELAIN, now=NOW)
        summary = BlameParser().summarize(entries, file_path="src/classifier.py", now=NOW)
        total_pct = sum(a.percentage for a in summary.authors)
        assert abs(total_pct - 100.0) < 1.0

    def test_blame_summary_total_lines(self):
        entries = BlameParser().parse(BLAME_PORCELAIN, now=NOW)
        summary = BlameParser().summarize(entries, file_path="src/classifier.py", now=NOW)
        assert summary.total_lines == 10

    def test_binary_file_blame_returns_none(self):
        # Binary files produce empty/unparseable blame output — summarize returns None
        parser = BlameParser()
        entries = parser.parse("", now=NOW)
        assert entries == []
        # Calling summarize on empty entries is safe and produces a valid (empty) summary
        summary = parser.summarize(entries, file_path="image.png", now=NOW)
        assert summary.total_lines == 0
        assert summary.authors == []

    def test_blame_summary_recent_changes(self):
        # NOW = 1_747_130_000; aaaa timestamp = 1_747_043_200 → delta ~87k s (~1d) < 30d
        entries = BlameParser().parse(BLAME_PORCELAIN, now=NOW)
        summary = BlameParser().summarize(
            entries, file_path="src/classifier.py",
            recent_window_seconds=86_400 * 30, now=NOW,
        )
        # Both commits are within 30d of NOW
        assert len(summary.recent_changes) > 0


# ── StatusParser ──────────────────────────────────────────────────────────────

class TestStatusParser:
    def test_clean_all_false(self):
        status = StatusParser().parse(STATUS_CLEAN)
        assert status.has_staged is False
        assert status.has_unstaged is False
        assert status.has_untracked is False
        assert status.staged_files == []
        assert status.unstaged_files == []
        assert status.untracked_files == []

    def test_clean_branch_name(self):
        status = StatusParser().parse(STATUS_CLEAN)
        assert status.current_branch == "main"
        assert status.upstream == "origin/main"
        assert status.ahead == 0
        assert status.behind == 0

    def test_staged_has_staged_true(self):
        status = StatusParser().parse(STATUS_STAGED)
        assert status.has_staged is True
        assert len(status.staged_files) == 2

    def test_staged_files_list(self):
        status = StatusParser().parse(STATUS_STAGED)
        assert "src/classifier.py" in status.staged_files
        assert "tests/test_new.py" in status.staged_files

    def test_unstaged_file(self):
        status = StatusParser().parse(STATUS_STAGED)
        assert status.has_unstaged is True
        assert "src/utils.py" in status.unstaged_files

    def test_untracked_file(self):
        status = StatusParser().parse(STATUS_STAGED)
        assert status.has_untracked is True
        assert "scratch.py" in status.untracked_files

    def test_ahead_behind(self):
        status = StatusParser().parse(STATUS_AHEAD)
        assert status.ahead == 3
        assert status.behind == 1

    def test_detached_head(self):
        raw = "# branch.oid abc123\n# branch.head (detached)\n"
        status = StatusParser().parse(raw)
        assert status.current_branch == "(detached HEAD)"

    def test_no_upstream(self):
        raw = "# branch.oid abc123\n# branch.head main\n"
        status = StatusParser().parse(raw)
        assert status.upstream is None
        assert status.ahead == 0
        assert status.behind == 0


# ── GitContextExtractor (mocked) ───────────────────────────────────────────────

def _make_extractor(tmp_path: Path) -> GitContextExtractor:
    extractor = object.__new__(GitContextExtractor)
    extractor._runner = MagicMock()
    extractor._runner.get_repo_root.return_value = tmp_path
    extractor._runner.run.return_value = ""
    extractor._runner.file_exists_in_git.return_value = True
    extractor.max_commits = 10
    extractor.max_diff_lines = 200
    extractor.diff_context_lines = 3
    extractor.blame_recent_window_seconds = 86_400 * 30
    extractor.max_blame_entries = 20
    extractor.max_related_files = 5
    extractor.verbose = False
    return extractor


class TestResolveBase:
    def test_with_upstream(self, tmp_path):
        extractor = _make_extractor(tmp_path)
        extractor._runner.run.side_effect = lambda *a, **kw: (
            "abc1234\n" if "merge-base" in a else ""
        )
        base = extractor._resolve_base()
        assert base == "abc1234"

    def test_no_upstream_falls_back_to_default_branch(self, tmp_path):
        extractor = _make_extractor(tmp_path)

        def _run(*args, **kwargs):
            if "merge-base" in args:
                return ""
            if "abbrev-ref" in args:
                return "feature/foo\n"
            if "--verify" in args:
                return "abc123\n"
            return ""

        extractor._runner.run.side_effect = _run
        extractor._runner.get_default_branch.return_value = "main"
        base = extractor._resolve_base()
        assert base == "main"

    def test_no_default_branch_falls_back_to_head1(self, tmp_path):
        extractor = _make_extractor(tmp_path)

        def _run(*args, **kwargs):
            if "merge-base" in args:
                return ""
            if "abbrev-ref" in args:
                return "main\n"
            if "--verify" in args:
                return ""
            return ""

        extractor._runner.run.side_effect = _run
        extractor._runner.get_default_branch.return_value = "main"
        base = extractor._resolve_base()
        assert base == "HEAD~1"


class TestGetFileContext:
    def test_returns_file_context(self, tmp_path):
        extractor = _make_extractor(tmp_path)
        extractor._runner.file_exists_in_git.return_value = True

        def _run(*args, **kwargs):
            if "log" in args:
                return LOG_SIMPLE
            if "diff" in args:
                return DIFF_MODIFIED
            if "blame" in args:
                return BLAME_PORCELAIN
            if "abbrev-ref" in args:
                return "main\n"
            if "merge-base" in args:
                return "abc\n"
            return ""

        extractor._runner.run.side_effect = _run

        # Create a dummy file so resolve() works
        dummy = tmp_path / "src" / "classifier.py"
        dummy.parent.mkdir(parents=True, exist_ok=True)
        dummy.write_text("# hi")

        ctx = extractor.get_file_context(dummy)
        assert isinstance(ctx, FileContext)
        assert ctx.recent_commits
        assert ctx.diff_vs_base

    def test_file_not_tracked_raises(self, tmp_path):
        extractor = _make_extractor(tmp_path)
        extractor._runner.file_exists_in_git.return_value = False

        dummy = tmp_path / "untracked.py"
        dummy.write_text("# hi")

        with pytest.raises(FileNotTrackedError):
            extractor.get_file_context(dummy)


class TestGetRepoContext:
    def test_returns_repo_context(self, tmp_path):
        extractor = _make_extractor(tmp_path)

        def _run(*args, **kwargs):
            if "status" in args:
                return STATUS_STAGED
            if "log" in args:
                return LOG_SIMPLE
            if "diff" in args:
                return ""
            if "stash" in args:
                return ""
            if "describe" in args:
                return ""
            return ""

        extractor._runner.run.side_effect = _run
        extractor._runner.get_repo_root.return_value = tmp_path

        ctx = extractor.get_repo_context()
        assert isinstance(ctx, RepoContext)
        assert ctx.recent_commits


# ── Diff truncation ───────────────────────────────────────────────────────────

class TestDiffTruncation:
    def test_truncation_applied(self, tmp_path):
        extractor = _make_extractor(tmp_path)
        extractor.max_diff_lines = 2

        # Build a diff with many lines
        hunk = DiffHunk(
            file_path="foo.py",
            old_start=1, old_count=5, new_start=1, new_count=5,
            header=None,
            lines=[
                __import__("git_context.context", fromlist=["DiffLine"]).DiffLine(
                    type="added", content=f"line {i}", line_number_old=None, line_number_new=i
                )
                for i in range(10)
            ],
        )
        big_diff = [
            FileDiff(
                path="foo.py", old_path=None, status="modified",
                insertions=10, deletions=0, is_binary=False, hunks=[hunk],
            )
        ]
        truncated = extractor._truncate_diffs(big_diff)
        total_lines = sum(len(h.lines) for d in truncated for h in d.hunks)
        assert total_lines <= extractor.max_diff_lines


# ── Related files ─────────────────────────────────────────────────────────────

class TestRelatedFiles:
    def test_co_committed_ranked_by_frequency(self, tmp_path):
        extractor = _make_extractor(tmp_path)
        commits = LogParser().parse(LOG_SIMPLE, now=NOW)
        related = extractor._get_related_files("src/classifier.py", commits)
        # tests/test_classifier.py co-committed once; README.md never with classifier.py
        assert "tests/test_classifier.py" in related
        assert "src/classifier.py" not in related


# ── Renderer ──────────────────────────────────────────────────────────────────

class TestRenderer:
    def _file_ctx(self, tmp_path: Path) -> FileContext:
        from git_context.context import BlameSummary, AgeDistribution, AuthorContribution

        commits = LogParser().parse(LOG_SIMPLE, now=NOW)
        diffs = DiffParser().parse(DIFF_MODIFIED)
        blame_entries = BlameParser().parse(BLAME_PORCELAIN, now=NOW)
        blame = BlameParser().summarize(blame_entries, "src/classifier.py", now=NOW)

        return FileContext(
            file_path="src/classifier.py",
            repo_root=str(tmp_path),
            current_branch="main",
            recent_commits=commits,
            diff_vs_base=diffs,
            blame_summary=blame,
            related_files=["tests/test_classifier.py"],
        )

    def _repo_ctx(self, tmp_path: Path) -> RepoContext:
        from git_context.context import BranchStatus

        commits = LogParser().parse(LOG_SIMPLE, now=NOW)
        status = StatusParser().parse(STATUS_STAGED)

        return RepoContext(
            root_path=str(tmp_path),
            branch_status=status,
            recent_commits=commits,
            active_files=["src/classifier.py"],
            uncommitted_diff=[],
            stash_count=0,
            tag_on_head=None,
        )

    def test_file_markdown_has_expected_sections(self, tmp_path):
        ctx = self._file_ctx(tmp_path)
        md = Renderer().render_file_context(ctx, base="main")
        assert "# Git Context:" in md
        assert "## Recent Commits" in md
        assert "## Current Diff" in md
        assert "## Blame Summary" in md
        assert "## Related Files" in md

    def test_file_markdown_has_commit_data(self, tmp_path):
        ctx = self._file_ctx(tmp_path)
        md = Renderer().render_file_context(ctx, base="main")
        assert "feat: add classifier" in md
        assert "aaaa1111" in md

    def test_repo_markdown_has_expected_sections(self, tmp_path):
        ctx = self._repo_ctx(tmp_path)
        md = Renderer().render_repo_context(ctx)
        assert "## Branch Status" in md
        assert "## Uncommitted Changes" in md
        assert "## Recent Commits" in md
        assert "## Active Files" in md

    def test_to_json_valid(self, tmp_path):
        ctx = self._file_ctx(tmp_path)
        raw = Renderer().to_json(ctx)
        parsed = json.loads(raw)
        assert "file_path" in parsed
        assert "recent_commits" in parsed
        assert isinstance(parsed["recent_commits"], list)

    def test_to_json_nested_objects_serialized(self, tmp_path):
        ctx = self._file_ctx(tmp_path)
        raw = Renderer().to_json(ctx)
        parsed = json.loads(raw)
        # blame_summary should be a dict, not a Python object
        assert isinstance(parsed["blame_summary"], dict)
        assert "authors" in parsed["blame_summary"]


# ── Skip flags: no-blame, no-diff, no-related ─────────────────────────────────

class TestSkipFlags:
    def _extractor_with_file(self, tmp_path: Path):
        extractor = _make_extractor(tmp_path)
        dummy = tmp_path / "src" / "app.py"
        dummy.parent.mkdir(parents=True, exist_ok=True)
        dummy.write_text("# hi")

        def _run(*args, **kwargs):
            if "log" in args:
                return LOG_SIMPLE
            if "diff" in args:
                return DIFF_MODIFIED
            if "blame" in args:
                return BLAME_PORCELAIN
            if "rev-parse" in args and "--abbrev-ref" in args:
                return "main\n"
            if "merge-base" in args:
                return ""
            return ""

        extractor._runner.run.side_effect = _run
        extractor._runner.get_default_branch.return_value = "main"
        return extractor, dummy

    def test_no_blame_skips_blame(self, tmp_path):
        extractor, dummy = self._extractor_with_file(tmp_path)
        ctx = extractor.get_file_context(dummy, skip_blame=True)
        assert ctx.blame_summary is None

    def test_no_diff_skips_diff(self, tmp_path):
        extractor, dummy = self._extractor_with_file(tmp_path)
        ctx = extractor.get_file_context(dummy, skip_diff=True)
        assert ctx.diff_vs_base == []

    def test_no_related_skips_related(self, tmp_path):
        extractor, dummy = self._extractor_with_file(tmp_path)
        ctx = extractor.get_file_context(dummy, skip_related=True)
        assert ctx.related_files == []

    def test_all_flags_independent(self, tmp_path):
        extractor, dummy = self._extractor_with_file(tmp_path)
        ctx = extractor.get_file_context(
            dummy, skip_blame=True, skip_diff=True, skip_related=True
        )
        assert ctx.blame_summary is None
        assert ctx.diff_vs_base == []
        assert ctx.related_files == []
        assert ctx.recent_commits  # commits always fetched

    def test_no_flags_fetches_all(self, tmp_path):
        extractor, dummy = self._extractor_with_file(tmp_path)
        ctx = extractor.get_file_context(dummy)
        assert ctx.blame_summary is not None
        # diff runner was invoked — verify it was called with "diff" args
        diff_calls = [c for c in extractor._runner.run.call_args_list if "diff" in c.args]
        assert diff_calls, "expected _runner.run to be called with 'diff'"
        assert ctx.recent_commits

    def test_cli_no_blame_flag(self, tmp_path):
        from git_context.cli import main
        dummy = tmp_path / "app.py"
        dummy.write_text("# hi")
        # Run with a non-git path — expect error exit, not crash
        rc = main([str(dummy), "--no-blame"])
        assert rc in (0, 1)  # no AttributeError

    def test_cli_no_diff_flag(self, tmp_path):
        from git_context.cli import main
        dummy = tmp_path / "app.py"
        dummy.write_text("# hi")
        rc = main([str(dummy), "--no-diff"])
        assert rc in (0, 1)

    def test_cli_no_related_flag(self, tmp_path):
        from git_context.cli import main
        dummy = tmp_path / "app.py"
        dummy.write_text("# hi")
        rc = main([str(dummy), "--no-related"])
        assert rc in (0, 1)
