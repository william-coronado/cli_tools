from __future__ import annotations

from .inspector import Advisory, DepReport, Dependency, EcosystemReport


_SEVERITY_ORDER = ["critical", "high", "medium", "low", "unknown"]


class Renderer:
    def render_markdown(self, r: DepReport) -> str:
        lines: list[str] = []
        eco_names = ", ".join(e.ecosystem for e in r.ecosystems) or "—"
        lines.append(f"# Dependency Report: {r.source}")
        lines.append("")

        # Top-level header
        header_bits = [f"**Ecosystems:** {eco_names}"]
        total_direct = sum(len(e.direct_deps) for e in r.ecosystems)
        total_trans = sum(e.transitive_count for e in r.ecosystems)
        header_bits.append(f"**Direct:** {total_direct}")
        header_bits.append(f"**Transitives:** {total_trans}")
        header_bits.append(f"**Parsed in:** {r.parse_duration_ms / 1000:.2f}s")
        lines.append("  |  ".join(header_bits))
        lines.append("")

        # Top-level warnings
        for w in r.warnings:
            lines.append(f"> {w}")
        if r.warnings:
            lines.append("")

        # Summary line: counts of outdated / advisories
        outdated_n = sum(
            1 for e in r.ecosystems for d in e.direct_deps + e.transitive_deps
            if d.outdated
        )
        advisory_n = sum(
            len(d.advisories)
            for e in r.ecosystems for d in e.direct_deps + e.transitive_deps
        )
        summary_bits = []
        if r.outdated_requested:
            summary_bits.append(f"{outdated_n} outdated")
        if r.audit_requested:
            summary_bits.append(f"{advisory_n} advisories")
        if summary_bits:
            lines.append(f"> _{' · '.join(summary_bits)}_")
            lines.append("")

        for e in r.ecosystems:
            lines.extend(self._render_ecosystem(e, r))

        return "\n".join(lines).rstrip() + "\n"

    def _render_ecosystem(self, e: EcosystemReport, r: DepReport) -> list[str]:
        lines: list[str] = ["---", "", f"## Ecosystem: {e.ecosystem}", ""]
        lines.append(
            f"**Manifest:** `{e.manifest_path or '—'}`  |  "
            f"**Lockfile:** `{e.lockfile_path or '—'}`"
        )
        lines.append(
            f"**Direct:** {len(e.direct_deps)}  |  "
            f"**Transitives:** {e.transitive_count}"
        )
        lines.append("")
        for n in e.notes:
            lines.append(f"> _{n}_")
        if e.notes:
            lines.append("")

        # Direct deps table
        if e.direct_deps:
            lines.append("### Direct Dependencies")
            lines.append("")
            has_latest = r.outdated_requested
            if has_latest:
                lines.append("| Package | Declared | Resolved | Latest | Status |")
                lines.append("|---------|----------|----------|--------|--------|")
            else:
                lines.append("| Package | Declared | Resolved |")
                lines.append("|---------|----------|----------|")
            for d in e.direct_deps:
                row = self._dep_row(d, has_latest=has_latest)
                lines.append(row)
            lines.append("")

        # Advisories
        all_deps = e.direct_deps + e.transitive_deps
        advisories_present = any(d.advisories for d in all_deps)
        if r.audit_requested and advisories_present:
            lines.append("### Advisories")
            lines.append("")
            # Sort: by severity (worst first), then dep name
            entries = [
                (d, a)
                for d in all_deps for a in d.advisories
            ]
            entries.sort(key=lambda t: (_SEVERITY_ORDER.index(t[1].severity), t[0].name))
            for d, a in entries:
                fix_str = f" → fix in {a.fixed_in}" if a.fixed_in else ""
                lines.append(f"#### `{d.name}` {d.resolved or ''}{fix_str}")
                url_str = f"  \n  {a.url}" if a.url else ""
                lines.append(f"- **{a.id}** ({a.severity}) — {a.summary}{url_str}")
                lines.append("")

        # Top transitives
        if e.top_transitives and not r.show_all_transitives:
            lines.append("### Top Transitive Dependencies")
            lines.append("")
            lines.append("| Package | Required by |")
            lines.append("|---------|-------------|")
            for name, count in e.top_transitives:
                lines.append(f"| `{name}` | {count} |")
            lines.append("")

        # Full transitives if --all
        if r.show_all_transitives and e.transitive_deps:
            lines.append("### All Transitive Dependencies")
            lines.append("")
            has_latest = r.outdated_requested
            if has_latest:
                lines.append("| Package | Resolved | Latest | Parent |")
                lines.append("|---------|----------|--------|--------|")
            else:
                lines.append("| Package | Resolved | Parent |")
                lines.append("|---------|----------|--------|")
            for d in e.transitive_deps:
                resolved = d.resolved or "—"
                parent = d.parent or "—"
                tag_suffix = ""
                if d.dev:
                    tag_suffix += " *(dev)*"
                if d.outdated:
                    tag_suffix += " *(outdated)*"
                if d.advisories:
                    tag_suffix += f" *(⚠ {len(d.advisories)})*"
                if has_latest:
                    latest = d.latest or "—"
                    lines.append(f"| `{d.name}`{tag_suffix} | {resolved} | {latest} | {parent} |")
                else:
                    lines.append(f"| `{d.name}`{tag_suffix} | {resolved} | {parent} |")
            lines.append("")

        return lines

    @staticmethod
    def _dep_row(d: Dependency, has_latest: bool) -> str:
        declared = d.declared or "—"
        resolved = d.resolved or "—"
        bits = [f"`{d.name}`", declared, resolved]
        if has_latest:
            latest = d.latest or "—"
            status_parts = []
            if d.outdated:
                status_parts.append("outdated")
            if d.advisories:
                status_parts.append(f"⚠ {len(d.advisories)}")
            if not status_parts and d.latest:
                status_parts.append("latest")
            status = " · ".join(status_parts) or "—"
            bits.extend([latest, status])
        # Add dev/optional tags as suffix in package cell
        tag_bits = []
        if d.dev:
            tag_bits.append("dev")
        if d.optional:
            tag_bits.append("optional")
        if tag_bits:
            bits[0] = bits[0] + " *(" + ", ".join(tag_bits) + ")*"
        return "| " + " | ".join(bits) + " |"

    def render_json(self, r: DepReport) -> dict:
        return {
            "source": r.source,
            "audit_requested": r.audit_requested,
            "outdated_requested": r.outdated_requested,
            "parse_duration_ms": r.parse_duration_ms,
            "warnings": r.warnings,
            "ecosystems": [
                {
                    "ecosystem": e.ecosystem,
                    "manifest_path": e.manifest_path,
                    "lockfile_path": e.lockfile_path,
                    "direct_deps": [_dep_json(d) for d in e.direct_deps],
                    "transitive_deps": [_dep_json(d) for d in e.transitive_deps],
                    "top_transitives": [[n, c] for n, c in e.top_transitives],
                    "transitive_count": e.transitive_count,
                    "notes": e.notes,
                }
                for e in r.ecosystems
            ],
        }

    def render_text(self, r: DepReport) -> str:
        parts = [f"{r.source} | ecosystems={[e.ecosystem for e in r.ecosystems]}"]
        for e in r.ecosystems:
            parts.append(
                f"\n[{e.ecosystem}] direct={len(e.direct_deps)} transitives={e.transitive_count}"
            )
            for d in e.direct_deps:
                tag = ""
                if d.outdated:
                    tag = " [outdated]"
                if d.advisories:
                    tag += f" [{len(d.advisories)} adv]"
                parts.append(
                    f"  - {d.name}: declared={d.declared or '-'} "
                    f"resolved={d.resolved or '-'} latest={d.latest or '-'}{tag}"
                )
            if e.top_transitives:
                parts.append(f"  top transitives: {', '.join(n for n, _ in e.top_transitives[:5])}")
        if r.warnings:
            parts.append("\nwarnings: " + "; ".join(r.warnings))
        return "\n".join(parts)


def _dep_json(d) -> dict:
    return {
        "name": d.name,
        "declared": d.declared,
        "resolved": d.resolved,
        "direct": d.direct,
        "dev": d.dev,
        "optional": d.optional,
        "parent": d.parent,
        "latest": d.latest,
        "outdated": d.outdated,
        "advisories": [
            {
                "id": a.id,
                "severity": a.severity,
                "summary": a.summary,
                "fixed_in": a.fixed_in,
                "url": a.url,
            }
            for a in d.advisories
        ],
    }
