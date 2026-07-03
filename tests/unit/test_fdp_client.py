"""Unit tests for the strict-egress FDP HTTP client (task 1.2)."""

from __future__ import annotations

import httpx
import pytest
import respx

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import (
    EgressError,
    FdpResponseTooLargeError,
    FdpTimeoutError,
    FdpUpstreamError,
)

BASE = "https://fdp.example.org"


def _settings(**over: object) -> FdpMcpSettings:
    values: dict[str, object] = {"FDP_BASE_URL": BASE}
    return FdpMcpSettings(_env_file=None, **values, **over)  # type: ignore[arg-type]


async def test_get_returns_document_with_status_and_links() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/x").mock(
            return_value=httpx.Response(
                200,
                text="hello",
                headers={
                    "content-type": "text/turtle; charset=utf-8",
                    "link": '<https://fdp.example.org/x>; rel="cite-as"',
                },
            )
        )
        async with FdpClient(_settings()) as client:
            doc = await client.get(f"{BASE}/x")
    assert doc.status == 200
    assert doc.media_type == "text/turtle"
    assert doc.text == "hello"
    assert doc.links.cite_as == "https://fdp.example.org/x"


async def test_get_sends_accept_header() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/x").mock(return_value=httpx.Response(200, text="ok"))
        async with FdpClient(_settings()) as client:
            await client.get(f"{BASE}/x", accept="application/ld+json")
    assert route.calls.last.request.headers["accept"] == "application/ld+json"


async def test_off_origin_request_rejected_before_network() -> None:
    async with FdpClient(_settings()) as client:
        with pytest.raises(EgressError):
            await client.get("https://evil.example.org/x")


async def test_off_origin_redirect_rejected() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/redirect").mock(
            return_value=httpx.Response(302, headers={"location": "https://evil.example.org/"})
        )
        async with FdpClient(_settings()) as client:
            with pytest.raises(EgressError):
                await client.get(f"{BASE}/redirect")


async def test_same_origin_redirect_is_followed() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/a").mock(
            return_value=httpx.Response(302, headers={"location": f"{BASE}/b"})
        )
        mock.get(f"{BASE}/b").mock(return_value=httpx.Response(200, text="landed"))
        async with FdpClient(_settings()) as client:
            doc = await client.get(f"{BASE}/a")
    assert doc.text == "landed"


async def test_timeout_maps_to_fdp_timeout() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/slow").mock(side_effect=httpx.ConnectTimeout("boom"))
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpTimeoutError):
                await client.get(f"{BASE}/slow")


async def test_transport_error_maps_to_upstream() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/down").mock(side_effect=httpx.ConnectError("refused"))
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpUpstreamError):
                await client.get(f"{BASE}/down")


async def test_response_over_size_cap_is_rejected() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/big").mock(
            return_value=httpx.Response(
                200, text="x" * 1000, headers={"content-type": "text/turtle"}
            )
        )
        async with FdpClient(_settings(fdp_max_response_bytes=16)) as client:
            with pytest.raises(FdpResponseTooLargeError):
                await client.get(f"{BASE}/big")
