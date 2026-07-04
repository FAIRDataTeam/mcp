"""Unit tests for the read tools (task 2.1).

Handlers are exercised over respx fixtures for FDPneo (Turtle + signposting) and
the Java reference implementation (JSON-LD, sparse links). Results are checked
against the tool-surface contract shapes.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import FdpError, FdpNotFoundError, FdpUnsupportedError, InvalidArgumentError
from fdp_mcp.shaping import result_from_error
from fdp_mcp.tools import fdp_info, get_record, get_schema, list_records

BASE = "https://fdp.example.org"

_LDP_LINK = (
    '<http://www.w3.org/ns/ldp#Resource>; rel="type", '
    '<http://www.w3.org/ns/ldp#Container>; rel="type", '
    '<http://www.w3.org/ns/ldp#DirectContainer>; rel="type"'
)
ROOT_LINK = f'{_LDP_LINK}, <https://fdp.example.org>; rel="cite-as"'
DATASET_LINK = (
    '<http://www.w3.org/ns/ldp#Resource>; rel="type", '
    '<http://www.w3.org/ns/ldp#Container>; rel="type", '
    '<https://fdp.example.org/schema/dataset>; rel="http://www.w3.org/ns/ldp#constrainedBy", '
    '<https://doi.org/10.1/ds1>; rel="cite-as"'
)

ROOT_TTL = """
@prefix ldp: <http://www.w3.org/ns/ldp#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix fdp: <https://w3id.org/fdp/o#> .
<https://fdp.example.org> a fdp:FAIRDataPoint, ldp:Container, ldp:DirectContainer ;
    dcterms:title "Example FDP" ;
    ldp:contains <https://fdp.example.org/catalog/1> .
"""
CATALOG_TTL = """
@prefix ldp: <http://www.w3.org/ns/ldp#> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
<https://fdp.example.org/catalog/1> a dcat:Catalog, ldp:Container, ldp:DirectContainer ;
    dcterms:title "Catalog One" ;
    ldp:contains <https://fdp.example.org/dataset/1> .
"""
DATASET_TTL = """
@prefix ldp: <http://www.w3.org/ns/ldp#> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
<https://fdp.example.org/dataset/1> a dcat:Dataset, ldp:Container ;
    dcterms:title "Dataset One" ;
    dcterms:isPartOf <https://fdp.example.org/catalog/1> ;
    ldp:contains <https://fdp.example.org/distribution/1>,
                 <https://fdp.example.org/dataservice/1> .
"""
DISTRIBUTION_TTL = """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
<https://fdp.example.org/distribution/1> a dcat:Distribution .
"""
DATASERVICE_TTL = """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
<https://fdp.example.org/dataservice/1> a dcat:DataService .
"""
SHAPE_TTL = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<https://fdp.example.org/schema/dataset> a sh:NodeShape ;
    sh:targetClass dcat:Dataset ;
    sh:property [ sh:path dcterms:title ; sh:name "title" ;
                  sh:minCount 1 ; sh:datatype xsd:string ] .
"""


def _settings() -> FdpMcpSettings:
    return FdpMcpSettings(_env_file=None, FDP_BASE_URL=BASE)  # type: ignore[call-arg]


def _ttl(mock: respx.MockRouter, url: str, body: str, *, link: str | None = None) -> None:
    headers = {"content-type": "text/turtle"}
    if link is not None:
        headers["link"] = link
    mock.get(url).mock(return_value=httpx.Response(200, text=body, headers=headers))


def _mock_fdp(mock: respx.MockRouter, *, sparql: bool = True, search: bool = True) -> None:
    _ttl(mock, f"{BASE}/", ROOT_TTL, link=ROOT_LINK)
    _ttl(mock, f"{BASE}/catalog/1", CATALOG_TTL, link=_LDP_LINK)
    _ttl(mock, f"{BASE}/dataset/1", DATASET_TTL, link=DATASET_LINK)
    _ttl(mock, f"{BASE}/distribution/1", DISTRIBUTION_TTL)
    _ttl(mock, f"{BASE}/dataservice/1", DATASERVICE_TTL)
    _ttl(mock, f"{BASE}/schema/dataset", SHAPE_TTL)
    sparql_resp = (
        httpx.Response(
            200,
            text=json.dumps({"head": {}, "boolean": True}),
            headers={"content-type": "application/sparql-results+json"},
        )
        if sparql
        else httpx.Response(404)
    )
    mock.post(f"{BASE}/fdp-api/sparql").mock(return_value=sparql_resp)
    search_resp = (
        httpx.Response(
            200,
            text=json.dumps({"items": [], "total": 0}),
            headers={"content-type": "application/json"},
        )
        if search
        else httpx.Response(404)
    )
    mock.post(f"{BASE}/fdp-api/search").mock(return_value=search_resp)


# --- fdp_info ---------------------------------------------------------------


async def test_fdp_info_describes_repository_kinds_and_endpoints() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_fdp(mock)
        async with FdpClient(_settings()) as client:
            result = await fdp_info.handle(client, _settings())

    assert result["repository"]["iri"] == "https://fdp.example.org"
    assert result["repository"]["kind"] == "fair-data-point"
    slugs = {k["slug"] for k in result["kinds"]}
    assert slugs == {"fair-data-point", "catalog", "dataset", "distribution", "data-service"}
    catalog = next(k for k in result["kinds"] if k["slug"] == "catalog")
    assert catalog["top_level"] is True
    assert result["endpoints"] == {"sparql": True, "search": True}


