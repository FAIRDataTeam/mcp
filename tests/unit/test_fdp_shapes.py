"""Unit tests for SHACL shape resolution + digest (task 1.3)."""

from __future__ import annotations

import httpx
import pytest
import respx

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import FdpUnsupportedError
from fdp_mcp.fdp.shapes import fetch_shape, fetch_shape_for_record

BASE = "https://fdp.example.org"
SHAPE = f"{BASE}/schema/dataset"

SHAPE_TTL = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<https://fdp.example.org/schema/dataset> a sh:NodeShape ;
    sh:targetClass dcat:Dataset ;
    sh:property [ sh:path dcterms:title ; sh:name "title" ;
                  sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:string ;
                  sh:description "Human-readable title." ] ;
    sh:property [ sh:path dcterms:publisher ; sh:nodeKind sh:IRI ] .
"""

RECORD_TTL = """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
<https://fdp.example.org/dataset/1> a dcat:Dataset .
"""
RECORD_LINK = (
    '<https://fdp.example.org/schema/dataset>; rel="http://www.w3.org/ns/ldp#constrainedBy"'
)


def _settings() -> FdpMcpSettings:
    return FdpMcpSettings(_env_file=None, FDP_BASE_URL=BASE)  # type: ignore[call-arg]


async def test_fetch_shape_digests_properties() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(SHAPE).mock(
            return_value=httpx.Response(
                200, text=SHAPE_TTL, headers={"content-type": "text/turtle"}
            )
        )
        async with FdpClient(_settings()) as client:
            shape = await fetch_shape(client, SHAPE)

    assert shape.target_class_iris == ["http://www.w3.org/ns/dcat#Dataset"]
    by_path = {p.path: p for p in shape.properties}
    title = by_path["http://purl.org/dc/terms/title"]
    assert title.name == "title"
    assert title.min_count == 1
    assert title.max_count == 1
    assert title.datatype == "http://www.w3.org/2001/XMLSchema#string"
    assert title.description == "Human-readable title."
    publisher = by_path["http://purl.org/dc/terms/publisher"]
    assert publisher.name == "publisher"  # derived from the path's local name
    assert publisher.node_kind == "http://www.w3.org/ns/shacl#IRI"


async def test_fetch_shape_for_record_follows_constrained_by() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/dataset/1").mock(
            return_value=httpx.Response(
                200, text=RECORD_TTL, headers={"content-type": "text/turtle", "link": RECORD_LINK}
            )
        )
        mock.get(SHAPE).mock(
            return_value=httpx.Response(
                200, text=SHAPE_TTL, headers={"content-type": "text/turtle"}
            )
        )
        async with FdpClient(_settings()) as client:
            shape = await fetch_shape_for_record(client, f"{BASE}/dataset/1")
    assert shape.shape_iri == SHAPE
    assert shape.target_class_iris == ["http://www.w3.org/ns/dcat#Dataset"]


async def test_record_without_constrained_by_degrades_to_unsupported() -> None:
    with respx.mock(assert_all_called=False) as mock:
        # Java-reference-style record: no constrainedBy link, no graph triple.
        mock.get(f"{BASE}/dataset/1").mock(
            return_value=httpx.Response(
                200, text=RECORD_TTL, headers={"content-type": "text/turtle"}
            )
        )
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpUnsupportedError) as exc_info:
                await fetch_shape_for_record(client, f"{BASE}/dataset/1")
    assert exc_info.value.capability == "shapes"


async def test_missing_shape_document_degrades_to_unsupported() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(SHAPE).mock(return_value=httpx.Response(404))
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpUnsupportedError) as exc_info:
                await fetch_shape(client, SHAPE)
    assert exc_info.value.capability == "shapes"
