"""`fdp_info` — describe the repository and the kinds it holds.

Contract: docs/mcp-tool-surface.md §5.1 (required). Reports the root record, the
runtime-discovered kinds, and which optional endpoints (SPARQL, search) this FDP
supports, so an agent knows up front what will work.
"""

from __future__ import annotations

from typing import Any

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.discovery import resolve_search_endpoint, resolve_sparql_endpoint
from fdp_mcp.fdp.errors import FdpError, FdpUnsupportedError
from fdp_mcp.fdp.ldp import discover_root
from fdp_mcp.fdp.search import run_search
from fdp_mcp.fdp.sparql import run_query
from fdp_mcp.shaping import record_object
from fdp_mcp.tools._common import Format


async def handle(
    client: FdpClient, settings: FdpMcpSettings, *, fmt: Format = "jsonld"
) -> dict[str, Any]:
    """Describe the repository, its kinds, and its optional endpoints.

    The SPARQL/search endpoints are resolved from the root advertisement (G-05)
    when present — reusing the root fetch discovery already did — then probed, so
    the reported support reflects the endpoints the other tools will actually use.
    """
    discovery = await discover_root(client)
    kinds = [
        {
            "slug": kind.slug,
            "type_iris": list(kind.type_iris),
            "label": kind.label,
            "top_level": kind.top_level,
        }
        for kind in discovery.kinds
    ]
    root_kind = next((kind.slug for kind in discovery.kinds if kind.is_root), None)
    graph, root_iri = discovery.root.graph, discovery.root.iri
    sparql_endpoint = await resolve_sparql_endpoint(
        client, settings, root_graph=graph, root_iri=root_iri
    )
    search_endpoint = await resolve_search_endpoint(
        client, settings, root_graph=graph, root_iri=root_iri
    )
    endpoints = {
        "sparql": await _supports_sparql(client, sparql_endpoint),
        "search": await _supports_search(client, search_endpoint),
    }
    return {
        "repository": record_object(discovery.root, kind=root_kind, fmt=fmt),
        "kinds": kinds,
        "endpoints": endpoints,
        # True when kind discovery hit the crawl cap, so `kinds` may be partial.
        "truncated": discovery.truncated,
    }


async def _supports_sparql(client: FdpClient, endpoint: str) -> bool:
    try:
        await run_query(client, endpoint, "ASK {}")
    except (FdpUnsupportedError, FdpError):
        return False
    return True


async def _supports_search(client: FdpClient, endpoint: str) -> bool:
    try:
        await run_search(client, endpoint, query="*", limit=1)
    except (FdpUnsupportedError, FdpError):
        return False
    return True
