from __future__ import annotations
import json
import dataclasses
from typing import Any

from .context import FileContext, RepoContext, FileDiff, DiffHunk


class Renderer:
    def render_file_context(self, ctx: FileContext, base: str = "") -> str:
        lines: list[str] = []
        repo_name = ctx.repo_root.split("/")[-1] if ctx.repo_root else ""

        lines.append(f"# Git Context: {ctx.file_path}")
        lines.append("")
        branch_info = f"**Branch:** {ctx.current_branch}"
        if base:
            branch_info += f"  |  **Base:** {base}"
        if repo_name:
            branch_info += f"  |  **Repo:** {repo_name}"
        lines.append(branch_info)
        lines.append("")
        lines.append("---")
        lines.append("")

        # Recent commits
        n = len(ctx.recent_commits)
        lines.append(f"## Recent Commits ({n} touching this file)")
        lines.append("")
        if ctx.recent_commits:
            lines.append("| Hash | Age | Author | Message |")
            lines.append("|------|-----|--------|---------|")
            for c in ctx.recent_commits:
                subject = c.subject[:72] + "…" if len(c.subject) > 72 else c.subject
                lines.append(
                    f"| `{c.short_hash}` | {c.age_human} | {c.author_name} | {subject} |"
                )
        else:
            lines.append("*(no commits found)*")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Diff
        total_ins = sum(d.insertions for d in ctx.diff_vs_base)
        total_del = sum(d.deletions for d in ctx.diff_vs_base)
        base_label = base or "base"
        lines.append(f"## Current Diff vs. {base_label} (+{total_ins} -{total_del})")
        lines.append("")
        if ctx.diff_vs_base:
            lines.append("```diff")
            total_hunks = sum(len(d.hunks) for d in ctx.diff_vs_base)
            shown_hunks = 0
            for file_diff in ctx.diff_vs_base:
                if file_diff.is_binary:
                    lines.append(f"# Binary file: {file_diff.path}")
                    continue
                for hunk in file_diff.hunks:
                    shown_hunks += 1
                    old_c = hunk.old_count
                    new_c = hunk.new_count
                    hdr = f" {hunk.header}" if hunk.header else ""
                    lines.append(
                        f"@@ -{hunk.old_start},{old_c} +{hunk.new_start},{new_c} @@{hdr}"
                    )
                    for dl in hunk.lines:
                        prefix = {"added": "+", "removed": "-", "context": " "}[dl.type]
                        lines.append(f"{prefix}{dl.content}")
            lines.append("```")
            omitted = total_hunks - shown_hunks
            note_parts = []
            if omitted > 0:
                note_parts.append(f"{omitted} hunk{'s' if omitted > 1 else ''} omitted")
            if total_ins or total_del:
                note_parts.append(f"{total_ins} total insertions, {total_del} deletions")
            if note_parts:
                lines.append(f"*({', '.join(note_parts)})*")
        else:
            lines.append("*(no diff vs base)*")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Blame summary
        lines.append("## Blame Summary")
        lines.append("")
        if ctx.blame_summary:
            bs = ctx.blame_summary
            lines.append(f"**{bs.total_lines} lines total**")
            lines.append("")
            lines.append("| Author | Lines | % | Last Change |")
            lines.append("|--------|-------|---|-------------|")
            for a in bs.authors:
                lines.append(
                    f"| {a.name} | {a.line_count} | {a.percentage}% "
                    f"| {a.most_recent_date[:10] if a.most_recent_date else '—'} "
                    f"(`{a.most_recent_commit}`) |"
                )
            lines.append("")
            d = bs.age_distribution
            age_parts = []
            if d.last_week:
                age_parts.append(f"{d.last_week} lines this week")
            if d.last_month:
                age_parts.append(f"{d.last_month} lines this month")
            if d.last_quarter:
                age_parts.append(f"{d.last_quarter} lines this quarter")
            if d.last_year:
                age_parts.append(f"{d.last_year} lines this year")
            if d.older:
                age_parts.append(f"{d.older} older")
            lines.append(f"**Age distribution:** {' · '.join(age_parts) or 'n/a'}")
            lines.append("")
            recent_count = len(bs.recent_changes)
            lines.append(f"**Recently changed lines (last 30d):** {recent_count} of {bs.total_lines}")
        else:
            lines.append("*(blame not available)*")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Related files
        lines.append("## Related Files (co-committed)")
        lines.append("")
        if ctx.related_files:
            for f in ctx.related_files:
                lines.append(f"- `{f}`")
        else:
            lines.append("*(none found)*")
        lines.append("")

        return "\n".join(lines)

    def render_repo_context(self, ctx: RepoContext) -> str:
        lines: list[str] = []
        repo_name = ctx.root_path.split("/")[-1] if ctx.root_path else ""

        lines.append(f"# Git Context: {repo_name}")
        lines.append("")
        bs = ctx.branch_status
        branch_line = f"**Branch:** {bs.current_branch}"
        if bs.upstream:
            parts = []
            if bs.ahead:
                parts.append(f"+{bs.ahead} ahead")
            if bs.behind:
                parts.append(f"{bs.behind} behind")
            upstream_info = f" → {bs.upstream}"
            if parts:
                upstream_info += f" ({', '.join(parts)})"
            branch_line += upstream_info
        lines.append(branch_line)

        staged_count = len(bs.staged_files)
        unstaged_count = len(bs.unstaged_files)
        untracked_count = len(bs.untracked_files)
        lines.append(
            f"**Uncommitted:** {staged_count} staged · "
            f"{unstaged_count} unstaged · {untracked_count} untracked"
        )
        lines.append("")
        lines.append("---")
        lines.append("")

        # Branch status
        lines.append("## Branch Status")
        lines.append("")
        if not bs.has_staged and not bs.has_unstaged and not bs.has_untracked:
            lines.append("- Clean working tree")
        if bs.staged_files:
            lines.append(f"- {len(bs.staged_files)} staged change(s)")
        for f in bs.unstaged_files:
            lines.append(f"- Unstaged: `{f}`")
        for f in bs.untracked_files:
            lines.append(f"- Untracked: `{f}`")
        if bs.ahead:
            lines.append(f"- {bs.ahead} commit{'s' if bs.ahead != 1 else ''} ahead of upstream (not pushed)")
        if bs.behind:
            lines.append(f"- {bs.behind} commit{'s' if bs.behind != 1 else ''} behind upstream")
        if bs.merge_in_progress:
            lines.append("- **Merge in progress**")
        if bs.rebase_in_progress:
            lines.append("- **Rebase in progress**")
        if bs.cherry_pick_in_progress:
            lines.append("- **Cherry-pick in progress**")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Uncommitted changes
        total_ins = sum(d.insertions for d in ctx.uncommitted_diff)
        total_del = sum(d.deletions for d in ctx.uncommitted_diff)
        lines.append(f"## Uncommitted Changes (+{total_ins} -{total_del})")
        lines.append("")
        if ctx.uncommitted_diff:
            lines.append("| File | Status | +/- |")
            lines.append("|------|--------|-----|")
            for d in ctx.uncommitted_diff:
                lines.append(
                    f"| `{d.path}` | {d.status} | +{d.insertions} -{d.deletions} |"
                )
        else:
            lines.append("*(no uncommitted changes)*")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Recent commits
        n = len(ctx.recent_commits)
        lines.append(f"## Recent Commits (last {n})")
        lines.append("")
        if ctx.recent_commits:
            lines.append("| Hash | Age | Author | Files | Message |")
            lines.append("|------|-----|--------|-------|---------|")
            for c in ctx.recent_commits:
                subject = c.subject[:60] + "…" if len(c.subject) > 60 else c.subject
                lines.append(
                    f"| `{c.short_hash}` | {c.age_human} | {c.author_name} "
                    f"| {len(c.files_changed)} | {subject} |"
                )
        else:
            lines.append("*(no commits)*")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Active files
        lines.append("## Active Files (touched in recent commits)")
        lines.append("")
        if ctx.active_files:
            # Count occurrences
            file_counts: dict[str, int] = {}
            for c in ctx.recent_commits:
                for f in c.files_changed:
                    file_counts[f] = file_counts.get(f, 0) + 1
            parts = [
                f"`{f}` ({file_counts.get(f, 1)}×)" for f in ctx.active_files[:10]
            ]
            lines.append(" · ".join(parts))
        else:
            lines.append("*(no file activity)*")
        lines.append("")

        if ctx.stash_count:
            lines.append(f"*{ctx.stash_count} stash entr{'ies' if ctx.stash_count != 1 else 'y'} present*")
            lines.append("")

        if ctx.tag_on_head:
            lines.append(f"*Tagged: `{ctx.tag_on_head}`*")
            lines.append("")

        return "\n".join(lines)

    def to_json(self, ctx: FileContext | RepoContext) -> str:
        return json.dumps(_to_dict(ctx), indent=2, default=str)


def _to_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, list):
        return [_to_dict(item) for item in obj]
    return obj
