"""`set_record_state` — move a record between DRAFT / PUBLISHED / ARCHIVED.

Contract: docs/mcp-tool-surface.md §5.12 (optional extension; capability
``state_transition``; ADR-0024).
"""

from __future__ import annotations

from typing import Any

from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import FdpError
from fdp_mcp.fdp.ldp import fetch_resource
from fdp_mcp.fdp.write import transition_state
from fdp_mcp.shaping import record_object
from fdp_mcp.tools._common import kind_slug, validate_iri


async def handle(client: FdpClient, *, iri: str, to: str) -> dict[str, Any]:
    """Request the transition; the FDP decides (409 for a disallowed one)."""
    validate_iri(iri)
    outcome = await transition_state(client, iri, to=to)
    record: dict[str, Any] | None
    try:
        resource = await fetch_resource(client, outcome.iri)
        record = record_object(resource, kind=kind_slug(resource))
    except FdpError:
        # e.g. unpublishing to DRAFT may hide the record from this credential.
        record = None
    return {
        "iri": outcome.iri,
        "from_state": outcome.from_state,
        "to_state": outcome.to_state,
        "record": record,
    }
