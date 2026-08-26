"""Integration: an authenticated MCP session walks the write golden path.

create_record → get_record (etag) → update_record (PUT, If-Match) →
set_record_state (PUBLISHED) → delete_record, over the assembled server with
``FDP_MCP_ENABLE_WRITE`` on and the FDP mocked in-process. The in-memory
transport carries no HTTP headers, so the session is made authenticated by
patching the registry's session resolver (no production seam). Also checks
that the write tools are invisible with the flag off. Marked ``integration``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
import respx
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult
from pydantic import SecretStr

import fdp_mcp.tools.registry as registry
from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.server import build_server
from fdp_mcp.session import SessionContext
from tests.conftest import BASE, NEW_DATASET, NEW_DATASET_TTL, WriteSurface

pytestmark = pytest.mark.integration

WRITE_TOOLS = {"create_record", "update_record", "delete_record", "set_record_state"}
SECRET = "fdpk_write-key"


def _payload(result: CallToolResult) -> dict[str, Any]:
    assert result.isError is False
    if result.structuredContent is not None:
        return result.structuredContent
    block = result.content[0]
    assert block.type == "text"
    parsed: dict[str, Any] = json.loads(block.text)
    return parsed


def _write_settings() -> FdpMcpSettings:
    return FdpMcpSettings(_env_file=None, FDP_BASE_URL=BASE, enable_write=True)  # type: ignore[call-arg]


async def test_write_tools_hidden_when_disabled(fdp_settings: FdpMcpSettings) -> None:
    async with create_connected_server_and_client_session(build_server(fdp_settings)) as client:
        listed = await client.list_tools()
    assert {tool.name for tool in listed.tools}.isdisjoint(WRITE_TOOLS)


async def test_golden_write_path(
    monkeypatch: pytest.MonkeyPatch,
    register_fdpneo: Callable[..., None],
    register_fdpneo_write: Callable[[respx.MockRouter], None],
    write_surface: WriteSurface,
) -> None:
    settings = _write_settings()

    def authenticated_session(_ctx: object, _settings: FdpMcpSettings) -> SessionContext:
        return SessionContext(session_id="it", fdp_base_url=BASE, credential=SecretStr(SECRET))

    monkeypatch.setattr(registry, "_session", authenticated_session)
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo(mock)
        register_fdpneo_write(mock)
        async with create_connected_server_and_client_session(build_server(settings)) as client:
            listed = await client.list_tools()
            assert {tool.name for tool in listed.tools} >= WRITE_TOOLS

            created = _payload(
                await client.call_tool(
                    "create_record", {"parent_iri": f"{BASE}/catalog/1", "body": NEW_DATASET_TTL}
                )
            )
            assert created["iri"] == NEW_DATASET
            assert created["state"] == "DRAFT"

            fetched = _payload(await client.call_tool("get_record", {"iri": NEW_DATASET}))
            assert fetched["etag"] == created["etag"]

            stale = _payload(
                await client.call_tool(
                    "update_record",
                    {"iri": NEW_DATASET, "if_match": '"nope"', "body": NEW_DATASET_TTL},
                )
            )
            assert stale["error"]["code"] == "precondition_failed"

            updated = _payload(
                await client.call_tool(
                    "update_record",
                    {"iri": NEW_DATASET, "if_match": fetched["etag"], "body": NEW_DATASET_TTL},
                )
            )
            assert updated["mode"] == "replace"

            published = _payload(
                await client.call_tool("set_record_state", {"iri": NEW_DATASET, "to": "PUBLISHED"})
            )
            assert published["to_state"] == "PUBLISHED"

            deleted = _payload(
                await client.call_tool(
                    "delete_record", {"iri": NEW_DATASET, "if_match": updated["etag"]}
                )
            )
            assert deleted["deleted"] is True

    # Every write carried the forwarded credential, verbatim.
    assert write_surface.requests
    assert all(r.headers.get("authorization") == f"Bearer {SECRET}" for r in write_surface.requests)
    assert write_surface.exists is False
