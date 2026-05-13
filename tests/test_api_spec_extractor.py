"""Tests for api_spec_extractor."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from api_spec_extractor.extractor import (
    ExtractorOptions,
    SpecExtractor,
    SpecResult,
)
from api_spec_extractor.parsers.base import (
    DetectedFormat,
    MissingOptionalDep,
    WrongContentType,
    detect_format,
    simplify_schema,
)
from api_spec_extractor.parsers.openapi import (
    parse_openapi_json,
    extract_response_summary,
    extract_request_body_schema,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

PETSTORE_JSON = json.dumps({
    "openapi": "3.0.3",
    "info": {"title": "Petstore", "version": "1.0.0"},
    "servers": [{"url": "https://petstore.example.com/v1"}],
    "paths": {
        "/pets": {
            "get": {
                "summary": "List all pets",
                "operationId": "listPets",
                "tags": ["pets"],
                "deprecated": False,
                "parameters": [
                    {"name": "limit", "in": "query", "required": False,
                     "schema": {"type": "integer"}, "description": "Max items to return"}
                ],
                "responses": {
                    "200": {
                        "description": "A list of pets",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pets"}}}
                    },
                    "default": {
                        "description": "unexpected error",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
                    }
                }
            },
            "post": {
                "summary": "Create a pet",
                "operationId": "createPets",
                "tags": ["pets"],
                "deprecated": False,
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/NewPet"}
                        }
                    }
                },
                "responses": {
                    "201": {"description": "Null response"},
                    "default": {"description": "unexpected error"}
                }
            }
        },
        "/pets/{petId}": {
            "get": {
                "summary": "Info for a specific pet",
                "operationId": "showPetById",
                "tags": ["pets"],
                "deprecated": False,
                "parameters": [
                    {"name": "petId", "in": "path", "required": True,
                     "schema": {"type": "string"}, "description": "The id of the pet to retrieve"}
                ],
                "responses": {
                    "200": {
                        "description": "Expected response to a valid request",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}}
                    },
                    "default": {"description": "unexpected error"}
                }
            }
        },
        "/admin/health": {
            "get": {
                "summary": "Health check",
                "tags": ["admin"],
                "deprecated": True,
                "responses": {"200": {"description": "ok"}}
            }
        }
    },
    "components": {
        "schemas": {
            "Pet": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "tag": {"type": "string"}
                },
                "required": ["id", "name"]
            },
            "Pets": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/Pet"}
            },
            "NewPet": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "tag": {"type": "string"}
                },
                "required": ["name"]
            },
            "Error": {
                "type": "object",
                "properties": {
                    "code": {"type": "integer"},
                    "message": {"type": "string"}
                },
                "required": ["code", "message"]
            }
        }
    }
})

SWAGGER2_JSON = json.dumps({
    "swagger": "2.0",
    "info": {"title": "Swagger Petstore", "version": "1.0"},
    "host": "petstore.swagger.io",
    "basePath": "/v2",
    "schemes": ["https"],
    "paths": {
        "/pet": {
            "post": {
                "summary": "Add a new pet",
                "operationId": "addPet",
                "tags": ["pet"],
                "parameters": [
                    {
                        "in": "body",
                        "name": "body",
                        "schema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}}
                        }
                    }
                ],
                "responses": {"405": {"description": "Invalid input"}}
            }
        },
        "/pet/{petId}": {
            "get": {
                "summary": "Find pet by ID",
                "operationId": "getPetById",
                "tags": ["pet"],
                "parameters": [
                    {"name": "petId", "in": "path", "required": True,
                     "type": "integer", "description": "Pet id to delete"}
                ],
                "responses": {
                    "200": {"description": "successful operation"},
                    "404": {"description": "Pet not found"}
                }
            }
        }
    },
    "definitions": {
        "Pet": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"}
            }
        }
    }
})

GRAPHQL_SDL = """
type Query {
  pets(limit: Int): [Pet]
  pet(id: ID!): Pet
  users: [User]
}

type Mutation {
  createPet(name: String!, tag: String): Pet
  deletePet(id: ID!): Boolean
}

type Pet {
  id: ID!
  name: String!
  tag: String
  owner: User
}

type User {
  id: ID!
  name: String!
  email: String
}

input NewPetInput {
  name: String!
  tag: String
}

