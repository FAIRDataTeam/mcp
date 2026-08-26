"""JSON Schemas for the tool-surface result shapes (draft 2020-12).

Derived from ``docs/mcp-tool-surface.md`` — the machine-readable companion the
conformance suite validates every tool result against. Section references point
at the contract clause each schema encodes.
"""

from __future__ import annotations

from typing import Any

_STRING = {"type": "string"}
_STRING_OR_NULL = {"type": ["string", "null"]}

# §3.6 Record object. `metadata` is an object (framed JSON-LD / summary) or a
# string (raw serialization); tools may add fields (match, service), so extra
# properties are allowed.
RECORD: dict[str, Any] = {
    "type": "object",
    "required": ["iri", "types", "title", "kind", "metadata", "links"],
    "properties": {
        "iri": _STRING,
        "types": {"type": "array", "items": _STRING},
        "title": _STRING_OR_NULL,
        "kind": _STRING_OR_NULL,
        "metadata": {"type": ["object", "string"]},
        "metadata_media_type": _STRING,
        "etag": _STRING_OR_NULL,
        "links": {"type": "object"},
    },
    "additionalProperties": True,
}

# §3.4 error envelope.
ERROR: dict[str, Any] = {
    "type": "object",
    "required": ["error"],
    "additionalProperties": False,
    "properties": {
        "error": {
            "type": "object",
            "required": ["code", "message"],
            "additionalProperties": False,
            "properties": {
                "code": {
                    "enum": [
                        "invalid_argument",
                        "not_found",
                        "read_only_violation",
                        "upstream_error",
                        "upstream_unauthorized",
                        "upstream_timeout",
                        "too_large",
                        "unsupported",
                        # Write surface (contract 1.1, ADR-0024).
                        "precondition_failed",
                        "conflict",
                        "validation_failed",
                        "unsupported_media_type",
                        "authentication_required",
                    ]
                },
                "message": _STRING,
                "details": {"type": "object"},
            },
        }
    },
}

# §3.5 unsupported result.
UNSUPPORTED: dict[str, Any] = {
    "type": "object",
    "required": ["unsupported"],
    "additionalProperties": False,
    "properties": {
        "unsupported": {
            "type": "object",
            "required": ["tool", "reason", "capability"],
            "additionalProperties": False,
            "properties": {
                "tool": _STRING,
                "reason": _STRING,
                "capability": _STRING,
                "alternative": _STRING,
            },
        }
    },
}


def page(item_schema: dict[str, Any]) -> dict[str, Any]:
    """§3.3 page envelope over the given item schema."""
    return {
        "type": "object",
        "required": ["items", "page"],
        "additionalProperties": False,
        "properties": {
            "items": {"type": "array", "items": item_schema},
            "page": {
                "type": "object",
                "required": ["limit", "offset", "count", "has_more", "total"],
                "additionalProperties": False,
                "properties": {
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                    "count": {"type": "integer"},
                    "has_more": {"type": "boolean"},
                    "total": {"type": ["integer", "null"]},
                    "next_offset": {"type": "integer"},
                    "truncated": {"type": "boolean"},
                },
            },
        },
    }


# §5.1 fdp_info
FDP_INFO: dict[str, Any] = {
    "type": "object",
    "required": ["repository", "kinds", "endpoints"],
    "additionalProperties": False,
    "properties": {
        "truncated": {"type": "boolean"},
        "repository": RECORD,
        "kinds": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["slug", "type_iris", "label", "top_level"],
                "additionalProperties": False,
                "properties": {
                    "slug": _STRING,
                    "type_iris": {"type": "array", "items": _STRING},
                    "label": _STRING_OR_NULL,
                    "top_level": {"type": "boolean"},
                },
            },
        },
        "endpoints": {"type": "object", "additionalProperties": {"type": "boolean"}},
    },
}

# §5.4 get_schema
GET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["kind", "shape_iri", "targets", "properties"],
    "additionalProperties": True,
    "properties": {
        "kind": _STRING,
        "shape_iri": _STRING,
        "targets": {"type": "array", "items": _STRING},
        "properties": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": _STRING_OR_NULL,
                    "name": _STRING_OR_NULL,
                    "min_count": {"type": ["integer", "null"]},
                    "max_count": {"type": ["integer", "null"]},
                    "datatype": _STRING_OR_NULL,
                    "node_kind": _STRING_OR_NULL,
                    "description": _STRING_OR_NULL,
                },
            },
        },
    },
}

# §5.6 sparql_query — one of the three forms.
SPARQL: dict[str, Any] = {
    "oneOf": [
        {
            "type": "object",
            "required": ["form", "head", "results"],
            "additionalProperties": False,
            "properties": {
                "form": {"const": "select"},
                "head": {"type": "object"},
                "results": {"type": "object"},
            },
        },
        {
            "type": "object",
            "required": ["form", "boolean"],
            "additionalProperties": False,
            "properties": {"form": {"const": "ask"}, "boolean": {"type": "boolean"}},
        },
        {
            "type": "object",
            "required": ["form", "graph"],
            "additionalProperties": False,
            "properties": {
                "form": {"enum": ["construct", "describe"]},
                "graph": {"type": "object"},
            },
        },
    ]
}

# §5.7 get_access_conditions
ACCESS_CONDITIONS: dict[str, Any] = {
    "type": "object",
    "required": [
        "iri",
        "license",
        "rights",
        "access_rights",
        "policies",
        "contacts",
        "determinable",
    ],
    "additionalProperties": False,
    "properties": {
        "iri": _STRING,
        "license": {"type": ["object", "null"]},
        "rights": {"type": "array"},
        "access_rights": {"type": ["object", "null"]},
        "policies": {"type": "array"},
        "contacts": {"type": "array"},
        "determinable": {"type": "boolean"},
    },
}

# §5.2 list_records / §5.5 search — page of Record objects.
LIST_RECORDS = page(RECORD)
SEARCH = page(RECORD)
# §5.8 list_data_services — page of Record objects that carry a `service` block.
LIST_DATA_SERVICES = page(RECORD)


# §5.9 create_record.
CREATE_RECORD: dict[str, Any] = {
    "type": "object",
    "required": ["iri", "etag", "state", "record"],
    "additionalProperties": False,
    "properties": {
        "iri": _STRING,
        "etag": _STRING_OR_NULL,
        "state": _STRING_OR_NULL,
        "record": RECORD,
    },
}

# §5.10 update_record.
UPDATE_RECORD: dict[str, Any] = {
    "type": "object",
    "required": ["iri", "etag", "mode", "record"],
    "additionalProperties": False,
    "properties": {
        "iri": _STRING,
        "etag": _STRING_OR_NULL,
        "mode": {"enum": ["replace", "patch"]},
        "record": RECORD,
    },
}

# §5.11 delete_record.
DELETE_RECORD: dict[str, Any] = {
    "type": "object",
    "required": ["iri", "deleted"],
    "additionalProperties": False,
    "properties": {"iri": _STRING, "deleted": {"const": True}},
}

# §5.12 set_record_state.
SET_RECORD_STATE: dict[str, Any] = {
    "type": "object",
    "required": ["iri", "from_state", "to_state", "record"],
    "additionalProperties": False,
    "properties": {
        "iri": _STRING,
        "from_state": _STRING_OR_NULL,
        "to_state": {"enum": ["DRAFT", "PUBLISHED", "ARCHIVED"]},
        "record": {"oneOf": [RECORD, {"type": "null"}]},
    },
}
