"""`fdp_info` — describe the repository and the kinds it holds.

Contract: docs/mcp-tool-surface.md §5.1 (required). Reports the root record, the
runtime-discovered kinds, and which optional endpoints (SPARQL, search) this FDP
supports, so an agent knows up front what will work.
"""

from __future__ import annotations

from typing import Any

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import FdpError, FdpUnsupportedError
from fdp_mcp.fdp.ldp import discover_root
from fdp_mcp.fdp.search import run_search
from fdp_mcp.fdp.sparql import run_query
from fdp_mcp.shaping import record_object
from fdp_mcp.tools._common import Format


async def handle(
    client: FdpClient, settings: FdpMcpSettings, *, fmt: Format = "jsonld"
) -> dict[str, Any]:
    """Describe the repository, its kinds, and its optional endpoints."""
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
    endpoints = {
        "sparql": await _supports_sparql(client, settings),
        "search": await _supports_search(client, settings),
    }
    return {
        "repository": record_object(discovery.root, kind=root_kind, fmt=fmt),
        "kinds": kinds,
        "endpoints": endpoints,
    }


async def _supports_sparql(client: FdpClient, settings: FdpMcpSettings) -> bool:
    try:
        await run_query(client, settings.fdp_sparql_endpoint, "ASK {}")
    except (FdpUnsupportedError, FdpError):
        return False
    return True


async def _supports_search(client: FdpClient, settings: FdpMcpSettings) -> bool:
    try:
        await run_search(client, settings.fdp_search_endpoint, query="*", limit=1)
    except (FdpUnsupportedError, FdpError):
        return False
    return True
