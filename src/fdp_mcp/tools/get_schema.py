"""`get_schema` — the SHACL shape for a kind.

Contract: docs/mcp-tool-surface.md §5.4 (optional, capability ``shapes``).
Resolves the kind to an example record (via root discovery), then follows that
record's ``constrainedBy`` shape and digests it. Degrades to the ``unsupported``
result when the FDP publishes no resolvable shape (see fdp-api-gaps.md G-02).
"""

from __future__ import annotations

from typing import Any

from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import FdpUnsupportedError, InvalidArgumentError
from fdp_mcp.fdp.ldp import discover_root
from fdp_mcp.fdp.shapes import fetch_shape_for_record
from fdp_mcp.shaping import frame_record
from fdp_mcp.tools._common import Format


async def handle(client: FdpClient, *, kind: str, fmt: Format = "jsonld") -> dict[str, Any]:
    """Resolve and digest the SHACL shape for a runtime kind slug."""
    discovery = await discover_root(client)
    match = next((k for k in discovery.kinds if k.slug == kind), None)
    if match is None:
        raise InvalidArgumentError(f"unknown kind {kind!r}; call fdp_info for available kinds")
    if match.example_iri is None:
        raise FdpUnsupportedError(
            "shapes", f"no example record of kind {kind!r} from which to resolve a shape"
        )

    shape = await fetch_shape_for_record(client, match.example_iri)
    properties = [
        {
            "path": prop.path,
            "name": prop.name,
            "min_count": prop.min_count,
            "max_count": prop.max_count,
            "datatype": prop.datatype,
            "node_kind": prop.node_kind,
            "class": prop.cls,
            "description": prop.description,
        }
        for prop in shape.properties
    ]
    result: dict[str, Any] = {
        "kind": kind,
        "shape_iri": shape.shape_iri,
        "targets": shape.target_class_iris,
        "properties": properties,
    }
    if fmt == "jsonld":
        result["shape"] = frame_record(shape.graph, shape.shape_iri)
    else:
        result["shape"] = shape.text
        result["shape_media_type"] = shape.media_type
    return result
