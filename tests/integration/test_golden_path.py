"""Integration: a real MCP client session drives the assembled server.

Uses the SDK's in-memory client/server pairing against ``build_server`` with the
FDP mocked in-process (respx). This exercises the full MCP layer — initialize,
list tools, call tools — end-to-end without a live container, walking the
golden path from the vision doc (search → get_record → get_access_conditions →
get_schema → sparql_query). Marked ``integration``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
import respx
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.server import build_server

pytestmark = pytest.mark.integration

TOOL_NAMES = {
    "fdp_info",
    "list_records",
    "get_record",
    "get_schema",
    "search",
    "sparql_query",
    "get_access_conditions",
    "list_data_services",
}


def _payload(result: CallToolResult) -> dict[str, Any]:
    """Extract the tool's JSON result from a CallToolResult."""
    assert result.isError is False
    if result.structuredContent is not None:
        return result.structuredContent
    block = result.content[0]
    assert block.type == "text"
    parsed: dict[str, Any] = json.loads(block.text)
    return parsed


async def test_golden_path_session(
    fdp_settings: FdpMcpSettings, register_fdpneo: Callable[..., None], base_url: str
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo(mock)
        server = build_server(fdp_settings)
        async with create_connected_server_and_client_session(server) as client:
            listed = await client.list_tools()
            assert {tool.name for tool in listed.tools} >= TOOL_NAMES

            info = _payload(await client.call_tool("fdp_info", {}))
            assert info["repository"]["iri"] == base_url
            assert info["endpoints"]["sparql"] is True

            found = _payload(await client.call_tool("search", {"query": "dataset"}))
            assert found["items"][0]["iri"] == f"{base_url}/dataset/1"

            record = _payload(
                await client.call_tool("get_record", {"iri": f"{base_url}/dataset/1"})
            )
            assert record["kind"] == "dataset"
            assert record["links"]["constrained_by"] == f"{base_url}/schema/dataset"

            access = _payload(
                await client.call_tool("get_access_conditions", {"iri": f"{base_url}/dataset/1"})
            )
            assert access["license"]["open"] is True
            assert access["contacts"][0]["email"] == "mailto:dac@example.org"

            schema = _payload(await client.call_tool("get_schema", {"kind": "dataset"}))
            assert schema["shape_iri"] == f"{base_url}/schema/dataset"

            select = _payload(
                await client.call_tool("sparql_query", {"query": "SELECT * WHERE { ?s ?p ?o }"})
            )
            assert select["form"] == "select"

            services = _payload(await client.call_tool("list_data_services", {}))
            assert (
                services["items"][0]["service"]["endpoint_url"] == "https://beacon.example.org/api"
            )


async def test_optional_tool_degrades_over_mcp(
    fdp_settings: FdpMcpSettings, register_fdpneo: Callable[..., None]
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo(mock, search=False)
        server = build_server(fdp_settings)
        async with create_connected_server_and_client_session(server) as client:
            result = _payload(await client.call_tool("search", {"query": "x"}))
    assert result["unsupported"]["capability"] == "search-api"
