"""Shared fixtures: a respx-mocked FDPneo instance for conformance + integration.

Provides a realistic, self-consistent FDPneo surface (root → catalog → dataset →
distribution, plus a data service, a SHACL shape, an ODRL policy, SPARQL and
search endpoints) so every v1 tool can be exercised end-to-end without a live
container.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
import respx

from fdp_mcp.config import FdpMcpSettings

BASE = "https://fdp.example.org"

# Faithful to real FDPneo: containers are typed ldp:DirectContainer only (no bare
# ldp:Container), in both the Link header and the graph. This exercises the
# container-type recognition that a DataService BFS depends on.
_LDP_CONTAINER_LINK = (
    '<http://www.w3.org/ns/ldp#Resource>; rel="type", '
    '<http://www.w3.org/ns/ldp#DirectContainer>; rel="type"'
)
_ROOT_LINK = f'{_LDP_CONTAINER_LINK}, <{BASE}>; rel="cite-as"'
_DATASET_LINK = (
    '<http://www.w3.org/ns/ldp#Resource>; rel="type", '
    '<http://www.w3.org/ns/ldp#DirectContainer>; rel="type", '
    f'<{BASE}/schema/dataset>; rel="http://www.w3.org/ns/ldp#constrainedBy", '
    '<https://doi.org/10.1/ds1>; rel="cite-as", '
    '<https://creativecommons.org/licenses/by/4.0/>; rel="license"'
)

_ROOT_TTL = f"""
@prefix ldp: <http://www.w3.org/ns/ldp#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix fdp: <https://w3id.org/fdp/o#> .
<{BASE}> a fdp:FAIRDataPoint, ldp:DirectContainer ;
    dcterms:title "Example FDP" ;
    dcterms:publisher <https://example.org/org/1> ;
    ldp:contains <{BASE}/catalog/1> .
"""
_CATALOG_TTL = f"""
@prefix ldp: <http://www.w3.org/ns/ldp#> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
<{BASE}/catalog/1> a dcat:Catalog, ldp:DirectContainer ;
    dcterms:title "Catalog One" ;
    ldp:contains <{BASE}/dataset/1>, <{BASE}/service/1> .
"""
_DATASET_TTL = f"""
@prefix ldp: <http://www.w3.org/ns/ldp#> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix vcard: <http://www.w3.org/2006/vcard/ns#> .
<{BASE}/dataset/1> a dcat:Dataset, ldp:DirectContainer ;
    dcterms:title "Dataset One" ;
    dcterms:isPartOf <{BASE}/catalog/1> ;
    dcterms:license <https://creativecommons.org/licenses/by/4.0/> ;
    dcterms:rights <{BASE}/policies/1> ;
    dcat:contactPoint [ a vcard:Kind ; vcard:fn "Data Access Committee" ;
                        vcard:hasEmail <mailto:dac@example.org> ] ;
    ldp:contains <{BASE}/distribution/1> .
"""
_DISTRIBUTION_TTL = f"""
@prefix dcat: <http://www.w3.org/ns/dcat#> .
<{BASE}/distribution/1> a dcat:Distribution .
"""
_SERVICE_TTL = f"""
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
<{BASE}/service/1> a dcat:DataService ;
    dcterms:title "Beacon endpoint" ;
    dcat:endpointURL <https://beacon.example.org/api> ;
    dcat:endpointDescription <https://beacon.example.org/api/openapi.json> ;
    dcat:servesDataset <{BASE}/dataset/1> ;
    dcterms:conformsTo <http://en.wikipedia.org/wiki/Beacon_v2> .
"""
_SHAPE_TTL = f"""
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<{BASE}/schema/dataset> a sh:NodeShape ;
    sh:targetClass dcat:Dataset ;
    sh:property [ sh:path dcterms:title ; sh:name "title" ;
                  sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:string ] .
"""
_POLICY_TTL = f"""
@prefix odrl: <http://www.w3.org/ns/odrl/2/> .
@prefix dcterms: <http://purl.org/dc/terms/> .
<{BASE}/policies/1> a odrl:Offer ; dcterms:title "Academic use" .
"""


def _ttl(mock: respx.MockRouter, url: str, body: str, *, link: str | None = None) -> None:
    headers = {"content-type": "text/turtle"}
    if link is not None:
        headers["link"] = link
    mock.get(url).mock(return_value=httpx.Response(200, text=body, headers=headers))


@pytest.fixture
def base_url() -> str:
    return BASE


@pytest.fixture
def fdp_settings() -> FdpMcpSettings:
    return FdpMcpSettings(_env_file=None, FDP_BASE_URL=BASE)  # type: ignore[call-arg]


@pytest.fixture
def register_fdpneo() -> Callable[..., None]:
    """Return a function that registers the FDPneo surface on a respx router."""

    def _register(mock: respx.MockRouter, *, sparql: bool = True, search: bool = True) -> None:
        _ttl(mock, f"{BASE}/", _ROOT_TTL, link=_ROOT_LINK)
        _ttl(mock, f"{BASE}/catalog/1", _CATALOG_TTL, link=_LDP_CONTAINER_LINK)
        _ttl(mock, f"{BASE}/dataset/1", _DATASET_TTL, link=_DATASET_LINK)
        _ttl(mock, f"{BASE}/distribution/1", _DISTRIBUTION_TTL)
        _ttl(mock, f"{BASE}/service/1", _SERVICE_TTL)
        _ttl(mock, f"{BASE}/schema/dataset", _SHAPE_TTL)
        _ttl(mock, f"{BASE}/policies/1", _POLICY_TTL)
        mock.post(f"{BASE}/fdp-api/sparql").mock(
            return_value=(
                httpx.Response(
                    200,
                    text=json.dumps(
                        {"head": {"vars": ["s"]}, "results": {"bindings": []}, "boolean": True}
                    ),
                    headers={"content-type": "application/sparql-results+json"},
                )
                if sparql
                else httpx.Response(404)
            )
        )
        mock.post(f"{BASE}/fdp-api/search").mock(
            return_value=(
                httpx.Response(
                    200,
                    text=json.dumps(
                        {
                            "items": [
                                {
                                    "recordIri": f"{BASE}/dataset/1",
                                    "typeIri": "http://www.w3.org/ns/dcat#Dataset",
                                    "title": "Dataset One",
                                    "description": None,
                                    "license": None,
                                    "state": "PUBLISHED",
                                    "updatedAt": None,
                                }
                            ],
                            "total": 1,
                        }
                    ),
                    headers={"content-type": "application/json"},
                )
                if search
                else httpx.Response(404)
            )
        )

    return _register
