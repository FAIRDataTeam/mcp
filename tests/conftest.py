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


NEW_DATASET = f"{BASE}/dataset/2"
NEW_DATASET_TTL = f"""
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix fdp: <https://w3id.org/fdp/o#> .
<{NEW_DATASET}> a dcat:Dataset ;
    dcterms:title "Dataset Two" ;
    dcterms:isPartOf <{BASE}/catalog/1> ;
    fdp:metadataState "DRAFT" ;
    fdp:allowedStateTransition "PUBLISHED" .
"""
_STATE_LINK = f'<{NEW_DATASET}/state>; rel="https://w3id.org/fdp/o#hasStateTransition"'


class WriteSurface:
    """A minimal, stateful FDPneo write surface for one new record.

    Tracks an ETag that changes on every successful write so a stale
    ``If-Match`` yields 412 (and a missing one 428), records the last body, and
    honours the state machine DRAFT → PUBLISHED. A body containing the marker
    ``"INVALID"`` fails "SHACL" with a 422 report.
    """

    def __init__(self) -> None:
        self.version = 0
        self.exists = False
        self.state = "DRAFT"
        self.body = NEW_DATASET_TTL
        self.requests: list[httpx.Request] = []

    @property
    def etag(self) -> str:
        return f'"v{self.version}"'

    def _precondition(self, request: httpx.Request) -> httpx.Response | None:
        if_match = request.headers.get("if-match")
        if if_match is None:
            return _json(428, "fdp.precondition_required", "If-Match is required")
        if if_match != self.etag:
            return _json(412, "fdp.precondition_failed", "If-Match does not match current ETag")
        return None

    def post(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("slug") == "taken":
            return _json(409, "fdp.conflict", "Slug already in use")
        if b"INVALID" in request.content:
            return _violation()
        self.exists = True
        self.version += 1
        self.body = request.content.decode()
        return httpx.Response(201, headers={"location": NEW_DATASET, "etag": self.etag})

    def get(self, request: httpx.Request) -> httpx.Response:
        if not self.exists:
            return httpx.Response(404)
        return httpx.Response(
            200,
            text=NEW_DATASET_TTL.replace('"DRAFT"', f'"{self.state}"'),
            headers={"content-type": "text/turtle", "etag": self.etag, "link": _STATE_LINK},
        )

    def put(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if (denied := self._precondition(request)) is not None:
            return denied
        if b"INVALID" in request.content:
            return _violation()
        self.version += 1
        self.body = request.content.decode()
        return httpx.Response(204, headers={"etag": self.etag})

    def patch(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("content-type") != "application/sparql-update":
            return httpx.Response(415, headers={"accept-patch": "application/sparql-update"})
        if (denied := self._precondition(request)) is not None:
            return denied
        self.version += 1
        return httpx.Response(204, headers={"etag": self.etag})

    def delete(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if (denied := self._precondition(request)) is not None:
            return denied
        self.exists = False
        return httpx.Response(204)

    def state_transition(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        to = json.loads(request.content)["to"]
        if (self.state, to) not in {("DRAFT", "PUBLISHED"), ("PUBLISHED", "DRAFT")}:
            return _json(
                409,
                "fdp.invalid_transition",
                f"cannot move {self.state} -> {to}",
                details={"from": self.state, "to": to},
            )
        previous, self.state = self.state, to
        return httpx.Response(
            200,
            json={"record": NEW_DATASET, "from_state": previous, "to_state": to},
        )


def _json(
    status: int, code: str, message: str, *, details: dict[str, object] | None = None
) -> httpx.Response:
    payload: dict[str, object] = {
        "code": code,
        "message": message,
        "docs_url": f"https://specs.fairdatapoint.org/errors#{code}",
    }
    if details is not None:
        payload["details"] = details
    return httpx.Response(status, json=payload)


def _violation() -> httpx.Response:
    return _json(
        422,
        "fdp.schema_violation",
        f"Graph failed SHACL validation against {BASE}/schema/dataset",
        details={
            "shape": f"{BASE}/schema/dataset",
            "violations": [
                {
                    "focus_node": NEW_DATASET,
                    "result_path": "http://purl.org/dc/terms/title",
                    "source_shape": f"{BASE}/schema/dataset",
                    "severity": "Violation",
                    "message": "Less than 1 values",
                    "value": None,
                }
            ],
        },
    )


@pytest.fixture
def write_surface() -> WriteSurface:
    return WriteSurface()


@pytest.fixture
def register_fdpneo_write(write_surface: WriteSurface) -> Callable[[respx.MockRouter], None]:
    """Register the stateful write routes (POST catalog, PUT/PATCH/DELETE/GET new record, state)."""

    def _register(mock: respx.MockRouter) -> None:
        mock.post(f"{BASE}/catalog/1").mock(side_effect=write_surface.post)
        mock.post(f"{BASE}/dataset/1").mock(
            return_value=httpx.Response(405, headers={"allow": "GET"})
        )
        mock.get(NEW_DATASET).mock(side_effect=write_surface.get)
        mock.put(NEW_DATASET).mock(side_effect=write_surface.put)
        mock.patch(NEW_DATASET).mock(side_effect=write_surface.patch)
        mock.delete(NEW_DATASET).mock(side_effect=write_surface.delete)
        # Faithful to the FDPneo bug tracked as gap G-08: the advertised
        # `<record>/state` link does not resolve; the real endpoint is under
        # /fdp-api/. The bridge must fall back.
        mock.post(f"{NEW_DATASET}/state").mock(return_value=httpx.Response(404))
        mock.post(f"{BASE}/fdp-api/dataset/2/state").mock(
            side_effect=write_surface.state_transition
        )

    return _register


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
