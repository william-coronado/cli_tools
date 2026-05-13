from __future__ import annotations

from typing import Any

from .summarizer import DataSummary, TableSummary, StructureSummary, ColumnInfo, ColumnStats


def _fmt_int(n: int | None) -> str:
    return "—" if n is None else f"{n:,}"


def _fmt_float(v: float | None, places: int = 4) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.{places}f}"
    return str(v)


def _fmt_size(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    if b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    return f"{b / (1024 * 1024 * 1024):.2f} GB"


def _truncate_cell(v: Any, width: int) -> str:
    s = "" if v is None else str(v)
    s = s.replace("|", "\\|").replace("\n", " ")
    if len(s) > width:
        return s[: width - 1] + "…"
    return s


class Renderer:
    def render_markdown(self, r: DataSummary) -> str:
        lines: list[str] = []

        total_rows = sum((t.row_count or 0) for t in r.tables)
        total_cols = sum(t.column_count for t in r.tables)
        title_suffix = (
            f" ({len(r.tables)} table{'s' if len(r.tables) != 1 else ''})"
            if len(r.tables) > 1 else ""
        )
        lines.append(f"# Data Summary: {r.source}{title_suffix}")
        lines.append("")

        header_bits = [
            f"**Format:** {r.file_format}",
            f"**Size:** {_fmt_size(r.file_size_bytes)}",
        ]
        if r.tables:
            if len(r.tables) == 1:
                t0 = r.tables[0]
                header_bits.append(f"**Rows:** {_fmt_int(t0.row_count)}")
                header_bits.append(f"**Cols:** {t0.column_count}")
            else:
                header_bits.append(f"**Tables:** {len(r.tables)}")
                header_bits.append(f"**Total rows:** {_fmt_int(total_rows)}")
        header_bits.append(f"**Parsed in:** {r.parse_duration_ms / 1000:.2f}s")
        header_bits.append(f"**Backend:** {r.backend_used}")
        lines.append("  |  ".join(header_bits))
        lines.append("")

        if r.warnings:
            lines.append("> " + " · ".join(r.warnings))
            lines.append("")

        for s in r.structures:
            lines.extend(self._render_structure_markdown(s))

        multi_table = len(r.tables) > 1
        for table in r.tables:
            if multi_table:
                lines.append("---")
                lines.append("")
                lines.append(f"## Table: `{table.name}`  ({_fmt_int(table.row_count)} rows · {table.column_count} cols)")
                lines.append("")
            lines.extend(self._render_table_markdown(table, sub_heading=multi_table))

        return "\n".join(lines).rstrip() + "\n"

    def _render_table_markdown(self, t: TableSummary, sub_heading: bool = False) -> list[str]:
        h = "###" if sub_heading else "##"
        lines: list[str] = []

        if t.notes:
            for n in t.notes:
                lines.append(f"> _{n}_")
            lines.append("")

        # Schema
        if not sub_heading:
            lines.append("---")
            lines.append("")
        lines.append(f"{h} Schema")
        lines.append("")
        lines.append("| # | Column | Type | Nullable | Nulls | Distinct |")
        lines.append("|---|--------|------|----------|------:|---------:|")
        for i, c in enumerate(t.columns, start=1):
            null_disp = f"{c.null_count:,}" + (f" ({c.null_pct:.1f}%)" if c.null_count else "")
            distinct_disp = "—" if c.distinct_count is None else f"{c.distinct_count:,}"
            lines.append(
                f"| {i} | `{c.name}` | {c.dtype} | "
                f"{'yes' if c.nullable else 'no'} | {null_disp} | {distinct_disp} |"
            )
        lines.append("")

        # Sample
        if t.head or t.tail:
            head_n, tail_n = len(t.head), len(t.tail)
            label_bits = []
            if head_n:
                label_bits.append(f"head {head_n}")
            if tail_n:
                label_bits.append(f"tail {tail_n}")
            label = ", ".join(label_bits)
            lines.append("---")
            lines.append("")
            lines.append(f"{h} Sample ({label})")
            lines.append("")
            shown_cols = [c.name for c in t.columns]
            lines.append("| " + " | ".join(f"`{n}`" for n in shown_cols) + " |")
            lines.append("|" + "|".join("---" for _ in shown_cols) + "|")
            for row in t.head:
                lines.append("| " + " | ".join(_truncate_cell(row.get(c), 80) for c in shown_cols) + " |")
            if t.head and t.tail:
                lines.append("| " + " | ".join("…" for _ in shown_cols) + " |")
            for row in t.tail:
                lines.append("| " + " | ".join(_truncate_cell(row.get(c), 80) for c in shown_cols) + " |")
            lines.append("")

        # Stats
        if t.stats:
            lines.append("---")
            lines.append("")
            lines.append(f"{h} Statistics")
            lines.append("")
            for s in t.stats:
                lines.extend(self._render_stat_markdown(s))
            lines.append("")

        return lines

    def _render_stat_markdown(self, s: ColumnStats) -> list[str]:
        lines: list[str] = []
        # Determine flavor by which fields populated
        is_numeric = s.min is not None or s.max is not None or s.mean is not None
        is_datetime = s.min_date is not None or s.max_date is not None
        is_categorical = bool(s.top_values)

        flavor = "numeric" if is_numeric else "datetime" if is_datetime else "categorical" if is_categorical else "—"
        lines.append(f"#### `{s.name}`  *({flavor})*")
        head = [f"count {s.count:,}", f"nulls {s.null_count:,}"]
        if s.distinct_count is not None:
            head.append(f"distinct {s.distinct_count:,}")
        else:
            head.append("distinct >max")
        if is_numeric:
            head.append(f"min {_fmt_float(s.min)}")
            head.append(f"max {_fmt_float(s.max)}")
            head.append(f"mean {_fmt_float(s.mean)}")
            if s.median is not None:
                head.append(f"median {_fmt_float(s.median)}")
            head.append(f"std {_fmt_float(s.std)}")
        if is_datetime:
            head.append(f"min {s.min_date}")
            head.append(f"max {s.max_date}")
        lines.append(" · ".join(head))
        if s.top_values:
            tv = " · ".join(f"`{_truncate_cell(v, 40)}` ({c:,})" for v, c in s.top_values)
            lines.append(f"- top: {tv}")
        lines.append("")
        return lines

    def _render_structure_markdown(self, s: StructureSummary) -> list[str]:
        lines: list[str] = ["---", "", f"## Structure: `{s.name}` (nested JSON, depth {s.depth})", ""]
        if s.notes:
            for n in s.notes:
                lines.append(f"> _{n}_")
            lines.append("")
        lines.append("| Key | Type | Size |")
        lines.append("|-----|------|-----:|")
        for k in s.top_level_keys:
            size = k.get("size")
            lines.append(f"| `{k['key']}` | {k['type']} | {_fmt_int(size)} |")
        lines.append("")
        return lines

    def render_json(self, r: DataSummary) -> dict:
        def _col(c: ColumnInfo) -> dict:
            return {
                "name": c.name,
                "dtype": c.dtype,
                "nullable": c.nullable,
                "null_count": c.null_count,
                "null_pct": round(c.null_pct, 4),
                "distinct_count": c.distinct_count,
            }

        def _stat(s: ColumnStats) -> dict:
            return {
                "name": s.name,
                "count": s.count,
                "null_count": s.null_count,
                "distinct_count": s.distinct_count,
                "min": s.min,
                "max": s.max,
                "mean": s.mean,
                "median": s.median,
                "std": s.std,
                "min_date": s.min_date,
                "max_date": s.max_date,
                "top_values": [[v, c] for v, c in s.top_values],
            }

        def _table(t: TableSummary) -> dict:
            return {
                "name": t.name,
                "row_count": t.row_count,
                "column_count": t.column_count,
                "columns": [_col(c) for c in t.columns],
                "stats": [_stat(s) for s in t.stats],
                "head": t.head,
                "tail": t.tail,
                "truncated": t.truncated,
                "notes": t.notes,
            }

        def _structure(s: StructureSummary) -> dict:
            return {
                "name": s.name,
                "top_level_keys": s.top_level_keys,
                "depth": s.depth,
                "notes": s.notes,
            }

        return {
            "source": r.source,
            "file_size_bytes": r.file_size_bytes,
            "file_format": r.file_format,
            "parse_duration_ms": r.parse_duration_ms,
            "backend_used": r.backend_used,
            "tables": [_table(t) for t in r.tables],
            "structures": [_structure(s) for s in r.structures],
            "warnings": r.warnings,
        }

    def render_text(self, r: DataSummary) -> str:
        parts: list[str] = [
            f"{r.source} | {r.file_format} | {_fmt_size(r.file_size_bytes)} | {r.backend_used}"
        ]
        for t in r.tables:
            parts.append(f"\n[{t.name}] rows={_fmt_int(t.row_count)} cols={t.column_count}")
            for c in t.columns:
                parts.append(f"  - {c.name}: {c.dtype} nulls={c.null_count} distinct={c.distinct_count}")
        for s in r.structures:
            parts.append(f"\n[{s.name}] (nested, depth={s.depth})")
            for k in s.top_level_keys:
                parts.append(f"  - {k['key']}: {k['type']} size={k.get('size')}")
        if r.warnings:
            parts.append("\nwarnings: " + "; ".join(r.warnings))
        return "\n".join(parts)
