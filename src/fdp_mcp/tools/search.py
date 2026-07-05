"""`search` — keyword/faceted discovery within the FDP.

Contract: docs/mcp-tool-surface.md §5.5 (optional, capability ``search-api``).
Maps the contract's generic ``filters`` onto the FDP search parameters; an
absent search API raises ``FdpUnsupportedError`` (→ the unsupported result).
"""

from __future__ import annotations

from typing import Any

from rdflib import Graph

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.discovery import resolve_search_endpoint
from fdp_mcp.fdp.ldp import discover_root
from fdp_mcp.fdp.search import run_search
from fdp_mcp.shaping import page_envelope, search_hit_object
from fdp_mcp.tools._common import clamp_limit


async def handle(
    client: FdpClient,
    settings: FdpMcpSettings,
    *,
    query: str,
    filters: dict[str, Any] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Run a search and shape hits into a page of summary Record objects."""
    filters = filters or {}
    limit = clamp_limit(limit)
    offset = max(0, offset)

    types = list(filters.get("types", []))
    # A `kind` slug is resolved to its type IRIs via discovery (optional facet).
    # Reuse that root fetch for endpoint discovery (G-05) when it happens.
    kind = filters.get("kind")
    root_graph: Graph | None = None
    root_iri: str | None = None
    if kind:
        discovery = await discover_root(client)
        root_graph, root_iri = discovery.root.graph, discovery.root.iri
        match = next((k for k in discovery.kinds if k.slug == kind), None)
        if match is not None:
            types.extend(match.type_iris)

    endpoint = await resolve_search_endpoint(
        client, settings, root_graph=root_graph, root_iri=root_iri
    )
    result = await run_search(
        client,
        endpoint,
        query=query,
        types=types or None,
        license=filters.get("license"),
        language=filters.get("language"),
        updated_from=filters.get("from"),
        updated_to=filters.get("to"),
        limit=limit,
        offset=offset,
    )
    items = [search_hit_object(hit) for hit in result.items]
    return page_envelope(items, limit=limit, offset=offset, total=result.total)
