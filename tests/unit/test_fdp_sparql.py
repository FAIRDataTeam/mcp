"""Unit tests for the read-only SPARQL client (task 1.3)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import FdpUnsupportedError, InvalidQueryError, ReadOnlyError
from fdp_mcp.fdp.sparql import (
    AskResult,
    GraphResult,
    SelectResult,
    classify_query,
    run_query,
)

BASE = "https://fdp.example.org"
SPARQL = f"{BASE}/fdp-api/sparql"


def _settings() -> FdpMcpSettings:
    return FdpMcpSettings(_env_file=None, FDP_BASE_URL=BASE)  # type: ignore[call-arg]


# --- read-only classification (no network) ----------------------------------


def test_classify_read_forms() -> None:
    assert classify_query("SELECT * WHERE { ?s ?p ?o }") == "select"
    assert classify_query("ASK { ?s ?p ?o }") == "ask"
    assert classify_query("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }") == "construct"
    assert classify_query("DESCRIBE <http://x>") == "describe"


@pytest.mark.parametrize(
    "query",
    [
        "INSERT DATA { <a> <b> <c> }",
        "DELETE WHERE { ?s ?p ?o }",
        "CLEAR ALL",
        "LOAD <http://x>",
        "DROP GRAPH <http://g>",
    ],
)
def test_update_forms_rejected(query: str) -> None:
    with pytest.raises(ReadOnlyError):
        classify_query(query)


def test_service_clause_rejected() -> None:
    with pytest.raises(InvalidQueryError):
        classify_query("SELECT * WHERE { SERVICE <http://evil/> { ?s ?p ?o } }")


def test_malformed_query_rejected() -> None:
    with pytest.raises(InvalidQueryError):
        classify_query("this is not sparql")


# --- execution --------------------------------------------------------------


async def test_select_returns_results_json() -> None:
    payload = {
        "head": {"vars": ["s"]},
        "results": {"bindings": [{"s": {"type": "uri", "value": "https://fdp.example.org/x"}}]},
    }
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(SPARQL).mock(
            return_value=httpx.Response(
                200,
                text=json.dumps(payload),
                headers={"content-type": "application/sparql-results+json"},
            )
        )
        async with FdpClient(_settings()) as client:
            result = await run_query(client, SPARQL, "SELECT * WHERE { ?s ?p ?o }")

    assert isinstance(result, SelectResult)
    assert result.head == {"vars": ["s"]}
    assert result.results["bindings"][0]["s"]["value"] == "https://fdp.example.org/x"
    # Read-only enforcement is proven by the query being forwarded as-is.
    assert route.calls.last.request.headers["content-type"] == "application/sparql-query"
    assert route.calls.last.request.headers["accept"] == "application/sparql-results+json"


async def test_ask_returns_boolean() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(SPARQL).mock(
            return_value=httpx.Response(
                200,
                text=json.dumps({"head": {}, "boolean": True}),
                headers={"content-type": "application/sparql-results+json"},
            )
        )
        async with FdpClient(_settings()) as client:
            result = await run_query(client, SPARQL, "ASK { ?s ?p ?o }")
    assert isinstance(result, AskResult)
    assert result.boolean is True


async def test_construct_returns_graph() -> None:
    turtle = "<https://fdp.example.org/s> <https://fdp.example.org/p> <https://fdp.example.org/o> ."
    with respx.mock(assert_all_called=False) as mock:
        mock.post(SPARQL).mock(
            return_value=httpx.Response(200, text=turtle, headers={"content-type": "text/turtle"})
        )
        async with FdpClient(_settings()) as client:
            result = await run_query(client, SPARQL, "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
    assert isinstance(result, GraphResult)
    assert result.form == "construct"
    assert len(result.graph) == 1


async def test_update_is_rejected_before_any_network_call() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(SPARQL).mock(return_value=httpx.Response(200, text="{}"))
        async with FdpClient(_settings()) as client:
            with pytest.raises(ReadOnlyError):
                await run_query(client, SPARQL, "INSERT DATA { <a> <b> <c> }")
    assert route.call_count == 0  # never sent


async def test_missing_endpoint_degrades_to_unsupported() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(SPARQL).mock(return_value=httpx.Response(404))
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpUnsupportedError) as exc_info:
                await run_query(client, SPARQL, "SELECT * WHERE { ?s ?p ?o }")
    assert exc_info.value.capability == "sparql"
