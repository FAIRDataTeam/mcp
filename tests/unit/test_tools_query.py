"""Unit tests for the query tools (task 2.2).

Covers search / sparql_query / get_access_conditions / list_data_services over
respx fixtures, including the explicit-degrade paths and the read-only guarantee.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import FdpUnsupportedError, ReadOnlyError
from fdp_mcp.tools import get_access_conditions, list_data_services, search, sparql_query

BASE = "https://fdp.example.org"
SPARQL = f"{BASE}/fdp-api/sparql"
SEARCH = f"{BASE}/fdp-api/search"


def _settings() -> FdpMcpSettings:
    return FdpMcpSettings(_env_file=None, FDP_BASE_URL=BASE)  # type: ignore[call-arg]


def _ttl(mock: respx.MockRouter, url: str, body: str, *, link: str | None = None) -> None:
    headers = {"content-type": "text/turtle"}
    if link is not None:
        headers["link"] = link
    mock.get(url).mock(return_value=httpx.Response(200, text=body, headers=headers))


# --- sparql_query -----------------------------------------------------------


async def test_sparql_select_shape() -> None:
    payload: dict[str, Any] = {"head": {"vars": ["s"]}, "results": {"bindings": []}}
    with respx.mock(assert_all_called=False) as mock:
        mock.post(SPARQL).mock(
            return_value=httpx.Response(
                200,
                text=json.dumps(payload),
                headers={"content-type": "application/sparql-results+json"},
            )
        )
        async with FdpClient(_settings()) as client:
            result = await sparql_query.handle(
                client, _settings(), query="SELECT * WHERE { ?s ?p ?o }"
            )
    assert result == {"form": "select", "head": {"vars": ["s"]}, "results": {"bindings": []}}


async def test_sparql_construct_returns_framed_graph() -> None:
    turtle = '<https://fdp.example.org/s> <http://purl.org/dc/terms/title> "T" .'
    with respx.mock(assert_all_called=False) as mock:
        mock.post(SPARQL).mock(
            return_value=httpx.Response(200, text=turtle, headers={"content-type": "text/turtle"})
        )
        async with FdpClient(_settings()) as client:
            result = await sparql_query.handle(
                client, _settings(), query="CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"
            )
    assert result["form"] == "construct"
    assert result["graph"]["@graph"][0]["@id"] == "https://fdp.example.org/s"


async def test_sparql_update_rejected_before_network() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(SPARQL).mock(return_value=httpx.Response(200, text="{}"))
        async with FdpClient(_settings()) as client:
            with pytest.raises(ReadOnlyError):
                await sparql_query.handle(client, _settings(), query="DELETE WHERE { ?s ?p ?o }")
    assert route.call_count == 0


async def test_sparql_absent_endpoint_unsupported() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(SPARQL).mock(return_value=httpx.Response(404))
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpUnsupportedError) as exc_info:
                await sparql_query.handle(client, _settings(), query="ASK {}")
    assert exc_info.value.capability == "sparql"


# --- search -----------------------------------------------------------------


async def test_search_shapes_hits_into_page() -> None:
    payload: dict[str, Any] = {
        "items": [
            {
                "recordIri": "https://fdp.example.org/dataset/1",
                "typeIri": "http://www.w3.org/ns/dcat#Dataset",
                "title": "Cohort X",
                "description": "desc",
                "license": None,
                "state": "PUBLISHED",
                "updatedAt": None,
            }
        ],
        "total": 1,
    }
    with respx.mock(assert_all_called=False) as mock:
        mock.post(SEARCH).mock(
            return_value=httpx.Response(
                200, text=json.dumps(payload), headers={"content-type": "application/json"}
            )
        )
        async with FdpClient(_settings()) as client:
            result = await search.handle(client, _settings(), query="cohort")
    assert result["page"]["total"] == 1
    hit = result["items"][0]
    assert hit["iri"] == "https://fdp.example.org/dataset/1"
    assert hit["kind"] == "dataset"
    assert hit["metadata"]["dcterms:title"] == "Cohort X"


async def test_search_absent_unsupported() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(SEARCH).mock(return_value=httpx.Response(404))
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpUnsupportedError) as exc_info:
                await search.handle(client, _settings(), query="x")
    assert exc_info.value.capability == "search-api"


# --- get_access_conditions --------------------------------------------------

_ACCESS_TTL = """
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix vcard: <http://www.w3.org/2006/vcard/ns#> .
<https://fdp.example.org/dataset/1> a dcat:Dataset ;
    dcterms:license <https://creativecommons.org/licenses/by/4.0/> ;
    dcterms:rights <https://fdp.example.org/policies/1> ;
    dcat:contactPoint [ a vcard:Kind ; vcard:fn "Data Access Committee" ;
                        vcard:hasEmail <mailto:dac@example.org> ] .
