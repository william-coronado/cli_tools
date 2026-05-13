from __future__ import annotations

from .extractor import EndpointInfo, GraphQLType, SpecResult

_OPERATION_KINDS = ("query", "mutation", "subscription")
_PLURAL = {"query": "Queries", "mutation": "Mutations", "subscription": "Subscriptions"}


class Renderer:
    def render_markdown(self, r: SpecResult) -> str:
        if r.spec_format == "graphql":
            return self._render_graphql_markdown(r)
        return self._render_openapi_markdown(r)

    def _render_openapi_markdown(self, r: SpecResult) -> str:
        lines: list[str] = []

        title = r.title or "API"
        version = f" (v{r.version})" if r.version else ""
        lines.append(f"# API: {title}{version}")
        lines.append("")

        meta_parts = []
        if r.openapi_version:
            meta_parts.append(f"OpenAPI {r.openapi_version}")
        meta_parts.append(f"{r.shown_endpoints} endpoint{'s' if r.shown_endpoints != 1 else ''}")
        if r.total_endpoints != r.shown_endpoints:
            meta_parts.append(f"{r.total_endpoints} total")
        if r.servers:
            meta_parts.append("servers: " + ", ".join(r.servers[:2]))
        lines.append("  |  ".join(meta_parts))
        lines.append("")

        for w in r.warnings:
            lines.append(f"> {w}")
        if r.warnings:
            lines.append("")

        if not r.endpoints:
            lines.append("_No endpoints match the current filters._")
            return "\n".join(lines)

        if r.endpoints and r.endpoints[0].parameters or any(e.responses for e in r.endpoints):
            # Detail mode
            for ep in r.endpoints:
                lines.extend(self._render_endpoint_detail(ep))
        else:
            # Catalog table
            lines.append("| Method | Path | Summary | Tags | Deprecated |")
            lines.append("|--------|------|---------|------|-----------|")
            for ep in r.endpoints:
                tags = ", ".join(ep.tags) if ep.tags else ""
                summary = ep.summary or ""
                dep = "yes" if ep.deprecated else ""
                lines.append(f"| {ep.method} | `{ep.path}` | {summary} | {tags} | {dep} |")

        return "\n".join(lines).rstrip() + "\n"

    def _render_endpoint_detail(self, ep: EndpointInfo) -> list[str]:
        lines: list[str] = []
        dep = "  _(deprecated)_" if ep.deprecated else ""
        lines.append(f"### {ep.method} {ep.path}{dep}")
        parts = []
        if ep.tags:
            parts.append(f"**Tags:** {', '.join(ep.tags)}")
        if ep.operation_id:
            parts.append(f"**OperationId:** `{ep.operation_id}`")
        if parts:
            lines.append("  |  ".join(parts))
        if ep.summary:
            lines.append(f"_{ep.summary}_")
        lines.append("")

        if ep.parameters:
            lines.append("**Parameters:**")
            lines.append("| Name | In | Required | Type | Description |")
            lines.append("|------|----|----------|------|-------------|")
            for p in ep.parameters:
                req = "yes" if p.required else "no"
                ptype = p.schema_type or ""
                desc = p.description or ""
                lines.append(f"| `{p.name}` | {p.location} | {req} | {ptype} | {desc} |")
            lines.append("")

        if ep.request_body_schema:
            lines.append(f"**Request body:** `{ep.request_body_schema}`")
            lines.append("")

        if ep.responses:
            lines.append("**Responses:**")
            for status, shape in ep.responses.items():
                lines.append(f"- `{status}` → `{shape}`")
            lines.append("")

        return lines

    def _render_graphql_markdown(self, r: SpecResult) -> str:
        lines: list[str] = []
        lines.append("# GraphQL Schema")
        lines.append("")

        if r.source:
            lines.append(f"**Source:** {r.source}")
            lines.append("")

        # Counts
        kinds: dict[str, int] = {}
        for t in r.graphql_types:
            kinds[t.kind] = kinds.get(t.kind, 0) + 1
        count_parts = [f"{v} {k}{'s' if v != 1 else ''}" for k, v in sorted(kinds.items())]
        lines.append("**Types:** " + ", ".join(count_parts))

        # Root operation types
        op_types = {t.name.lower(): t for t in r.graphql_types if t.name.lower() in _OPERATION_KINDS}
        if op_types:
            op_parts = [
                f"{len(t.fields)} {_PLURAL.get(t.name.lower(), t.name.lower() + 's').lower()}"
                for t in op_types.values()
            ]
            lines.append("**Operations:** " + ", ".join(op_parts))
        lines.append("")

        for w in r.warnings:
            lines.append(f"> {w}")
        if r.warnings:
            lines.append("")

        # Operations section
        for kind_name in _OPERATION_KINDS:
            op_type = op_types.get(kind_name)
            if op_type and op_type.fields:
                lines.append(f"## {_PLURAL.get(kind_name, kind_name.capitalize() + 's')}")
                lines.append("| Field | Returns | Args |")
                lines.append("|-------|---------|------|")
                for f in op_type.fields:
                    args_str = ", ".join(f.args) if f.args else ""
                    lines.append(f"| `{f.name}` | `{f.type_str}` | {args_str} |")
                lines.append("")

        # Non-operation types
        non_op = [t for t in r.graphql_types if t.name.lower() not in _OPERATION_KINDS]
        if non_op:
            lines.append("## Types")
            for t in non_op:
                dep_note = f"_{t.description}_" if t.description else ""
                lines.append(f"### {t.name} `({t.kind})`")
                if dep_note:
                    lines.append(dep_note)
                if t.kind == "union":
                    for f in t.fields:
                        lines.append(f"Members: `{f.type_str}`")
                elif t.kind == "enum":
                    values = [f.name for f in t.fields]
                    lines.append(f"Values: {', '.join(f'`{v}`' for v in values)}")
                elif t.kind == "scalar":
                    lines.append("_(custom scalar)_")
                elif t.fields:
                    lines.append("| Field | Type |")
                    lines.append("|-------|------|")
                    for f in t.fields:
                        lines.append(f"| `{f.name}` | `{f.type_str}` |")
                lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def render_json(self, r: SpecResult) -> dict:
        def _ep(e: EndpointInfo) -> dict:
            return {
                "method": e.method,
                "path": e.path,
                "summary": e.summary,
                "description": e.description,
                "tags": e.tags,
                "deprecated": e.deprecated,
                "operation_id": e.operation_id,
                "parameters": [
                    {
                        "name": p.name,
                        "location": p.location,
                        "required": p.required,
                        "schema_type": p.schema_type,
                        "description": p.description,
                    }
                    for p in e.parameters
                ],
                "request_body_schema": e.request_body_schema,
                "responses": e.responses,
            }

        def _gql(t: GraphQLType) -> dict:
            return {
                "name": t.name,
                "kind": t.kind,
                "description": t.description,
                "fields": [
                    {"name": f.name, "type": f.type_str, "args": f.args, "description": f.description}
                    for f in t.fields
                ],
            }

        return {
            "source": r.source,
            "spec_format": r.spec_format,
            "title": r.title,
            "version": r.version,
            "openapi_version": r.openapi_version,
            "servers": r.servers,
            "total_endpoints": r.total_endpoints,
            "shown_endpoints": r.shown_endpoints,
            "parse_duration_ms": r.parse_duration_ms,
            "warnings": r.warnings,
            "endpoints": [_ep(e) for e in r.endpoints],
            "graphql_types": [_gql(t) for t in r.graphql_types],
        }

    def render_text(self, r: SpecResult) -> str:
        parts: list[str] = []
        if r.spec_format == "openapi":
            for ep in r.endpoints:
                summary = f" — {ep.summary}" if ep.summary else ""
                parts.append(f"{ep.method} {ep.path}{summary}")
        else:
            for t in r.graphql_types:
                fields = ", ".join(f.name for f in t.fields[:5])
                if len(t.fields) > 5:
                    fields += f", ... ({len(t.fields)} total)"
                parts.append(f"{t.kind} {t.name}: {fields}")
        return "\n".join(parts)
