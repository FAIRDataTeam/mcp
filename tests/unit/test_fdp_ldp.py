"""Unit tests for LDP fetch, paging, and root discovery (task 1.2).

Fixtures model both FDPneo (Turtle, full FAIR-Signposting Link header) and the
Java reference implementation (JSON-LD, sparse links) response shapes.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import FdpNotFoundError, FdpUnauthorizedError
from fdp_mcp.fdp.ldp import discover_root, fetch_resource, iter_container_members

BASE = "https://fdp.example.org"

# --- FDPneo (Turtle) fixtures ----------------------------------------------

_LDP_LINK = (
    '<http://www.w3.org/ns/ldp#Resource>; rel="type", '
    '<http://www.w3.org/ns/ldp#RDFSource>; rel="type", '
    '<http://www.w3.org/ns/ldp#Container>; rel="type", '
    '<http://www.w3.org/ns/ldp#DirectContainer>; rel="type"'
)

ROOT_TTL = """
@prefix ldp: <http://www.w3.org/ns/ldp#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix fdp: <https://w3id.org/fdp/o#> .
<https://fdp.example.org> a fdp:FAIRDataPoint, ldp:Container, ldp:DirectContainer ;
    dcterms:title "Example FDP" ;
    ldp:contains <https://fdp.example.org/catalog/1> .
