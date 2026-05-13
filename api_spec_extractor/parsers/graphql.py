from __future__ import annotations

from dataclasses import dataclass, field

from .base import MissingOptionalDep


@dataclass
class RawGraphQLType:
    name: str
    kind: str           # object | input | interface | union | enum | scalar
    fields: list[tuple[str, str, list[str], str | None]]  # (name, type_str, args, description)
    description: str | None
    operation_kind: str | None = None   # "query" | "mutation" | "subscription" | None


@dataclass
class GraphQLSpec:
    types: list[RawGraphQLType]
    warnings: list[str]


def parse_graphql_sdl(content: str) -> GraphQLSpec:
    try:
        from graphql import build_ast_schema, parse as gql_parse
        from graphql.type import (
            GraphQLObjectType,
            GraphQLInputObjectType,
            GraphQLInterfaceType,
            GraphQLUnionType,
            GraphQLEnumType,
            GraphQLScalarType,
            GraphQLNonNull,
            GraphQLList,
        )
    except ImportError:
        raise MissingOptionalDep(
            "graphql-core is required for GraphQL SDL files. "
            "Install it with: pip install graphql-core"
        )

    warnings: list[str] = []

    try:
        ast = gql_parse(content)
        schema = build_ast_schema(ast)
    except Exception as e:
        raise ValueError(f"Invalid GraphQL SDL: {e}") from e

    # Map each root operation type's actual name to its canonical kind.
    # A schema can declare custom root names, e.g. `schema { query: RootQuery }`,
    # so we can't rely on the type being literally named "Query".
    _root_op_kinds: dict[str, str] = {}
    if schema.query_type:
        _root_op_kinds[schema.query_type.name] = "query"
    if schema.mutation_type:
        _root_op_kinds[schema.mutation_type.name] = "mutation"
    if schema.subscription_type:
        _root_op_kinds[schema.subscription_type.name] = "subscription"

    def _type_str(t) -> str:
        if isinstance(t, GraphQLNonNull):
            return _type_str(t.of_type) + "!"
        if isinstance(t, GraphQLList):
            return f"[{_type_str(t.of_type)}]"
        return t.name

    types: list[RawGraphQLType] = []
    for name, gql_type in schema.type_map.items():
        if name.startswith("__"):
            continue
        if name in ("String", "Int", "Float", "Boolean", "ID"):
            continue

        if isinstance(gql_type, (GraphQLObjectType, GraphQLInterfaceType, GraphQLInputObjectType)):
            kind = (
                "object" if isinstance(gql_type, GraphQLObjectType)
                else "interface" if isinstance(gql_type, GraphQLInterfaceType)
                else "input"
            )
            fields = []
            for fname, field_def in gql_type.fields.items():
                ftype = _type_str(field_def.type)
                # Args (only on object/interface, not input)
                args: list[str] = []
                if hasattr(field_def, "args") and field_def.args:
                    for aname, arg in field_def.args.items():
                        args.append(f"{aname}: {_type_str(arg.type)}")
                desc = field_def.description or None
                fields.append((fname, ftype, args, desc))
            types.append(RawGraphQLType(
                name=name,
                kind=kind,
                fields=fields,
                description=gql_type.description or None,
                operation_kind=_root_op_kinds.get(name),
            ))

        elif isinstance(gql_type, GraphQLUnionType):
            members = [t.name for t in gql_type.types]
            types.append(RawGraphQLType(
                name=name,
                kind="union",
                fields=[("members", " | ".join(members), [], None)],
                description=gql_type.description or None,
            ))

        elif isinstance(gql_type, GraphQLEnumType):
            values = list(gql_type.values.keys())
            fields = [(v, "enum_value", [], None) for v in values]
            types.append(RawGraphQLType(
                name=name,
                kind="enum",
                fields=fields,
                description=gql_type.description or None,
            ))

        elif isinstance(gql_type, GraphQLScalarType):
            types.append(RawGraphQLType(
                name=name,
                kind="scalar",
                fields=[],
                description=gql_type.description or None,
            ))

    return GraphQLSpec(types=types, warnings=warnings)
