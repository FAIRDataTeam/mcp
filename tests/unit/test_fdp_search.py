"""Unit tests for the search client + capability degradation (task 1.3)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import FdpUnsupportedError
from fdp_mcp.fdp.search import run_search

BASE = "https://fdp.example.org"
SEARCH = f"{BASE}/fdp-api/search"


def _settings() -> FdpMcpSettings:
    return FdpMcpSettings(_env_file=None, FDP_BASE_URL=BASE)  # type: ignore[call-arg]


async def test_search_parses_items_total_and_facets() -> None:
    payload = {
        "items": [
            {
                "recordIri": "https://fdp.example.org/dataset/1",
                "typeIri": "http://www.w3.org/ns/dcat#Dataset",
                "title": "Cohort X",
                "description": "…",
                "license": "https://creativecommons.org/licenses/by/4.0/",
                "state": "PUBLISHED",
                "updatedAt": "2026-07-01T00:00:00Z",
            }
        ],
        "total": 1,
        "facets": {"type": {"label": "Type", "values": [{"value": "dcat:Dataset", "count": 1}]}},
    }
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(SEARCH).mock(
            return_value=httpx.Response(
                200, text=json.dumps(payload), headers={"content-type": "application/json"}
            )
        )
        async with FdpClient(_settings()) as client:
            result = await run_search(
                client, SEARCH, query="cohort", types=["http://www.w3.org/ns/dcat#Dataset"]
            )

    assert result.total == 1
    assert result.items[0].record_iri == "https://fdp.example.org/dataset/1"
    assert result.items[0].title == "Cohort X"
    assert "type" in result.facets
    sent = json.loads(route.calls.last.request.content)
    assert sent["query"] == "cohort"
    assert sent["types"] == ["http://www.w3.org/ns/dcat#Dataset"]


async def test_search_absent_degrades_to_unsupported() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(SEARCH).mock(return_value=httpx.Response(404))
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpUnsupportedError) as exc_info:
                await run_search(client, SEARCH, query="x")
    assert exc_info.value.capability == "search-api"
    assert exc_info.value.alternative is not None


async def test_search_missing_total_is_none() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(SEARCH).mock(
            return_value=httpx.Response(
                200, text=json.dumps({"items": []}), headers={"content-type": "application/json"}
            )
        )
        async with FdpClient(_settings()) as client:
            result = await run_search(client, SEARCH, query="x")
    assert result.items == []
    assert result.total is None
    assert result.facets == {}
