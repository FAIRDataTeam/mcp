"""Unit tests for endpoint discovery from the FDP root (ADR-0018 G-05)."""

from __future__ import annotations

import httpx
import respx
from rdflib import Graph

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.discovery import (
    advertised_search_endpoint,
    advertised_sparql_endpoint,
    resolve_search_endpoint,
    resolve_sparql_endpoint,
)

BASE = "https://fdp.example.org"
ROOT = BASE


def _settings(**overrides: object) -> FdpMcpSettings:
    return FdpMcpSettings(_env_file=None, FDP_BASE_URL=BASE, **overrides)  # type: ignore[arg-type]


def _graph(ttl: str) -> Graph:
    g = Graph()
    g.parse(data=ttl, format="turtle")
    return g


# A root advertising both endpoints, FDPneo-style (custom paths to prove the
# advertised value is used, not the default).
_ADVERTISED = """
@prefix void: <http://rdfs.org/ns/void#> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
<https://fdp.example.org>
    void:sparqlEndpoint <https://fdp.example.org/custom/sparql> ;
    dcat:service
        [ a dcat:DataService ;
          dcat:endpointURL <https://fdp.example.org/custom/sparql> ;
          dcat:endpointDescription <https://www.w3.org/TR/sparql11-protocol/> ] ,
        [ a dcat:DataService ;
          dcat:endpointURL <https://fdp.example.org/custom/search> ] .
"""


# --- pure extraction --------------------------------------------------------


def test_advertised_sparql_from_void() -> None:
    g = _graph(_ADVERTISED)
    assert advertised_sparql_endpoint(g, ROOT) == "https://fdp.example.org/custom/sparql"


def test_advertised_sparql_from_dataservice_description_when_no_void() -> None:
    ttl = """
    @prefix dcat: <http://www.w3.org/ns/dcat#> .
    <https://fdp.example.org> dcat:service
        [ a dcat:DataService ;
          dcat:endpointURL <https://fdp.example.org/q/sparql> ;
          dcat:endpointDescription <https://www.w3.org/TR/sparql11-protocol/> ] .
    """
    assert advertised_sparql_endpoint(_graph(ttl), ROOT) == "https://fdp.example.org/q/sparql"


def test_advertised_search_is_the_single_non_sparql_service() -> None:
    g = _graph(_ADVERTISED)
    sparql = advertised_sparql_endpoint(g, ROOT)
    assert advertised_search_endpoint(g, ROOT, sparql_endpoint=sparql) == (
        "https://fdp.example.org/custom/search"
    )


def test_advertised_search_none_when_ambiguous() -> None:
    ttl = """
    @prefix dcat: <http://www.w3.org/ns/dcat#> .
    <https://fdp.example.org> dcat:service
        [ a dcat:DataService ; dcat:endpointURL <https://fdp.example.org/a> ] ,
        [ a dcat:DataService ; dcat:endpointURL <https://fdp.example.org/b> ] .
    """
    assert advertised_search_endpoint(_graph(ttl), ROOT, sparql_endpoint=None) is None


def test_advertised_none_when_root_silent() -> None:
    g = _graph(
        "@prefix ldp: <http://www.w3.org/ns/ldp#> .\n<https://fdp.example.org> a ldp:Container ."
    )
    assert advertised_sparql_endpoint(g, ROOT) is None
    assert advertised_search_endpoint(g, ROOT) is None


# --- resolver precedence ----------------------------------------------------


async def test_resolver_prefers_advertised_on_origin() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/").mock(
            return_value=httpx.Response(
                200, text=_ADVERTISED, headers={"content-type": "text/turtle"}
            )
        )
        async with FdpClient(_settings()) as client:
            sparql = await resolve_sparql_endpoint(client, _settings())
            search = await resolve_search_endpoint(client, _settings())
    assert sparql == "https://fdp.example.org/custom/sparql"
    assert search == "https://fdp.example.org/custom/search"


async def test_explicit_override_beats_advertisement() -> None:
    settings = _settings(fdp_sparql_path="/my/sparql")
    with respx.mock(assert_all_called=False) as mock:
        root = mock.get(f"{BASE}/").mock(
            return_value=httpx.Response(
                200, text=_ADVERTISED, headers={"content-type": "text/turtle"}
            )
        )
        async with FdpClient(settings) as client:
            sparql = await resolve_sparql_endpoint(client, settings)
    assert sparql == "https://fdp.example.org/my/sparql"  # configured wins
    assert root.call_count == 0  # no root fetch needed when overridden


async def test_offorigin_advertisement_ignored() -> None:
    ttl = """
    @prefix void: <http://rdfs.org/ns/void#> .
    <https://fdp.example.org> void:sparqlEndpoint <https://evil.example.org/sparql> .
    """
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/").mock(
            return_value=httpx.Response(200, text=ttl, headers={"content-type": "text/turtle"})
        )
        async with FdpClient(_settings()) as client:
            sparql = await resolve_sparql_endpoint(client, _settings())
    # Off-origin advertisement is refused; fall back to the configured default.
    assert sparql == f"{BASE}/fdp-api/sparql"


async def test_root_fetch_failure_falls_back_to_configured() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/").mock(return_value=httpx.Response(503))
        async with FdpClient(_settings()) as client:
            sparql = await resolve_sparql_endpoint(client, _settings())
    assert sparql == f"{BASE}/fdp-api/sparql"


async def test_root_is_memoized_across_resolves() -> None:
    with respx.mock(assert_all_called=False) as mock:
        root = mock.get(f"{BASE}/").mock(
            return_value=httpx.Response(
                200, text=_ADVERTISED, headers={"content-type": "text/turtle"}
            )
        )
        async with FdpClient(_settings()) as client:
            await resolve_sparql_endpoint(client, _settings())
            await resolve_search_endpoint(client, _settings())
    assert root.call_count == 1  # fetched once, reused (per-session memo)
