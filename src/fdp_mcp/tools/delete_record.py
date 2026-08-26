"""`delete_record` — delete one record (LDP DELETE under If-Match).

Contract: docs/mcp-tool-surface.md §5.11 (optional extension; ADR-0024).
"""

from __future__ import annotations

from typing import Any

from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import InvalidArgumentError
from fdp_mcp.fdp.write import delete_resource
from fdp_mcp.tools._common import validate_iri


async def handle(client: FdpClient, *, iri: str, if_match: str) -> dict[str, Any]:
    """DELETE ``iri`` under the ``if_match`` precondition."""
    validate_iri(iri)
    if not if_match:
        raise InvalidArgumentError("if_match is required: pass the etag from get_record")
    await delete_resource(client, iri, if_match=if_match)
    return {"iri": iri, "deleted": True}
