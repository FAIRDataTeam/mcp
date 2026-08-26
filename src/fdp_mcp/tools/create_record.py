"""`create_record` — create a new record inside a container (LDP POST).

Contract: docs/mcp-tool-surface.md §5.9 (optional extension; ADR-0024).
"""

from __future__ import annotations

from typing import Any

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.ldp import fetch_resource
from fdp_mcp.fdp.write import create_member, record_state, validate_rdf_body
from fdp_mcp.shaping import record_object
from fdp_mcp.tools._common import kind_slug, validate_iri


async def handle(
    client: FdpClient,
    settings: FdpMcpSettings,
    *,
    parent_iri: str,
    body: str,
    media_type: str = "text/turtle",
    slug: str | None = None,
) -> dict[str, Any]:
    """POST ``body`` to ``parent_iri``; return the new record with its ETag and state.

    The body is parsed bridge-side (syntax + single primary subject) and sent
    verbatim; the FDP validates it against the container's member shape.
    """
    validate_iri(parent_iri)
    validate_rdf_body(
        body, media_type, base_iri=parent_iri, max_bytes=settings.fdp_max_response_bytes
    )
    outcome = await create_member(client, parent_iri, body=body, media_type=media_type, slug=slug)
    resource = await fetch_resource(client, outcome.iri)
    return {
        "iri": resource.iri,
        "etag": resource.etag or outcome.etag,
        "state": record_state(resource),
        "record": record_object(resource, kind=kind_slug(resource)),
    }
