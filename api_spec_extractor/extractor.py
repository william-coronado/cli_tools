from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EndpointParam:
    name: str
    location: str           # query | path | header | cookie
    required: bool
    schema_type: str | None
    description: str | None


@dataclass
class EndpointInfo:
    method: str
    path: str
    summary: str | None
    description: str | None
    tags: list[str]
    deprecated: bool
    operation_id: str | None
    parameters: list[EndpointParam] = field(default_factory=list)
    request_body_schema: str | None = None   # simplified shape string
    responses: dict[str, str] = field(default_factory=dict)


@dataclass
class GraphQLField:
    name: str
    type_str: str
    args: list[str]
    description: str | None


@dataclass
class GraphQLType:
    name: str
    kind: str               # object | input | interface | union | enum | scalar
    fields: list[GraphQLField]
    description: str | None
    operation_kind: str | None = None   # "query" | "mutation" | "subscription" | None


@dataclass
class SpecResult:
    source: str
    spec_format: str            # "openapi" | "graphql"
    title: str | None
    version: str | None
    openapi_version: str | None
    servers: list[str]
    total_endpoints: int
    shown_endpoints: int
    endpoints: list[EndpointInfo]
    graphql_types: list[GraphQLType]
    warnings: list[str]
    parse_duration_ms: int

    def to_markdown(self) -> str:
        from .renderer import Renderer
        return Renderer().render_markdown(self)

    def to_json(self) -> dict:
        from .renderer import Renderer
        return Renderer().render_json(self)

    def to_text(self) -> str:
        from .renderer import Renderer
        return Renderer().render_text(self)


@dataclass
class ExtractorOptions:
    endpoint_filter: str | None = None      # path substring filter
    method_filter: list[str] | None = None  # e.g. ["GET", "POST"]
    tag_filter: str | None = None
    detail: bool = False
    include_deprecated: bool = False
    url_timeout: int = 10


class SpecExtractor:
    def __init__(self, options: ExtractorOptions | None = None) -> None:
        self.options = options or ExtractorOptions()

    def extract(self, source: str) -> SpecResult:
        t0 = time.monotonic()
        opts = self.options

        content, detected_format = self._load(source)

        from .parsers.base import DetectedFormat, simplify_schema
        from .parsers.openapi import (
            parse_openapi_json, parse_openapi_yaml,
            extract_request_body_schema, extract_response_summary,
        )

        warnings: list[str] = []

        if detected_format in (DetectedFormat.OPENAPI_JSON, DetectedFormat.OPENAPI_YAML):
            if detected_format == DetectedFormat.OPENAPI_YAML:
                spec = parse_openapi_yaml(content)
            else:
                spec = parse_openapi_json(content)
            warnings.extend(spec.warnings)

            total = len(spec.endpoints)
            endpoints: list[EndpointInfo] = []
            for raw in spec.endpoints:
                if not opts.include_deprecated and raw.deprecated:
                    continue
                if opts.tag_filter and opts.tag_filter not in raw.tags:
                    continue
                if opts.endpoint_filter and opts.endpoint_filter not in raw.path:
                    continue
                if opts.method_filter and raw.method not in opts.method_filter:
                    continue

                params: list[EndpointParam] = []
                req_body_schema: str | None = None
                responses: dict[str, str] = {}

                if opts.detail:
                    for p in raw.parameters:
                        schema = p.get("schema", {}) or {}
                        ptype = schema.get("type") or p.get("type")
                        params.append(EndpointParam(
                            name=p.get("name", ""),
                            location=p.get("in", "query"),
                            required=bool(p.get("required", False)),
                            schema_type=ptype,
                            description=p.get("description"),
                        ))
                    body_schema = extract_request_body_schema(raw.request_body, spec.components)
                    if body_schema:
                        req_body_schema = simplify_schema(body_schema, spec.components)
                    responses = extract_response_summary(raw.responses, spec.components)

                endpoints.append(EndpointInfo(
                    method=raw.method,
                    path=raw.path,
                    summary=raw.summary,
                    description=raw.description,
                    tags=raw.tags,
                    deprecated=raw.deprecated,
                    operation_id=raw.operation_id,
                    parameters=params,
                    request_body_schema=req_body_schema,
                    responses=responses,
                ))

            return SpecResult(
                source=source,
                spec_format="openapi",
                title=spec.title,
                version=spec.version,
                openapi_version=spec.openapi_version,
                servers=spec.servers,
                total_endpoints=total,
                shown_endpoints=len(endpoints),
                endpoints=endpoints,
                graphql_types=[],
                warnings=warnings,
                parse_duration_ms=int((time.monotonic() - t0) * 1000),
            )

        else:  # GRAPHQL
            from .parsers.graphql import parse_graphql_sdl
            spec = parse_graphql_sdl(content)
            warnings.extend(spec.warnings)

            gql_types = [
                GraphQLType(
                    name=t.name,
                    kind=t.kind,
                    fields=[
                        GraphQLField(name=f[0], type_str=f[1], args=f[2], description=f[3])
                        for f in t.fields
                    ],
                    description=t.description,
                    operation_kind=t.operation_kind,
                )
                for t in spec.types
            ]

            return SpecResult(
                source=source,
                spec_format="graphql",
                title=None,
                version=None,
                openapi_version=None,
                servers=[],
                total_endpoints=0,
                shown_endpoints=0,
                endpoints=[],
                graphql_types=gql_types,
                warnings=warnings,
                parse_duration_ms=int((time.monotonic() - t0) * 1000),
            )

    def _load(self, source: str) -> tuple[str, object]:
        from .parsers.base import detect_format, DetectedFormat

        is_url = source.startswith("http://") or source.startswith("https://")
        if is_url:
            from .fetcher import fetch_spec
            content, content_type = fetch_spec(source, timeout=self.options.url_timeout)
            fmt = detect_format(source, content)
            return content, fmt

        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {source}")
        content = path.read_text(encoding="utf-8", errors="replace")
        fmt = detect_format(source, content)
        return content, fmt
