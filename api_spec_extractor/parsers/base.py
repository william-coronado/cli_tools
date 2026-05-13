from __future__ import annotations

import json
from enum import Enum
from pathlib import Path


class DetectedFormat(Enum):
    OPENAPI_JSON = "openapi_json"
    OPENAPI_YAML = "openapi_yaml"
    GRAPHQL = "graphql"


class WrongContentType(Exception):
    pass


class MissingOptionalDep(Exception):
    pass


_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "trace"}


def detect_format(source: str, content: str | None = None) -> DetectedFormat:
    path = Path(source)
    ext = path.suffix.lower()

    if ext in (".graphql", ".gql"):
        return DetectedFormat.GRAPHQL
    if ext in (".yaml", ".yml"):
        return DetectedFormat.OPENAPI_YAML
    if ext == ".json":
        return DetectedFormat.OPENAPI_JSON

    # Content sniff for URLs or extensionless files
    if content:
        snippet = content[:2000]
        if '"openapi"' in snippet or '"swagger"' in snippet or "\nopenapi:" in snippet or snippet.startswith("openapi:"):
            if ext in (".yaml", ".yml") or "\nopenapi:" in snippet or snippet.startswith("openapi:"):
                return DetectedFormat.OPENAPI_YAML
            return DetectedFormat.OPENAPI_JSON
        if "type Query" in snippet or "schema {" in snippet or "type Mutation" in snippet:
            return DetectedFormat.GRAPHQL
        # Try JSON parse to determine if it's OpenAPI JSON
        try:
            obj = json.loads(content)
            if "openapi" in obj or "swagger" in obj:
                return DetectedFormat.OPENAPI_JSON
        except (json.JSONDecodeError, ValueError):
            pass

    raise WrongContentType(
        f"Cannot detect OpenAPI or GraphQL format for: {source!r}. "
        "Supported: .json/.yaml/.yml (OpenAPI), .graphql/.gql (GraphQL)."
    )


def simplify_schema(
    schema: dict,
    components: dict,
    depth: int = 0,
    max_depth: int = 2,
) -> str:
    if not schema:
        return "any"

    schema = _resolve_ref(schema, components)

    schema_type = schema.get("type")
    if schema_type == "array" or "items" in schema:
        items = schema.get("items", {})
        items = _resolve_ref(items, components)
        item_name = items.get("title") or _ref_name(schema.get("items", {}))
        if item_name:
            return f"array[{item_name}]"
        inner = simplify_schema(items, components, depth, max_depth)
        return f"array[{inner}]"

    if schema_type in ("string", "integer", "number", "boolean", "null"):
        fmt = schema.get("format")
        return f"{schema_type}({fmt})" if fmt else schema_type

    # Object or untyped with properties
    props = schema.get("properties", {})
    title = schema.get("title")

    if not props:
        if "allOf" in schema:
            parts = [simplify_schema(s, components, depth, max_depth) for s in schema["allOf"]]
            return " & ".join(parts)
        if "oneOf" in schema or "anyOf" in schema:
            variants = schema.get("oneOf") or schema.get("anyOf") or []
            parts = [simplify_schema(s, components, depth, max_depth) for s in variants[:3]]
            return " | ".join(parts)
        return title or schema_type or "object"

    if depth >= max_depth:
        label = title or "object"
        return f"{label}{{...}}"

    field_parts = []
    for name, field_schema in list(props.items())[:8]:
        field_schema = _resolve_ref(field_schema, components)
        ftype = simplify_schema(field_schema, components, depth + 1, max_depth)
        field_parts.append(f"{name}: {ftype}")
    if len(props) > 8:
        field_parts.append("...")

    inner = ", ".join(field_parts)
    label = title or "object"
    return f"{label} {{{inner}}}"


def _resolve_ref(schema: dict, components: dict) -> dict:
    ref = schema.get("$ref", "")
    if not ref:
        return schema
    name = _ref_name(schema)
    if not name:
        return schema
    # Support both OpenAPI 3 (#/components/schemas/X) and 2 (#/definitions/X)
    resolved = components.get(name)
    if resolved is None:
        # Try definitions key (OpenAPI 2)
        resolved = components.get("__defs__", {}).get(name)
    return resolved or schema


def _ref_name(schema: dict) -> str | None:
    ref = schema.get("$ref", "")
    if not ref:
        return None
    return ref.split("/")[-1]