"""
_POLICY_TTL = """
@prefix odrl: <http://www.w3.org/ns/odrl/2/> .
@prefix dcterms: <http://purl.org/dc/terms/> .
<https://fdp.example.org/policies/1> a odrl:Offer ; dcterms:title "Academic use" .
"""


async def test_access_conditions_resolves_license_policy_contact() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _ttl(mock, f"{BASE}/dataset/1", _ACCESS_TTL)
        _ttl(mock, f"{BASE}/policies/1", _POLICY_TTL)
        async with FdpClient(_settings()) as client:
            result = await get_access_conditions.handle(client, iri=f"{BASE}/dataset/1")

    assert result["determinable"] is True
    assert result["license"]["iri"] == "https://creativecommons.org/licenses/by/4.0/"
    assert result["license"]["open"] is True  # judged from a known-open IRI
    assert result["policies"][0]["iri"] == "https://fdp.example.org/policies/1"
    # On-origin Offer document is enriched (allowed egress).
    assert result["policies"][0]["type"] == "http://www.w3.org/ns/odrl/2/Offer"
    assert result["policies"][0]["summary"] == "Academic use"
    assert result["contacts"][0]["name"] == "Data Access Committee"
    assert result["contacts"][0]["email"] == "mailto:dac@example.org"


async def test_access_conditions_undeterminable_when_metadata_silent() -> None:
    body = "@prefix dcat: <http://www.w3.org/ns/dcat#> .\n<https://fdp.example.org/d/2> a dcat:Dataset ."
    with respx.mock(assert_all_called=False) as mock:
        _ttl(mock, f"{BASE}/d/2", body)
        async with FdpClient(_settings()) as client:
            result = await get_access_conditions.handle(client, iri=f"{BASE}/d/2")
    assert result["determinable"] is False
    assert result["license"] is None
    assert result["policies"] == []


# --- list_data_services -----------------------------------------------------

_ROOT = """
@prefix ldp: <http://www.w3.org/ns/ldp#> .
<https://fdp.example.org> a ldp:Container ; ldp:contains <https://fdp.example.org/catalog/1> .
"""
_CATALOG = """
@prefix ldp: <http://www.w3.org/ns/ldp#> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
<https://fdp.example.org/catalog/1> a dcat:Catalog, ldp:Container ;
    ldp:contains <https://fdp.example.org/service/1> .
"""
_SERVICE = """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
<https://fdp.example.org/service/1> a dcat:DataService ;
    dcterms:title "Beacon endpoint" ;
    dcat:endpointURL <https://beacon.example.org/api> ;
    dcat:servesDataset <https://fdp.example.org/dataset/1> ;
    dcterms:conformsTo <http://en.wikipedia.org/wiki/Beacon_v2> .
"""


async def test_list_data_services_enumerates_with_service_block() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _ttl(mock, f"{BASE}/", _ROOT)
        _ttl(mock, f"{BASE}/catalog/1", _CATALOG)
        _ttl(mock, f"{BASE}/service/1", _SERVICE)
        async with FdpClient(_settings()) as client:
            result = await list_data_services.handle(client)

    assert result["page"]["total"] == 1
    item = result["items"][0]
    assert item["iri"] == "https://fdp.example.org/service/1"
    assert item["kind"] == "data-service"
    assert item["service"]["endpoint_url"] == "https://beacon.example.org/api"
    assert item["service"]["serves_datasets"] == ["https://fdp.example.org/dataset/1"]
    assert item["service"]["conforms_to"] == ["http://en.wikipedia.org/wiki/Beacon_v2"]


async def test_list_data_services_empty_is_not_unsupported() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _ttl(mock, f"{BASE}/", _ROOT)
        _ttl(
            mock,
            f"{BASE}/catalog/1",
            "@prefix dcat: <http://www.w3.org/ns/dcat#> .\n<https://fdp.example.org/catalog/1> a dcat:Catalog .",
        )
        async with FdpClient(_settings()) as client:
            result = await list_data_services.handle(client)
    assert result["items"] == []
    assert result["page"]["total"] == 0
