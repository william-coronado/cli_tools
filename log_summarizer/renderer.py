from __future__ import annotations

import json
from .summarizer import SummaryResult


class Renderer:
    MAX_METRIC_ROWS = 5

    def render_markdown(self, r: SummaryResult) -> str:
        size_kb = r.total_bytes / 1024
        size_str = f"{size_kb:.1f} KB" if r.total_bytes else "unknown"
        lines: list[str] = [
            f"# Log Summary: {r.source}",
            "",
            f"**Format:** {r.log_format}  |  "
            f"**Lines:** {r.total_lines:,}  |  "
            f"**Size:** {size_str}  |  "
            f"**Parsed in:** {r.parse_duration_ms / 1000:.1f}s",
            "",
        ]

        if r.errors:
            lines += ["---", "", f"## Errors ({len(r.errors)})", ""]
            for e in r.errors:
                lines.append(f"**Line {e.line_number:,}** — `{e.message}`")
            lines.append("")

        if r.warnings:
            lines += ["---", "", f"## Warnings ({len(r.warnings)})", ""]
            for w in r.warnings:
                # Check for dedup annotation
                dedup_note = ""
                for g in r.dedup_groups:
                    if g.representative.line_number == w.line_number and g.count > 1:
                        dedup_note = f" *(x{g.count}, lines {g.first_line:,}–{g.last_line:,})*"
                        break
                lines.append(f"**Line {w.line_number:,}** — `{w.message}`{dedup_note}")
            lines.append("")

        if r.tracebacks:
            lines += ["---", "", f"## Tracebacks ({len(r.tracebacks)})", ""]
            for tb in r.tracebacks:
                exc_label = tb.exception_type or "Exception"
                msg = tb.exception_message or ""
                lines.append(f"**Lines {tb.start_line:,}–{tb.end_line:,}** — `{exc_label}: {msg}`")
                lines.append("```")
                lines.append(tb.full_text)
                lines.append("```")
                lines.append("")

        if r.metrics:
            lines += ["---", "", f"## Metrics (last {self.MAX_METRIC_ROWS} of {len(r.metrics)})", ""]
            shown = r.metrics[-self.MAX_METRIC_ROWS:]
            # Collect unique names
            names = list(dict.fromkeys(e.name for e in shown))
            if names:
                lines.append("| Step | " + " | ".join(names) + " |")
                lines.append("|------|" + "|".join("---" for _ in names) + "|")
                # Group by step
                by_step: dict[str | int, dict[str, str]] = {}
                for e in shown:
                    key = str(e.step) if e.step is not None else "?"
                    by_step.setdefault(key, {})[e.name] = (
                        f"{e.value:.4f}" if isinstance(e.value, float) else str(e.value)
                    )
                for step, vals in by_step.items():
                    row = "| " + step + " | " + " | ".join(vals.get(n, "") for n in names) + " |"
                    lines.append(row)
            lines.append("")

        if r.key_events:
            lines += ["---", "", f"## Key Events", ""]
            for ev in r.key_events:
                lines.append(f"- `{ev.message}` (line {ev.line_number:,})")
            lines.append("")

        lines += ["---", "", "## Summary", ""]
        shown_count = r.total_lines - r.suppressed_line_count
        lines.append(
            f"- Total lines: {r.total_lines:,}  |  "
            f"Suppressed (repetitive): {r.suppressed_line_count:,}  |  "
            f"Shown: {shown_count:,}"
        )
        lines.append(
            f"- Errors: {len(r.errors)}  |  "
            f"Warnings: {len(r.warnings)}  |  "
            f"Tracebacks: {len(r.tracebacks)}"
        )
        if r.dedup_groups:
            top = r.dedup_groups[0]
            lines.append(
                f"- Suppressed groups: {len(r.dedup_groups)} "
                f"(largest: \"{top.representative.message[:60]}\" x{top.count})"
            )
        return "\n".join(lines)

    def render_json(self, r: SummaryResult) -> dict:
        def _ll(e):
            return {
                "line_number": e.line_number,
                "level": e.level,
                "message": e.message,
                "category": e.category,
                "source": e.source,
            }

        def _tb(t):
            return {
                "start_line": t.start_line,
                "end_line": t.end_line,
                "exception_type": t.exception_type,
                "exception_message": t.exception_message,
                "frames": t.frames,
            }

        def _me(m):
            return {
                "line_number": m.line_number,
                "name": m.name,
                "value": m.value,
                "step": m.step,
                "unit": m.unit,
            }

        return {
            "source": r.source,
            "log_format": r.log_format,
            "total_lines": r.total_lines,
            "total_bytes": r.total_bytes,
            "parse_duration_ms": r.parse_duration_ms,
            "errors": [_ll(e) for e in r.errors],
            "warnings": [_ll(w) for w in r.warnings],
            "tracebacks": [_tb(t) for t in r.tracebacks],
            "metrics": [_me(m) for m in r.metrics],
            "key_events": [_ll(e) for e in r.key_events],
            "suppressed_line_count": r.suppressed_line_count,
            "dedup_groups": len(r.dedup_groups),
        }

    def render_text(self, r: SummaryResult) -> str:
        parts: list[str] = [f"Log: {r.source} | Format: {r.log_format} | Lines: {r.total_lines:,}"]
        if r.errors:
            parts.append(f"\nERRORS ({len(r.errors)}):")
            parts.extend(f"  [{e.line_number}] {e.message}" for e in r.errors)
        if r.warnings:
            parts.append(f"\nWARNINGS ({len(r.warnings)}):")
            parts.extend(f"  [{w.line_number}] {w.message}" for w in r.warnings)
        if r.tracebacks:
            parts.append(f"\nTRACEBACKS ({len(r.tracebacks)}):")
            for tb in r.tracebacks:
                parts.append(f"  [{tb.start_line}–{tb.end_line}] {tb.exception_type}: {tb.exception_message}")
        return "\n".join(parts)