"""
ROOT_LINK = (
    f"{_LDP_LINK}, "
    '<https://w3id.org/fdp/o#FAIRDataPoint>; rel="type", '
    '<https://fdp.example.org/schema/repository>; rel="http://www.w3.org/ns/ldp#constrainedBy", '
    '<https://fdp.example.org>; rel="cite-as"'
)

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


def _settings() -> FdpMcpSettings:
    return FdpMcpSettings(_env_file=None, FDP_BASE_URL=BASE)  # type: ignore[call-arg]


def _ttl(mock: respx.MockRouter, url: str, body: str, *, link: str | None = None) -> None:
    headers = {"content-type": "text/turtle"}
    if link is not None:
        headers["link"] = link
    mock.get(url).mock(return_value=httpx.Response(200, text=body, headers=headers))


def _mock_fdpneo(mock: respx.MockRouter) -> None:
    _ttl(mock, f"{BASE}/", ROOT_TTL, link=ROOT_LINK)
    _ttl(mock, f"{BASE}/catalog/1", CATALOG_TTL, link=_LDP_LINK)
    _ttl(mock, f"{BASE}/dataset/1", DATASET_TTL, link=_LDP_LINK)
    _ttl(mock, f"{BASE}/distribution/1", DISTRIBUTION_TTL)
    _ttl(mock, f"{BASE}/dataservice/1", DATASERVICE_TTL)


# --- fetch_resource ---------------------------------------------------------


async def test_fetch_root_parses_graph_links_and_containment() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_fdpneo(mock)
        async with FdpClient(_settings()) as client:
            root = await fetch_resource(client, client.base_url)

    assert root.iri == "https://fdp.example.org"
    assert "https://w3id.org/fdp/o#FAIRDataPoint" in root.type_iris
    assert root.is_container is True
    assert root.title == "Example FDP"
    assert root.constrained_by == "https://fdp.example.org/schema/repository"
    assert root.links.cite_as == "https://fdp.example.org"
    assert root.member_iris == ["https://fdp.example.org/catalog/1"]


async def test_child_parent_link_resolved() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_fdpneo(mock)
        async with FdpClient(_settings()) as client:
            dataset = await fetch_resource(client, f"{BASE}/dataset/1")
    assert dataset.parent_iri == "https://fdp.example.org/catalog/1"
    assert dataset.kind_type_iris == ["http://www.w3.org/ns/dcat#Dataset"]


async def test_content_negotiation_default_prefers_turtle() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE}/dataset/1").mock(
            return_value=httpx.Response(
                200, text=DATASET_TTL, headers={"content-type": "text/turtle"}
            )
        )
        async with FdpClient(_settings()) as client:
            await fetch_resource(client, f"{BASE}/dataset/1")
    assert route.calls.last.request.headers["accept"].startswith("text/turtle")


async def test_not_found_and_unauthorized_map_to_errors() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/missing").mock(return_value=httpx.Response(404))
        mock.get(f"{BASE}/secret").mock(return_value=httpx.Response(403))
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpNotFoundError):
                await fetch_resource(client, f"{BASE}/missing")
            with pytest.raises(FdpUnauthorizedError):
                await fetch_resource(client, f"{BASE}/secret")


# --- Java reference implementation (JSON-LD, sparse links) ------------------

JAVA_DATASET_JSONLD = (
    '{"@id": "https://fdp.example.org/dataset/1",'
    ' "@type": ["http://www.w3.org/ns/dcat#Dataset"],'
    ' "http://purl.org/dc/terms/title": "Java Dataset"}'
)


async def test_java_jsonld_record_parses_with_sparse_links() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/dataset/1").mock(
            return_value=httpx.Response(
                200,
                text=JAVA_DATASET_JSONLD,
                headers={
                    "content-type": "application/ld+json",
                    # Java RI emits no FAIR-Signposting relations (gap G-04).
                    "link": '<http://www.w3.org/ns/ldp#Resource>; rel="type"',
                },
            )
        )
        async with FdpClient(_settings()) as client:
            dataset = await fetch_resource(client, f"{BASE}/dataset/1")

    assert dataset.media_type == "application/ld+json"
    assert dataset.iri == "https://fdp.example.org/dataset/1"
    assert dataset.kind_type_iris == ["http://www.w3.org/ns/dcat#Dataset"]
    assert dataset.title == "Java Dataset"
    # Divergence recorded in fdp-api-gaps.md G-04: no signposting to lean on.
    assert dataset.links.cite_as is None
    assert dataset.constrained_by is None


# --- container paging -------------------------------------------------------


async def test_paging_follows_x_fdp_page_offset() -> None:
    page = f"{BASE}/fdp-api/page/dataset"
    page1 = """
    @prefix ldp: <http://www.w3.org/ns/ldp#> .
    <https://fdp.example.org/fdp-api/page/dataset> a ldp:Container ;
        ldp:contains <https://fdp.example.org/dataset/1>, <https://fdp.example.org/dataset/2> .
    """
    page2 = """
    @prefix ldp: <http://www.w3.org/ns/ldp#> .
    <https://fdp.example.org/fdp-api/page/dataset> a ldp:Container ;
        ldp:contains <https://fdp.example.org/dataset/3> .
    """
    with respx.mock(assert_all_called=False) as mock:
        # Register the specific offset=2 route first; the query-less base route
        # is the fallback (respx returns the first matching route in order).
        mock.get(page, params={"offset": "2"}).mock(
            return_value=httpx.Response(
                200,
                text=page2,
                headers={
                    "content-type": "text/turtle",
                    "x-fdp-page-offset": "2",
                    "x-fdp-page-limit": "2",
                    "x-fdp-page-total": "3",
                },
            )
        )
        mock.get(page).mock(
            return_value=httpx.Response(
                200,
                text=page1,
                headers={
                    "content-type": "text/turtle",
                    "x-fdp-page-offset": "0",
                    "x-fdp-page-limit": "2",
                    "x-fdp-page-total": "3",
                },
            )
        )
        async with FdpClient(_settings()) as client:
            members = [m async for m in iter_container_members(client, page)]

    assert members == [
        "https://fdp.example.org/dataset/1",
        "https://fdp.example.org/dataset/2",
        "https://fdp.example.org/dataset/3",
    ]


async def test_paging_respects_max_members() -> None:
    page = f"{BASE}/fdp-api/page/dataset"
    page1 = """
    @prefix ldp: <http://www.w3.org/ns/ldp#> .
    <https://fdp.example.org/fdp-api/page/dataset> a ldp:Container ;
        ldp:contains <https://fdp.example.org/dataset/1>, <https://fdp.example.org/dataset/2> .
    """
    with respx.mock(assert_all_called=False) as mock:
        mock.get(page).mock(
            return_value=httpx.Response(
                200,
                text=page1,
                headers={
                    "content-type": "text/turtle",
                    "x-fdp-page-offset": "0",
                    "x-fdp-page-limit": "2",
                    "x-fdp-page-total": "10",
                },
            )
        )
        async with FdpClient(_settings()) as client:
            members = [m async for m in iter_container_members(client, page, max_members=1)]
    assert members == ["https://fdp.example.org/dataset/1"]


async def test_paging_inline_container_single_page() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_fdpneo(mock)
        async with FdpClient(_settings()) as client:
            members = [m async for m in iter_container_members(client, f"{BASE}/catalog/1")]
    assert members == ["https://fdp.example.org/dataset/1"]


# --- root discovery ---------------------------------------------------------


async def test_discover_root_enumerates_kinds_without_hardcoding() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_fdpneo(mock)
        async with FdpClient(_settings()) as client:
            discovery = await discover_root(client)

    assert discovery.truncated is False
    assert discovery.root.iri == "https://fdp.example.org"
    slugs = {kind.slug for kind in discovery.kinds}
    assert slugs == {"fair-data-point", "catalog", "dataset", "distribution", "data-service"}
    root_kind = next(k for k in discovery.kinds if k.is_root)
    assert root_kind.type_iris == ("https://w3id.org/fdp/o#FAIRDataPoint",)


async def test_discover_root_truncates_at_fetch_cap() -> None:
    with respx.mock(assert_all_called=False) as mock:
        _mock_fdpneo(mock)
        async with FdpClient(_settings()) as client:
            discovery = await discover_root(client, max_fetches=2)
    assert discovery.truncated is True
