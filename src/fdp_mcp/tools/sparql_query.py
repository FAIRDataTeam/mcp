"""`sparql_query` — read-only SPARQL over the public endpoint.

Contract: docs/mcp-tool-surface.md §5.6 (optional, capability ``sparql``). The
read-only classification happens in the client layer *before* any network call;
this handler just shapes the result. Update forms raise ``ReadOnlyError``
(→ read_only_violation) and an absent endpoint raises ``FdpUnsupportedError``
(→ the unsupported result), both mapped in the registry.
"""

from __future__ import annotations

from typing import Any

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.sparql import run_query
from fdp_mcp.shaping import sparql_result_object


async def handle(client: FdpClient, settings: FdpMcpSettings, *, query: str) -> dict[str, Any]:
    """Execute a read-only SPARQL query and shape the result by form."""
    result = await run_query(client, settings.fdp_sparql_endpoint, query)
    return sparql_result_object(result)
