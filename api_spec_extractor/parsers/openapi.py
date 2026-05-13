from __future__ import annotations

import json
from dataclasses import dataclass, field

from .base import MissingOptionalDep, simplify_schema, _ref_name, _resolve_ref, _HTTP_METHODS


@dataclass
class RawEndpoint:
    method: str
    path: str
    summary: str | None
    description: str | None
    tags: list[str]
    deprecated: bool
    operation_id: str | None
    parameters: list[dict]
    request_body: dict | None
    responses: dict


@dataclass
class OpenAPISpec:
    title: str | None
    version: str | None
    openapi_version: str | None
    servers: list[str]
    endpoints: list[RawEndpoint]
    components: dict           # merged schemas (3.x components.schemas + 2.x definitions)
    warnings: list[str]


def parse_openapi_json(content: str) -> OpenAPISpec:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e
    return _parse_spec(data)


def parse_openapi_yaml(content: str) -> OpenAPISpec:
    try:
        import yaml
    except ImportError:
        raise MissingOptionalDep(
            "pyyaml is required for YAML spec files. "
            "Install it with: pip install pyyaml"
        )
    try:
        data = yaml.safe_load(content)
    except Exception as e:
        raise ValueError(f"Invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("YAML did not parse to a mapping")
    return _parse_spec(data)


def _parse_spec(data: dict) -> OpenAPISpec:
    warnings: list[str] = []

    openapi_version = data.get("openapi") or data.get("swagger")
    if not openapi_version:
        warnings.append("No 'openapi' or 'swagger' version key found")

    info = data.get("info", {})
    title = info.get("title")
    version = info.get("version")

    # Servers
    is_v3 = str(openapi_version or "").startswith("3")
    servers: list[str] = []
    if is_v3:
        for s in data.get("servers", []):
            url = s.get("url")
            if url:
                servers.append(url)
    else:
        # OpenAPI 2: host + basePath + schemes
        host = data.get("host", "")
        base = data.get("basePath", "")
        schemes = data.get("schemes", ["https"])
        if host:
            servers.append(f"{schemes[0]}://{host}{base}")

    # Components / definitions
    components: dict = {}
    if is_v3:
        schemas = data.get("components", {}).get("schemas", {})
        components = dict(schemas)
    else:
        definitions = data.get("definitions", {})
        components = dict(definitions)
        components["__defs__"] = definitions

    # Parse paths
    endpoints: list[RawEndpoint] = []
    for path, path_item in (data.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        # Path-level parameters (shared across all methods)
        path_params = path_item.get("parameters", [])

        for method, operation in path_item.items():
            if method.lower() not in _HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                continue

            # Merge parameters: op-level overrides path-level by name+in
            op_params = operation.get("parameters", [])
            merged_params = _merge_params(path_params, op_params)

            # Request body
            request_body = None
            if is_v3:
                request_body = operation.get("requestBody")
            else:
                # OpenAPI 2: body param
                body_params = [p for p in merged_params if p.get("in") == "body"]
                if body_params:
                    bp = body_params[0]
                    request_body = {"content": {"application/json": {"schema": bp.get("schema", {})}}}
                    merged_params = [p for p in merged_params if p.get("in") != "body"]

            endpoints.append(RawEndpoint(
                method=method.upper(),
                path=path,
                summary=operation.get("summary"),
                description=operation.get("description"),
                tags=list(operation.get("tags") or []),
                deprecated=bool(operation.get("deprecated", False)),
                operation_id=operation.get("operationId"),
                parameters=merged_params,
                request_body=request_body,
                responses=dict(operation.get("responses") or {}),
            ))

    return OpenAPISpec(
        title=title,
        version=str(version) if version is not None else None,
        openapi_version=str(openapi_version) if openapi_version else None,
        servers=servers,
        endpoints=endpoints,
        components=components,
        warnings=warnings,
    )


def _merge_params(path_params: list[dict], op_params: list[dict]) -> list[dict]:
    merged: dict[tuple, dict] = {}
    for p in path_params:
        key = (p.get("name"), p.get("in"))
        merged[key] = p
    for p in op_params:
        key = (p.get("name"), p.get("in"))
        merged[key] = p
    return list(merged.values())


def extract_request_body_schema(request_body: dict | None, components: dict) -> dict | None:
    if not request_body:
        return None
    content = request_body.get("content", {})
    for mime in ("application/json", "application/x-www-form-urlencoded", "*/*"):
        schema = content.get(mime, {}).get("schema")
        if schema:
            return schema
    # Pick first available
    for mime_data in content.values():
        schema = mime_data.get("schema")
        if schema:
            return schema
    return None


def extract_response_summary(responses: dict, components: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for status, resp_obj in responses.items():
        if not isinstance(resp_obj, dict):
            continue
        resp_obj = _resolve_ref(resp_obj, components)
        description = resp_obj.get("description", "")
        # Try to find schema
        schema = None
        content = resp_obj.get("content", {})
        if content:
            for mime_data in content.values():
                s = mime_data.get("schema")
                if s:
                    schema = s
                    break
        else:
            # OpenAPI 2
            schema = resp_obj.get("schema")

        if schema:
            shape = simplify_schema(schema, components)
            result[str(status)] = shape
        elif description:
            result[str(status)] = description
        else:
            result[str(status)] = "—"
    return result
