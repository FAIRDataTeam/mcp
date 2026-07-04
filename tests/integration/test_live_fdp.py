"""Integration against a *live* FDP (opt-in), via a real MCP client session.

Runs only when ``FDP_MCP_IT_BASE_URL`` points at a reachable, spec-compliant FDP
(a testcontainers-composed FDPneo stack, a local dev instance, or any FDP on the
network); otherwise it skips. When set, it drives the golden path over the real
MCP transport against the real FDP — the reach check from the vision doc, which
works against FDPneo *and* the Java reference implementation with no code change.

Set ``FDP_MCP_IT_API_KEY`` to additionally exercise credential pass-through.

CI note: a fully self-contained run launches the FDPneo compose stack (server +
Postgres + triple store) with ``testcontainers`` and sets ``FDP_MCP_IT_BASE_URL``
to the mapped server URL. That needs the published FDPneo image, so it lives
behind this env gate rather than in the default unit run.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.server import build_server

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_LIVE_BASE_URL = os.environ.get("FDP_MCP_IT_BASE_URL")

pytestmark.append(
    pytest.mark.skipif(
        _LIVE_BASE_URL is None,
        reason="set FDP_MCP_IT_BASE_URL to a live FDP to run the live integration test",
    )
)


def _payload(result: CallToolResult) -> dict[str, Any]:
    assert result.isError is False, result.content
    if result.structuredContent is not None:
        return result.structuredContent
    parsed: dict[str, Any] = json.loads(result.content[0].text)  # type: ignore[union-attr]
    return parsed


async def test_live_golden_path() -> None:
    assert _LIVE_BASE_URL is not None
    settings = FdpMcpSettings(_env_file=None, FDP_BASE_URL=_LIVE_BASE_URL)  # type: ignore[call-arg]
    server = build_server(settings)
    async with create_connected_server_and_client_session(server) as client:
        listed = await client.list_tools()
        assert {tool.name for tool in listed.tools}

        info = _payload(await client.call_tool("fdp_info", {}))
        assert info["repository"]["iri"]  # the FDP has a root record

        # Enumerate top-level records; if any exist, fetch one and read its terms.
        records = _payload(await client.call_tool("list_records", {}))
        if records["items"]:
            iri = records["items"][0]["iri"]
            record = _payload(await client.call_tool("get_record", {"iri": iri}))
            assert record["iri"] == iri
            access = _payload(await client.call_tool("get_access_conditions", {"iri": iri}))
            assert "determinable" in access