enum PetStatus {
  AVAILABLE
  PENDING
  SOLD
}
"""


def _extract(source: str, **opts) -> SpecResult:
    return SpecExtractor(ExtractorOptions(**opts)).extract(source)


@pytest.fixture
def petstore_file(tmp_path):
    p = tmp_path / "petstore.json"
    p.write_text(PETSTORE_JSON)
    return str(p)


@pytest.fixture
def petstore_yaml_file(tmp_path):
    p = tmp_path / "petstore.yaml"
    p.write_text(
        "openapi: '3.0.3'\n"
        "info:\n"
        "  title: Petstore YAML\n"
        "  version: '1.0.0'\n"
        "paths:\n"
        "  /items:\n"
        "    get:\n"
        "      summary: List items\n"
        "      tags:\n"
        "        - items\n"
        "      responses:\n"
        "        '200':\n"
        "          description: ok\n"
    )
    return str(p)


@pytest.fixture
def swagger2_file(tmp_path):
    p = tmp_path / "swagger2.json"
    p.write_text(SWAGGER2_JSON)
    return str(p)


@pytest.fixture
def graphql_file(tmp_path):
    p = tmp_path / "schema.graphql"
    p.write_text(GRAPHQL_SDL)
    return str(p)


# ── Endpoint extraction ───────────────────────────────────────────────────────

class TestEndpointExtraction:
    def test_total_endpoints_excludes_deprecated_by_default(self, petstore_file):
        r = _extract(petstore_file)
        assert r.total_endpoints == 4
        assert r.shown_endpoints == 3
        paths = [e.path for e in r.endpoints]
        assert "/admin/health" not in paths

    def test_include_deprecated(self, petstore_file):
        r = _extract(petstore_file, include_deprecated=True)
        assert r.shown_endpoints == 4

    def test_methods_parsed(self, petstore_file):
        r = _extract(petstore_file)
        methods = {e.method for e in r.endpoints}
        assert "GET" in methods and "POST" in methods

    def test_paths_parsed(self, petstore_file):
        r = _extract(petstore_file)
        paths = {e.path for e in r.endpoints}
        assert "/pets" in paths
        assert "/pets/{petId}" in paths

    def test_summary_parsed(self, petstore_file):
        r = _extract(petstore_file)
        summaries = {e.summary for e in r.endpoints}
        assert "List all pets" in summaries

    def test_tags_parsed(self, petstore_file):
        r = _extract(petstore_file)
        ep = next(e for e in r.endpoints if e.path == "/pets" and e.method == "GET")
        assert "pets" in ep.tags

    def test_title_and_version(self, petstore_file):
        r = _extract(petstore_file)
        assert r.title == "Petstore"
        assert r.version == "1.0.0"
        assert r.openapi_version == "3.0.3"

    def test_servers(self, petstore_file):
        r = _extract(petstore_file)
        assert "https://petstore.example.com/v1" in r.servers

    def test_deprecated_flag(self, petstore_file):
        r = _extract(petstore_file, include_deprecated=True)
        dep_ep = next(e for e in r.endpoints if e.path == "/admin/health")
        assert dep_ep.deprecated is True

    def test_operation_id(self, petstore_file):
        r = _extract(petstore_file)
        ep = next(e for e in r.endpoints if e.path == "/pets" and e.method == "GET")
        assert ep.operation_id == "listPets"


# ── Filtering ─────────────────────────────────────────────────────────────────

class TestFiltering:
    def test_tag_filter(self, petstore_file):
        r = _extract(petstore_file, tag_filter="pets", include_deprecated=True)
        assert all("pets" in e.tags for e in r.endpoints)

    def test_tag_filter_excludes_non_matching(self, petstore_file):
        r = _extract(petstore_file, tag_filter="admin", include_deprecated=True)
        assert all("admin" in e.tags for e in r.endpoints)

    def test_endpoint_filter(self, petstore_file):
        r = _extract(petstore_file, endpoint_filter="/pets/{")
        assert all("{petId}" in e.path for e in r.endpoints)

    def test_method_filter(self, petstore_file):
        r = _extract(petstore_file, method_filter=["POST"])
        assert all(e.method == "POST" for e in r.endpoints)

    def test_method_filter_get_only(self, petstore_file):
        r = _extract(petstore_file, method_filter=["GET"])
        assert all(e.method == "GET" for e in r.endpoints)
        assert r.shown_endpoints == 2

    def test_combined_filters(self, petstore_file):
        r = _extract(petstore_file, tag_filter="pets", method_filter=["GET"])
        assert all(e.method == "GET" and "pets" in e.tags for e in r.endpoints)


# ── Detail mode ───────────────────────────────────────────────────────────────

class TestDetailMode:
    def test_parameters_populated_in_detail_mode(self, petstore_file):
        r = _extract(petstore_file, detail=True)
        list_ep = next(e for e in r.endpoints if e.path == "/pets" and e.method == "GET")
        assert len(list_ep.parameters) == 1
        param = list_ep.parameters[0]
        assert param.name == "limit"
        assert param.location == "query"
        assert param.required is False
        assert param.schema_type == "integer"

    def test_parameters_empty_by_default(self, petstore_file):
        r = _extract(petstore_file)
        list_ep = next(e for e in r.endpoints if e.path == "/pets" and e.method == "GET")
        assert list_ep.parameters == []

    def test_request_body_schema_in_detail(self, petstore_file):
        r = _extract(petstore_file, detail=True)
        post_ep = next(e for e in r.endpoints if e.path == "/pets" and e.method == "POST")
        assert post_ep.request_body_schema is not None
        assert "name" in post_ep.request_body_schema

    def test_response_schemas_in_detail(self, petstore_file):
        r = _extract(petstore_file, detail=True)
        list_ep = next(e for e in r.endpoints if e.path == "/pets" and e.method == "GET")
        assert "200" in list_ep.responses
        assert list_ep.responses["200"]  # non-empty

    def test_path_parameter_in_detail(self, petstore_file):
        r = _extract(petstore_file, detail=True)
        detail_ep = next(e for e in r.endpoints if e.path == "/pets/{petId}")
        path_params = [p for p in detail_ep.parameters if p.location == "path"]
        assert any(p.name == "petId" for p in path_params)


# ── Component refs (requestBodies / responses) ───────────────────────────────

PETSTORE_COMPONENT_REFS_JSON = json.dumps({
    "openapi": "3.0.3",
    "info": {"title": "Ref Test", "version": "1.0"},
    "paths": {
        "/pets": {
            "post": {
                "summary": "Create a pet",
                "operationId": "createPet",
                "tags": ["pets"],
                "requestBody": {"$ref": "#/components/requestBodies/PetBody"},
                "responses": {
                    "201": {"$ref": "#/components/responses/PetCreated"},
                    "422": {"$ref": "#/components/responses/ValidationError"},
                }
            }
        }
    },
    "components": {
        "schemas": {
            "Pet": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"}
                }
            },
            "Error": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"}
                }
            }
        },
        "requestBodies": {
            "PetBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Pet"}
                    }
                }
            }
        },
        "responses": {
            "PetCreated": {
                "description": "Pet created",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Pet"}
                    }
                }
            },
            "ValidationError": {
                "description": "Validation failed",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Error"}
                    }
                }
            }
        }
    }
})


@pytest.fixture
def component_refs_file(tmp_path):
    p = tmp_path / "component_refs.json"
    p.write_text(PETSTORE_COMPONENT_REFS_JSON)
    return str(p)


class TestComponentRefs:
    def test_request_body_ref_resolved(self, component_refs_file):
        r = _extract(component_refs_file, detail=True)
        ep = r.endpoints[0]
        assert ep.request_body_schema is not None
        # Should contain Pet schema fields, not be empty/None
        assert "id" in ep.request_body_schema or "name" in ep.request_body_schema

    def test_response_ref_resolved(self, component_refs_file):
        r = _extract(component_refs_file, detail=True)
        ep = r.endpoints[0]
        assert "201" in ep.responses
        # Should contain Pet schema fields, not just description or "—"
        assert ep.responses["201"] != "—"
        assert "id" in ep.responses["201"] or "name" in ep.responses["201"]

    def test_response_ref_second_status(self, component_refs_file):
        r = _extract(component_refs_file, detail=True)
        ep = r.endpoints[0]
        assert "422" in ep.responses
        assert ep.responses["422"] != "—"
        assert "message" in ep.responses["422"]

    def test_component_refs_without_detail_dont_crash(self, component_refs_file):
        r = _extract(component_refs_file)
        assert r.shown_endpoints == 1


# ── OpenAPI 2 (Swagger) ───────────────────────────────────────────────────────

class TestOpenAPI2:
    def test_swagger2_parsed(self, swagger2_file):
        r = _extract(swagger2_file)
        assert r.spec_format == "openapi"
        assert r.openapi_version == "2.0"

    def test_swagger2_endpoints(self, swagger2_file):
        r = _extract(swagger2_file)
        assert r.total_endpoints == 2
        paths = {e.path for e in r.endpoints}
        assert "/pet" in paths and "/pet/{petId}" in paths

    def test_swagger2_host_server(self, swagger2_file):
        r = _extract(swagger2_file)
        assert any("petstore.swagger.io" in s for s in r.servers)

    def test_swagger2_body_param_detail(self, swagger2_file):
        r = _extract(swagger2_file, detail=True)
        post_ep = next(e for e in r.endpoints if e.path == "/pet" and e.method == "POST")
        assert post_ep.request_body_schema is not None


# ── GraphQL ───────────────────────────────────────────────────────────────────

class TestGraphQL:
    def test_graphql_format(self, graphql_file):
        r = _extract(graphql_file)
        assert r.spec_format == "graphql"

    def test_graphql_types_present(self, graphql_file):
        r = _extract(graphql_file)
        names = {t.name for t in r.graphql_types}
        assert "Pet" in names
        assert "User" in names

    def test_graphql_query_type(self, graphql_file):
        r = _extract(graphql_file)
        query_type = next((t for t in r.graphql_types if t.name == "Query"), None)
        assert query_type is not None
        field_names = {f.name for f in query_type.fields}
        assert "pets" in field_names and "pet" in field_names

    def test_graphql_mutation_type(self, graphql_file):
        r = _extract(graphql_file)
        mut = next((t for t in r.graphql_types if t.name == "Mutation"), None)
        assert mut is not None
        assert len(mut.fields) == 2

    def test_graphql_field_types(self, graphql_file):
        r = _extract(graphql_file)
        pet_type = next(t for t in r.graphql_types if t.name == "Pet")
        field_map = {f.name: f.type_str for f in pet_type.fields}
        assert field_map["id"] == "ID!"
        assert field_map["name"] == "String!"

    def test_graphql_query_args(self, graphql_file):
        r = _extract(graphql_file)
        query_type = next(t for t in r.graphql_types if t.name == "Query")
        pets_field = next(f for f in query_type.fields if f.name == "pets")
        assert any("limit" in arg for arg in pets_field.args)

    def test_graphql_enum(self, graphql_file):
        r = _extract(graphql_file)
        enum_type = next((t for t in r.graphql_types if t.name == "PetStatus"), None)
        assert enum_type is not None
        assert enum_type.kind == "enum"
        values = {f.name for f in enum_type.fields}
        assert "AVAILABLE" in values

    def test_graphql_input_type(self, graphql_file):
        r = _extract(graphql_file)
        input_type = next((t for t in r.graphql_types if t.name == "NewPetInput"), None)
        assert input_type is not None
        assert input_type.kind == "input"


# ── GraphQL custom root operation types ──────────────────────────────────────

GRAPHQL_CUSTOM_ROOTS = """
schema {
  query: RootQuery
  mutation: RootMutation
}

