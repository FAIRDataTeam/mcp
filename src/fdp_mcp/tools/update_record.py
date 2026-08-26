"""`update_record` — replace (PUT) or patch (SPARQL-update PATCH) one record.

Contract: docs/mcp-tool-surface.md §5.10 (optional extension; ADR-0024).
"""

from __future__ import annotations

from typing import Any

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import InvalidArgumentError
from fdp_mcp.fdp.ldp import fetch_resource
from fdp_mcp.fdp.write import (
    patch_resource,
    replace_resource,
    validate_rdf_body,
    validate_update,
)
from fdp_mcp.shaping import record_object
from fdp_mcp.tools._common import kind_slug, validate_iri


async def handle(
    client: FdpClient,
    settings: FdpMcpSettings,
    *,
    iri: str,
    if_match: str,
    body: str | None = None,
    media_type: str = "text/turtle",
    patch: str | None = None,
) -> dict[str, Any]:
    """Update ``iri`` under the ``if_match`` precondition; exactly one of body/patch.

    ``body`` → full replacement (PUT, portable). ``patch`` → SPARQL update
    (PATCH, optional capability ``ldp_patch``; degrades to ``unsupported``).
    """
    validate_iri(iri)
    if not if_match:
        raise InvalidArgumentError("if_match is required: pass the etag from get_record")
    if (body is None) == (patch is None):
        raise InvalidArgumentError("provide exactly one of body (replace) or patch (SPARQL update)")
    if body is not None:
        validate_rdf_body(body, media_type, base_iri=iri, max_bytes=settings.fdp_max_response_bytes)
        outcome = await replace_resource(
            client, iri, body=body, media_type=media_type, if_match=if_match
        )
        mode = "replace"
    else:
        assert patch is not None
        validate_update(patch, origin=settings.fdp_origin)
        outcome = await patch_resource(client, iri, update=patch, if_match=if_match)
        mode = "patch"
    resource = await fetch_resource(client, iri)
    return {
        "iri": resource.iri,
        "etag": resource.etag or outcome.etag,
        "mode": mode,
        "record": record_object(resource, kind=kind_slug(resource)),
    }
