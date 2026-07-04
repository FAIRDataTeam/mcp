"""`get_record` — full metadata of one record, with signposting links.

Contract: docs/mcp-tool-surface.md §5.3 (required).
"""

from __future__ import annotations

from typing import Any

from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.ldp import fetch_resource
from fdp_mcp.shaping import record_object
from fdp_mcp.tools._common import Format, accept_for, kind_slug, validate_iri


async def handle(client: FdpClient, *, iri: str, fmt: Format = "jsonld") -> dict[str, Any]:
    """Fetch one record and shape it as a Record object.

    Raises ``InvalidArgumentError`` (bad IRI), ``FdpNotFoundError`` (unknown or
    hidden), and the client's transport errors.
    """
    validate_iri(iri)
    resource = await fetch_resource(client, iri, accept=accept_for(fmt))
    return record_object(resource, kind=kind_slug(resource), fmt=fmt)
