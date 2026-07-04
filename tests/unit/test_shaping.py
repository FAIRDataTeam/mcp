"""Unit tests for result shaping: framing, Record object, envelopes (task 2.1)."""

from __future__ import annotations

from rdflib import Graph

from fdp_mcp.fdp.errors import FdpNotFoundError, FdpUnsupportedError, ReadOnlyError
from fdp_mcp.fdp.ldp import LdpResource
from fdp_mcp.fdp.links import LinkSet
from fdp_mcp.shaping import (
    error_result,
    frame_record,
    page_envelope,
    record_object,
    result_from_error,
    unsupported_result,
)

DATASET_TTL = """
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix vcard: <http://www.w3.org/2006/vcard/ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<https://fdp.example.org/d/1> a dcat:Dataset ;
    dcterms:title "Title"@en ;
    dcterms:issued "2026-01-01"^^xsd:date ;
    dcterms:publisher <https://example.org/org/1> ;
    dcat:contactPoint [ a vcard:Kind ; vcard:fn "DAC" ] .
"""


def _graph(ttl: str) -> Graph:
    graph = Graph()
    graph.parse(data=ttl, format="turtle")
    return graph


def _resource(*, link: str | None = None, media: str = "text/turtle") -> LdpResource:
    return LdpResource(
        iri="https://fdp.example.org/d/1",
        requested_iri="https://fdp.example.org/d/1",
        media_type=media,
        text=DATASET_TTL,
        graph=_graph(DATASET_TTL),
        links=LinkSet.from_header(link),
        status=200,
        page=None,
    )


# --- framing ---------------------------------------------------------------


def test_frame_record_compacts_types_and_predicates() -> None:
    framed = frame_record(_graph(DATASET_TTL), "https://fdp.example.org/d/1")
    assert framed["@id"] == "https://fdp.example.org/d/1"
    assert framed["@type"] == ["dcat:Dataset"]
    assert framed["@context"]["dcat"] == "http://www.w3.org/ns/dcat#"


def test_frame_record_literal_value_objects() -> None:
    framed = frame_record(_graph(DATASET_TTL), "https://fdp.example.org/d/1")
    assert framed["dcterms:title"] == {"@value": "Title", "@language": "en"}
    assert framed["dcterms:issued"] == {"@value": "2026-01-01", "@type": "xsd:date"}


def test_frame_record_object_iris_stay_absolute() -> None:
    framed = frame_record(_graph(DATASET_TTL), "https://fdp.example.org/d/1")
    assert framed["dcterms:publisher"] == {"@id": "https://example.org/org/1"}


def test_frame_record_embeds_blank_nodes() -> None:
    framed = frame_record(_graph(DATASET_TTL), "https://fdp.example.org/d/1")
    contact = framed["dcat:contactPoint"]
    assert contact["@type"] == ["vcard:Kind"]
    assert contact["vcard:fn"] == "DAC"
    assert "@id" not in contact  # embedded inline, not referenced


# --- Record object ---------------------------------------------------------


def test_record_object_full_shape() -> None:
    link = (
        '<https://fdp.example.org/schema/dataset>; rel="http://www.w3.org/ns/ldp#constrainedBy", '
        '<https://doi.org/10.1/x>; rel="cite-as"'
    )
    obj = record_object(_resource(link=link), kind="dataset")
    assert obj["iri"] == "https://fdp.example.org/d/1"
    assert obj["types"] == ["http://www.w3.org/ns/dcat#Dataset"]
    assert obj["title"] == "Title"
    assert obj["kind"] == "dataset"
    assert obj["metadata"]["@id"] == "https://fdp.example.org/d/1"
    assert obj["links"]["constrained_by"] == "https://fdp.example.org/schema/dataset"
    assert obj["links"]["cite_as"] == "https://doi.org/10.1/x"


def test_record_object_summary_metadata_is_compact() -> None:
    obj = record_object(_resource(), summary=True)
    assert obj["metadata"] == {
        "@id": "https://fdp.example.org/d/1",
        "@type": ["dcat:Dataset"],
        "dcterms:title": "Title",
    }


def test_record_object_raw_format_returns_text() -> None:
    obj = record_object(_resource(), fmt="turtle")
    assert obj["metadata"] == DATASET_TTL
    assert obj["metadata_media_type"] == "text/turtle"


def test_record_object_always_has_iri_for_citation() -> None:
    for fmt in ("jsonld", "turtle", "ntriples", "rdfxml"):
        assert record_object(_resource(), fmt=fmt)["iri"] == "https://fdp.example.org/d/1"


# --- envelopes -------------------------------------------------------------


def test_page_envelope_with_known_total() -> None:
    env = page_envelope([{"iri": "a"}], limit=1, offset=0, total=3)
    assert env["page"] == {
        "limit": 1,
        "offset": 0,
        "count": 1,
        "has_more": True,
        "total": 3,
        "next_offset": 1,
    }


def test_page_envelope_last_page_has_no_next() -> None:
    env = page_envelope([{"iri": "c"}], limit=2, offset=2, total=3)
    assert env["page"]["has_more"] is False
    assert "next_offset" not in env["page"]


def test_page_envelope_unknown_total_uses_full_page_heuristic() -> None:
    assert page_envelope([{}, {}], limit=2, offset=0, total=None)["page"]["has_more"] is True
    assert page_envelope([{}], limit=2, offset=0, total=None)["page"]["has_more"] is False


def test_error_and_unsupported_envelopes() -> None:
    assert error_result("not_found", "gone", {"iri": "x"}) == {
        "error": {"code": "not_found", "message": "gone", "details": {"iri": "x"}}
    }
    exc = FdpUnsupportedError("search-api", "no search here", alternative="use sparql_query")
    assert unsupported_result("search", exc) == {
        "unsupported": {
            "tool": "search",
            "reason": "no search here",
            "capability": "search-api",
            "alternative": "use sparql_query",
        }
    }


def test_result_from_error_maps_codes() -> None:
    assert result_from_error("get_record", FdpNotFoundError("x"))["error"]["code"] == "not_found"
    assert (
        result_from_error("sparql_query", ReadOnlyError("no"))["error"]["code"]
        == "read_only_violation"
    )
    unsupported = result_from_error("get_schema", FdpUnsupportedError("shapes", "none"))
    assert unsupported["unsupported"]["capability"] == "shapes"