async def test_fdp_info_reports_absent_endpoints() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_fdp(mock, sparql=False, search=False)
        async with FdpClient(_settings()) as client:
            result = await fdp_info.handle(client, _settings())
    assert result["endpoints"] == {"sparql": False, "search": False}


# --- get_record -------------------------------------------------------------


async def test_get_record_full_with_signposting() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_fdp(mock)
        async with FdpClient(_settings()) as client:
            result = await get_record.handle(client, iri=f"{BASE}/dataset/1")

    assert result["iri"] == "https://fdp.example.org/dataset/1"
    # types lists every rdf:type faithfully; `kind` is the clean domain slug.
    assert result["types"] == [
        "http://www.w3.org/ns/dcat#Dataset",
        "http://www.w3.org/ns/ldp#Container",
    ]
    assert result["kind"] == "dataset"
    assert result["links"]["parent"] == "https://fdp.example.org/catalog/1"
    assert result["links"]["constrained_by"] == "https://fdp.example.org/schema/dataset"
    assert result["links"]["cite_as"] == "https://doi.org/10.1/ds1"
    assert result["metadata"]["@id"] == "https://fdp.example.org/dataset/1"


async def test_get_record_raw_format() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_fdp(mock)
        async with FdpClient(_settings()) as client:
            result = await get_record.handle(client, iri=f"{BASE}/dataset/1", fmt="turtle")
    assert result["metadata_media_type"] == "text/turtle"
    assert isinstance(result["metadata"], str)


async def test_get_record_java_jsonld_sparse_links() -> None:
    body = (
        '{"@id": "https://fdp.example.org/dataset/9",'
        ' "@type": ["http://www.w3.org/ns/dcat#Dataset"],'
        ' "http://purl.org/dc/terms/title": "Java DS"}'
    )
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/dataset/9").mock(
            return_value=httpx.Response(
                200,
                text=body,
                headers={
                    "content-type": "application/ld+json",
                    "link": '<http://www.w3.org/ns/ldp#Resource>; rel="type"',
                },
            )
        )
        async with FdpClient(_settings()) as client:
            result = await get_record.handle(client, iri=f"{BASE}/dataset/9")
    assert result["iri"] == "https://fdp.example.org/dataset/9"
    assert result["title"] == "Java DS"
    assert "cite_as" not in result["links"]  # no signposting on the Java RI


async def test_get_record_unknown_iri_yields_not_found_envelope() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/missing").mock(return_value=httpx.Response(404))
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpNotFoundError) as exc_info:
                await get_record.handle(client, iri=f"{BASE}/missing")
    # The registry maps that error to the contract NotFound envelope:
    envelope = result_from_error("get_record", exc_info.value)
    assert envelope == {"error": {"code": "not_found", "message": f"{BASE}/missing"}}


async def test_get_record_rejects_off_origin_iri() -> None:
    async with FdpClient(_settings()) as client:
        # An off-origin IRI is caught by the egress guard and maps to
        # invalid_argument in the contract envelope.
        with pytest.raises(FdpError) as exc_info:
            await get_record.handle(client, iri="https://evil.example.org/x")
    assert result_from_error("get_record", exc_info.value)["error"]["code"] == "invalid_argument"


# --- list_records -----------------------------------------------------------


async def test_list_records_enumerates_parent_members() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_fdp(mock)
        async with FdpClient(_settings()) as client:
            result = await list_records.handle(client, parent=f"{BASE}/catalog/1")
    assert result["page"]["total"] == 1
    assert [item["iri"] for item in result["items"]] == ["https://fdp.example.org/dataset/1"]
    assert result["items"][0]["kind"] == "dataset"


async def test_list_records_kind_filter() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_fdp(mock)
        async with FdpClient(_settings()) as client:
            match = await list_records.handle(client, kind="dataset", parent=f"{BASE}/catalog/1")
            miss = await list_records.handle(client, kind="catalog", parent=f"{BASE}/catalog/1")
    assert [item["iri"] for item in match["items"]] == ["https://fdp.example.org/dataset/1"]
    assert miss["items"] == []


# --- get_schema -------------------------------------------------------------


async def test_get_schema_returns_shape_digest() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_fdp(mock)
        async with FdpClient(_settings()) as client:
            result = await get_schema.handle(client, kind="dataset")
    assert result["kind"] == "dataset"
    assert result["shape_iri"] == "https://fdp.example.org/schema/dataset"
    assert result["targets"] == ["http://www.w3.org/ns/dcat#Dataset"]
    title = next(p for p in result["properties"] if p["path"] == "http://purl.org/dc/terms/title")
    assert title["min_count"] == 1
    assert result["shape"]["@id"] == "https://fdp.example.org/schema/dataset"


async def test_get_schema_unknown_kind_is_invalid_argument() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_fdp(mock)
        async with FdpClient(_settings()) as client:
            with pytest.raises(InvalidArgumentError):
                await get_schema.handle(client, kind="nonesuch")


async def test_get_schema_without_shape_degrades_to_unsupported() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_fdp(mock)
        async with FdpClient(_settings()) as client:
            # distribution/1 carries no constrainedBy link → unsupported(shapes).
            with pytest.raises(FdpUnsupportedError) as exc_info:
                await get_schema.handle(client, kind="distribution")
    assert exc_info.value.capability == "shapes"