type RootQuery {
  pets(limit: Int): [Pet]
  pet(id: ID!): Pet
}

type RootMutation {
  createPet(name: String!): Pet
}

type Pet {
  id: ID!
  name: String!
}
"""


@pytest.fixture
def custom_root_graphql_file(tmp_path):
    p = tmp_path / "custom_roots.graphql"
    p.write_text(GRAPHQL_CUSTOM_ROOTS)
    return str(p)


class TestGraphQLCustomRoots:
    def test_queries_section_rendered(self, custom_root_graphql_file):
        md = _extract(custom_root_graphql_file).to_markdown()
        assert "## Queries" in md

    def test_mutations_section_rendered(self, custom_root_graphql_file):
        md = _extract(custom_root_graphql_file).to_markdown()
        assert "## Mutations" in md

    def test_query_fields_shown(self, custom_root_graphql_file):
        md = _extract(custom_root_graphql_file).to_markdown()
        assert "pets" in md
        assert "pet" in md

    def test_mutation_fields_shown(self, custom_root_graphql_file):
        md = _extract(custom_root_graphql_file).to_markdown()
        assert "createPet" in md

    def test_root_types_not_in_types_section(self, custom_root_graphql_file):
        md = _extract(custom_root_graphql_file).to_markdown()
        # RootQuery / RootMutation should not appear as regular types
        assert "### RootQuery" not in md
        assert "### RootMutation" not in md

    def test_operation_kind_tagged_correctly(self, custom_root_graphql_file):
        r = _extract(custom_root_graphql_file)
        root_query = next(t for t in r.graphql_types if t.name == "RootQuery")
        root_mut = next(t for t in r.graphql_types if t.name == "RootMutation")
        assert root_query.operation_kind == "query"
        assert root_mut.operation_kind == "mutation"

    def test_non_root_type_has_no_operation_kind(self, custom_root_graphql_file):
        r = _extract(custom_root_graphql_file)
        pet = next(t for t in r.graphql_types if t.name == "Pet")
        assert pet.operation_kind is None

    def test_operations_count_in_summary(self, custom_root_graphql_file):
        md = _extract(custom_root_graphql_file).to_markdown()
        assert "**Operations:**" in md

    def test_json_output_includes_operation_kind(self, custom_root_graphql_file):
        d = _extract(custom_root_graphql_file).to_json()
        root_query = next(t for t in d["graphql_types"] if t["name"] == "RootQuery")
        assert root_query["operation_kind"] == "query"


# ── YAML format ───────────────────────────────────────────────────────────────

class TestYAMLFormat:
    def test_yaml_spec_parsed(self, petstore_yaml_file):
        r = _extract(petstore_yaml_file)
        assert r.spec_format == "openapi"
        assert r.title == "Petstore YAML"

    def test_yaml_endpoints(self, petstore_yaml_file):
        r = _extract(petstore_yaml_file)
        assert r.total_endpoints == 1
        assert r.endpoints[0].path == "/items"


# ── Format detection ──────────────────────────────────────────────────────────

class TestFormatDetection:
    def test_json_extension(self, tmp_path):
        p = tmp_path / "spec.json"
        p.write_text('{"openapi": "3.0.0"}')
        assert detect_format(str(p)) == DetectedFormat.OPENAPI_JSON

    def test_yaml_extension(self, tmp_path):
        p = tmp_path / "spec.yaml"
        p.write_text("openapi: '3.0.0'\n")
        assert detect_format(str(p)) == DetectedFormat.OPENAPI_YAML

    def test_graphql_extension(self, tmp_path):
        p = tmp_path / "schema.graphql"
        p.write_text("type Query { hello: String }")
        assert detect_format(str(p)) == DetectedFormat.GRAPHQL

    def test_gql_extension(self, tmp_path):
        p = tmp_path / "schema.gql"
        p.write_text("type Query { hello: String }")
        assert detect_format(str(p)) == DetectedFormat.GRAPHQL

    def test_content_sniff_openapi(self):
        assert detect_format("spec", '{"openapi": "3.0.0", "paths": {}}') == DetectedFormat.OPENAPI_JSON

    def test_content_sniff_graphql(self):
        assert detect_format("spec", "type Query { hello: String }") == DetectedFormat.GRAPHQL

    def test_unknown_raises(self, tmp_path):
        p = tmp_path / "data.csv"
        p.write_text("a,b,c\n1,2,3\n")
        with pytest.raises(WrongContentType):
            detect_format(str(p), "a,b,c\n1,2,3\n")


# ── Schema simplification ─────────────────────────────────────────────────────

class TestSchemaSimplification:
    def test_scalar_types(self):
        assert simplify_schema({"type": "string"}, {}) == "string"
        assert simplify_schema({"type": "integer"}, {}) == "integer"

    def test_object_with_properties(self):
        schema = {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}}
        result = simplify_schema(schema, {})
        assert "id" in result and "name" in result

    def test_array_with_ref(self):
        schema = {"type": "array", "items": {"$ref": "#/components/schemas/Pet"}}
        components = {"Pet": {"type": "object", "properties": {}}}
        result = simplify_schema(schema, components)
        assert "array" in result and "Pet" in result

    def test_ref_resolution(self):
        schema = {"$ref": "#/components/schemas/Error"}
        components = {"Error": {"type": "object", "properties": {"code": {"type": "integer"}}}}
        result = simplify_schema(schema, components)
        assert "code" in result

    def test_max_depth_truncation(self):
        schema = {
            "type": "object",
            "properties": {
                "nested": {"type": "object", "properties": {"deep": {"type": "object", "properties": {}}}}
            }
        }
        result = simplify_schema(schema, {}, max_depth=1)
        assert "{...}" in result

    def test_allof_joins_with_ampersand(self):
        schema = {
            "allOf": [
                {"type": "object", "properties": {"id": {"type": "integer"}}},
                {"type": "object", "properties": {"name": {"type": "string"}}},
            ]
        }
        result = simplify_schema(schema, {})
        assert " & " in result
        assert "id: integer" in result
        assert "name: string" in result

    def test_allof_with_refs(self):
        schema = {
            "allOf": [
                {"$ref": "#/components/schemas/Base"},
                {"type": "object", "properties": {"extra": {"type": "boolean"}}},
            ]
        }
        components = {"Base": {"type": "object", "properties": {"id": {"type": "integer"}}}}
        result = simplify_schema(schema, components)
        assert " & " in result
        assert "id: integer" in result
        assert "extra: boolean" in result

    def test_oneof_joins_with_pipe(self):
        schema = {
            "oneOf": [
                {"type": "string"},
                {"type": "integer"},
                {"type": "null"},
            ]
        }
        result = simplify_schema(schema, {})
        assert " | " in result
        assert "string" in result
        assert "integer" in result
        assert "null" in result

    def test_anyof_joins_with_pipe(self):
        schema = {
            "anyOf": [
                {"type": "object", "properties": {"value": {"type": "number"}}},
                {"type": "null"},
            ]
        }
        result = simplify_schema(schema, {})
        assert " | " in result
        assert "null" in result

    def test_oneof_truncates_beyond_three_variants(self):
        schema = {
            "oneOf": [
                {"type": "string"},
                {"type": "integer"},
                {"type": "number"},
                {"type": "boolean"},
            ]
        }
        result = simplify_schema(schema, {})
        # Only first 3 variants shown, so boolean should not appear
        assert "boolean" not in result
        assert result.count("|") == 2   # 3 variants → 2 separators

    def test_oneof_with_refs(self):
        schema = {
            "oneOf": [
                {"$ref": "#/components/schemas/Cat"},
                {"$ref": "#/components/schemas/Dog"},
            ]
        }
        components = {
            "Cat": {"type": "object", "properties": {"meows": {"type": "boolean"}}},
            "Dog": {"type": "object", "properties": {"barks": {"type": "boolean"}}},
        }
        result = simplify_schema(schema, components)
        assert " | " in result
        assert "meows" in result
        assert "barks" in result


# ── URL input ─────────────────────────────────────────────────────────────────

class TestURLInput:
    def test_url_fetches_and_parses(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.read.return_value = PETSTORE_JSON.encode()
        mock_resp.headers.get.return_value = "application/json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            r = _extract("https://example.com/petstore.json")
        assert r.spec_format == "openapi"
        assert r.title == "Petstore"

    def test_url_fetch_error_raises_value_error(self):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            with pytest.raises(ValueError, match="Failed to fetch"):
                _extract("https://example.com/spec.json")


# ── Renderers ─────────────────────────────────────────────────────────────────

class TestRenderers:
    def test_markdown_has_table_headers(self, petstore_file):
        md = _extract(petstore_file).to_markdown()
        assert "| Method |" in md
        assert "| Path |" in md

    def test_markdown_has_title(self, petstore_file):
        md = _extract(petstore_file).to_markdown()
        assert "Petstore" in md

    def test_markdown_detail_has_parameters_header(self, petstore_file):
        md = _extract(petstore_file, detail=True).to_markdown()
        assert "**Parameters:**" in md

    def test_markdown_graphql_has_operations(self, graphql_file):
        md = _extract(graphql_file).to_markdown()
        assert "Queries" in md
        assert "Mutations" in md

    def test_json_parses(self, petstore_file):
        d = _extract(petstore_file).to_json()
        json.dumps(d)
        assert d["spec_format"] == "openapi"
        assert d["title"] == "Petstore"

    def test_json_endpoint_structure(self, petstore_file):
        d = _extract(petstore_file).to_json()
        ep = d["endpoints"][0]
        assert "method" in ep and "path" in ep and "tags" in ep

    def test_json_graphql_types(self, graphql_file):
        d = _extract(graphql_file).to_json()
        assert d["spec_format"] == "graphql"
        assert len(d["graphql_types"]) > 0

    def test_text_renderer_openapi(self, petstore_file):
        text = _extract(petstore_file).to_text()
        assert "GET" in text or "POST" in text

    def test_text_renderer_graphql(self, graphql_file):
        text = _extract(graphql_file).to_text()
        assert "Pet" in text or "Query" in text


# ── Exit codes ────────────────────────────────────────────────────────────────

class TestExitCodes:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "api_spec_extractor.cli", *args],
            capture_output=True, text=True,
        )

    def test_zero_on_success(self, petstore_file):
        r = self._run(petstore_file)
        assert r.returncode == 0

    def test_one_on_missing_file(self):
        r = self._run("/no/such/file.json")
        assert r.returncode == 1

    def test_one_on_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("this is not json {{{")
        r = self._run(str(p))
        assert r.returncode == 1

    def test_three_on_wrong_content_type(self, tmp_path):
        p = tmp_path / "data.csv"
        p.write_text("a,b\n1,2\n")
        r = self._run(str(p))
        assert r.returncode == 3

    def test_json_output_valid(self, petstore_file):
        r = self._run(petstore_file, "--format", "json")
        assert r.returncode == 0
        json.loads(r.stdout)

    def test_detail_flag(self, petstore_file):
        r = self._run(petstore_file, "--detail")
        assert r.returncode == 0
        assert "**Parameters:**" in r.stdout

    def test_method_filter_cli(self, petstore_file):
        r = self._run(petstore_file, "--method", "POST")
        assert r.returncode == 0
        assert "POST" in r.stdout
        assert "GET" not in r.stdout.split("Method")[1]  # Not in table body

    def test_tag_filter_cli(self, petstore_file):
        r = self._run(petstore_file, "--tag", "admin", "--include-deprecated")
        assert r.returncode == 0
        assert "/admin/health" in r.stdout

    def test_include_deprecated_cli(self, petstore_file):
        r_default = self._run(petstore_file)
        r_incl = self._run(petstore_file, "--include-deprecated")
        assert "/admin/health" not in r_default.stdout
        assert "/admin/health" in r_incl.stdout

    def test_zero_on_graphql(self, graphql_file):
        r = self._run(graphql_file)
        assert r.returncode == 0

    def test_text_format(self, petstore_file):
        r = self._run(petstore_file, "--format", "text")
        assert r.returncode == 0
        assert "GET" in r.stdout or "POST" in r.stdout


# ── MCP wrapper ───────────────────────────────────────────────────────────────

class TestMCPWrapper:
    def test_extract_api_spec_returns_result(self, petstore_file):
        req = json.dumps({"name": "extract_api_spec", "parameters": {"source": petstore_file}})
        r = subprocess.run(
            [sys.executable, "-m", "api_spec_extractor.mcp_tool"],
            input=req + "\n", capture_output=True, text=True,
        )
        assert r.returncode == 0
        d = json.loads(r.stdout.strip())
        assert "result" in d
        assert "Petstore" in d["result"]

    def test_mcp_detail_mode(self, petstore_file):
        req = json.dumps({
            "name": "extract_api_spec",
            "parameters": {"source": petstore_file, "detail": True}
        })
        r = subprocess.run(
            [sys.executable, "-m", "api_spec_extractor.mcp_tool"],
            input=req + "\n", capture_output=True, text=True,
        )
        d = json.loads(r.stdout.strip())
        assert "**Parameters:**" in d["result"]

    def test_unknown_tool_returns_error(self):
        r = subprocess.run(
            [sys.executable, "-m", "api_spec_extractor.mcp_tool"],
            input='{"name":"nope","parameters":{}}\n', capture_output=True, text=True,
        )
        d = json.loads(r.stdout.strip())
        assert "error" in d

    def test_mcp_graphql(self, graphql_file):
        req = json.dumps({"name": "extract_api_spec", "parameters": {"source": graphql_file}})
        r = subprocess.run(
            [sys.executable, "-m", "api_spec_extractor.mcp_tool"],
            input=req + "\n", capture_output=True, text=True,
        )
        d = json.loads(r.stdout.strip())
        assert "result" in d
        assert "GraphQL" in d["result"]
