"""Unit tests for the write client layer (task 5.2): validators, verbs, errors."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
import respx

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import (
    EgressError,
    FdpConflictError,
    FdpPreconditionError,
    FdpUnsupportedError,
    FdpUnsupportedMediaTypeError,
    FdpUpstreamError,
    FdpValidationError,
    InvalidArgumentError,
    InvalidQueryError,
    raise_for_status,
)
from fdp_mcp.fdp.sparql import classify_update
from fdp_mcp.fdp.write import (
    create_member,
    delete_resource,
    patch_resource,
    replace_resource,
    transition_state,
    validate_rdf_body,
)
from tests.conftest import NEW_DATASET, NEW_DATASET_TTL, WriteSurface

BASE = "https://fdp.example.org"
ORIGIN = "https://fdp.example.org"


def _settings() -> FdpMcpSettings:
    return FdpMcpSettings(_env_file=None, FDP_BASE_URL=BASE)  # type: ignore[call-arg]


# --- raise_for_status: write statuses -----------------------------------------


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (409, FdpConflictError),
        (412, FdpPreconditionError),
        (428, FdpPreconditionError),
        (415, FdpUnsupportedMediaTypeError),
        (422, FdpValidationError),
    ],
)
def test_raise_for_status_maps_write_statuses(status: int, error: type[Exception]) -> None:
    with pytest.raises(error):
        raise_for_status(status, iri="x")


def test_raise_for_status_passes_fdp_details_through() -> None:
    body = '{"code":"fdp.schema_violation","message":"bad","details":{"violations":[1]}}'
    with pytest.raises(FdpValidationError) as info:
        raise_for_status(422, iri="x", body=body, media_type="application/json")
    assert info.value.details == {"violations": [1]}
    assert "bad" in str(info.value)


def test_raise_for_status_tolerates_non_json_error_bodies() -> None:
    with pytest.raises(FdpConflictError) as info:
        raise_for_status(409, iri="x", body="<html>", media_type="text/html")
    assert info.value.details is None


# --- validate_rdf_body ------------------------------------------------------------


def test_validate_rdf_body_accepts_relative_self_subject() -> None:
    body = "@prefix dcat: <http://www.w3.org/ns/dcat#> . <> a dcat:Dataset ."
    graph = validate_rdf_body(body, "text/turtle", base_iri=f"{BASE}/catalog/1", max_bytes=10_000)
    assert len(graph) == 1


def test_validate_rdf_body_accepts_one_typed_subject_with_ancillary_nodes() -> None:
    body = """
    @prefix dcat: <http://www.w3.org/ns/dcat#> .
    @prefix dcterms: <http://purl.org/dc/terms/> .
    @prefix foaf: <http://xmlns.com/foaf/0.1/> .
    <https://fdp.example.org/dataset/9> a dcat:Dataset ; dcterms:publisher <https://org.example/1> .
    <https://org.example/1> foaf:name "Org" .
    """
    validate_rdf_body(body, "text/turtle", base_iri=NEW_DATASET, max_bytes=10_000)


@pytest.mark.parametrize(
    ("body", "media_type", "fragment"),
    [
        ("this is not turtle", "text/turtle", "not valid"),
        ("", "text/turtle", "no triples"),
        ("[] a <http://x/T> .", "text/turtle", "blank nodes only"),
        ("<http://a/1> a <http://x/T> . <http://a/2> a <http://x/T> .", "text/turtle", "primary"),
        ("<> a <http://x/T> .", "text/csv", "unsupported media_type"),
    ],
)
def test_validate_rdf_body_rejects(body: str, media_type: str, fragment: str) -> None:
    with pytest.raises(InvalidArgumentError, match=fragment):
        validate_rdf_body(body, media_type, base_iri=NEW_DATASET, max_bytes=10_000)


def test_validate_rdf_body_enforces_size_cap() -> None:
    with pytest.raises(InvalidArgumentError, match="cap"):
        validate_rdf_body("<> a <http://x/T> .", "text/turtle", base_iri=NEW_DATASET, max_bytes=5)


# --- classify_update ---------------------------------------------------------------


@pytest.mark.parametrize(
    "update",
    [
        "INSERT DATA { <https://fdp.example.org/dataset/2> <http://purl.org/dc/terms/title> 'x' }",
        "DELETE DATA { <https://fdp.example.org/dataset/2> <http://purl.org/dc/terms/title> 'x' }",
        "DELETE WHERE { <https://fdp.example.org/dataset/2> <http://purl.org/dc/terms/title> ?o }",
        "DELETE { ?s <http://purl.org/dc/terms/title> ?o } INSERT { ?s <http://purl.org/dc/terms/title> 'y' } "
        "WHERE { ?s <http://purl.org/dc/terms/title> ?o }",
        "INSERT DATA { GRAPH <https://fdp.example.org/dataset/2> { <a:b> <a:c> 'd' } }",
        "INSERT DATA { <a:b> <a:c> 'd' }; DELETE DATA { <a:b> <a:c> 'e' }",
    ],
)
def test_classify_update_allows_record_edits(update: str) -> None:
    assert classify_update(update, origin=ORIGIN)


@pytest.mark.parametrize(
    ("update", "fragment"),
    [
        ("LOAD <http://evil.example/> INTO GRAPH <https://fdp.example.org/g>", "LOAD"),
        ("CLEAR ALL", "CLEAR"),
        ("DROP GRAPH <https://fdp.example.org/g>", "DROP"),
        ("CREATE GRAPH <https://fdp.example.org/g>", "CREATE"),
        ("ADD <https://fdp.example.org/a> TO <https://fdp.example.org/b>", "ADD"),
        ("COPY DEFAULT TO <https://fdp.example.org/b>", "COPY"),
        ("MOVE DEFAULT TO <https://fdp.example.org/b>", "MOVE"),
        (
            "INSERT { ?s ?p ?o } WHERE { SERVICE <http://evil.example/sparql> { ?s ?p ?o } }",
            "SERVICE",
        ),
        (
            "INSERT DATA { GRAPH <http://evil.example/g> { <a:b> <a:c> 'd' } }",
            "outside the FDP origin",
        ),
        (
            "WITH <http://evil.example/g> DELETE { ?s ?p ?o } WHERE { ?s ?p ?o }",
            "outside the FDP origin",
        ),
        ("SELECT * WHERE { ?s ?p ?o }", "not a valid SPARQL update"),
        ("this is not sparql", "not a valid SPARQL update"),
    ],
)
def test_classify_update_rejects(update: str, fragment: str) -> None:
    with pytest.raises(InvalidQueryError, match=fragment):
        classify_update(update, origin=ORIGIN)


# --- verbs over the stateful surface ----------------------------------------------


async def test_create_member_returns_location_and_etag(
    register_fdpneo_write: Callable[[respx.MockRouter], None], write_surface: WriteSurface
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo_write(mock)
        async with FdpClient(_settings()) as client:
            outcome = await create_member(
                client,
                f"{BASE}/catalog/1",
                body=NEW_DATASET_TTL,
                media_type="text/turtle",
                slug="two",
            )
    assert outcome.iri == NEW_DATASET
    assert outcome.etag == write_surface.etag
    assert write_surface.requests[-1].headers["slug"] == "two"
    assert write_surface.requests[-1].headers["content-type"] == "text/turtle"


async def test_create_member_405_is_not_a_container(
    register_fdpneo_write: Callable[[respx.MockRouter], None],
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo_write(mock)
        async with FdpClient(_settings()) as client:
            with pytest.raises(InvalidArgumentError, match="not a container"):
                await create_member(client, f"{BASE}/dataset/1", body="x", media_type="text/turtle")


async def test_create_member_slug_collision_is_conflict(
    register_fdpneo_write: Callable[[respx.MockRouter], None],
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo_write(mock)
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpConflictError):
                await create_member(
                    client, f"{BASE}/catalog/1", body="x", media_type="text/turtle", slug="taken"
                )


async def test_create_member_without_location_is_upstream_error() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{BASE}/catalog/1").mock(return_value=httpx.Response(201))
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpUpstreamError, match="Location"):
                await create_member(client, f"{BASE}/catalog/1", body="x", media_type="text/turtle")


async def test_create_member_off_origin_location_is_refused() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{BASE}/catalog/1").mock(
            return_value=httpx.Response(201, headers={"location": "https://evil.example/x"})
        )
        async with FdpClient(_settings()) as client:
            with pytest.raises(EgressError):
                await create_member(client, f"{BASE}/catalog/1", body="x", media_type="text/turtle")


async def test_replace_patch_delete_require_matching_etag(
    register_fdpneo_write: Callable[[respx.MockRouter], None], write_surface: WriteSurface
) -> None:
    write_surface.exists = True
    write_surface.version = 3
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo_write(mock)
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpPreconditionError):
                await replace_resource(
                    client, NEW_DATASET, body="x", media_type="text/turtle", if_match='"stale"'
                )
            outcome = await replace_resource(
                client, NEW_DATASET, body="x", media_type="text/turtle", if_match='"v3"'
            )
            assert outcome.etag == '"v4"'
            outcome = await patch_resource(
                client, NEW_DATASET, update="INSERT DATA { <a:b> <a:c> 'd' }", if_match='"v4"'
            )
            assert outcome.etag == '"v5"'
            assert write_surface.requests[-1].headers["if-match"] == '"v4"'
            await delete_resource(client, NEW_DATASET, if_match='"v5"')
    assert write_surface.exists is False


async def test_patch_415_degrades_to_unsupported_ldp_patch() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.patch(NEW_DATASET).mock(
            return_value=httpx.Response(415, headers={"accept-patch": "text/ldpatch"})
        )
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpUnsupportedError) as info:
                await patch_resource(client, NEW_DATASET, update="x", if_match='"v"')
    assert route.called
    assert info.value.capability == "ldp_patch"
    assert "text/ldpatch" in info.value.reason
    assert info.value.alternative is not None


async def test_write_verbs_forward_bearer_and_respect_egress() -> None:
    from pydantic import SecretStr

    with respx.mock(assert_all_called=False) as mock:
        route = mock.delete(NEW_DATASET).mock(return_value=httpx.Response(204))
        async with FdpClient(_settings(), credential=SecretStr("fdpk_x")) as client:
            await delete_resource(client, NEW_DATASET, if_match='"v"')
            with pytest.raises(EgressError):
                await client.put(
                    "https://evil.example/r",
                    content="x",
                    content_type="text/turtle",
                    if_match='"v"',
                )
    assert route.calls.last.request.headers["authorization"] == "Bearer fdpk_x"


# --- transition_state ladder ---------------------------------------------------


async def test_transition_state_falls_back_to_convention_when_link_404s(
    register_fdpneo_write: Callable[[respx.MockRouter], None], write_surface: WriteSurface
) -> None:
    write_surface.exists = True
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo_write(mock)
        async with FdpClient(_settings()) as client:
            outcome = await transition_state(client, NEW_DATASET, to="PUBLISHED")
    assert (outcome.from_state, outcome.to_state) == ("DRAFT", "PUBLISHED")
    assert write_surface.state == "PUBLISHED"


async def test_transition_state_uses_advertised_link_first() -> None:
    link = f'<{NEW_DATASET}/state>; rel="https://w3id.org/fdp/o#hasStateTransition"'
    with respx.mock(assert_all_called=False) as mock:
        mock.get(NEW_DATASET).mock(
            return_value=httpx.Response(
                200, text=NEW_DATASET_TTL, headers={"content-type": "text/turtle", "link": link}
            )
        )
        advertised = mock.post(f"{NEW_DATASET}/state").mock(
            return_value=httpx.Response(200, json={"from_state": "DRAFT", "to_state": "PUBLISHED"})
        )
        conventional = mock.post(f"{BASE}/fdp-api/dataset/2/state")
        async with FdpClient(_settings()) as client:
            await transition_state(client, NEW_DATASET, to="PUBLISHED")
    assert advertised.called and not conventional.called


async def test_transition_state_refuses_off_origin_link() -> None:
    link = '<https://evil.example/state>; rel="https://w3id.org/fdp/o#hasStateTransition"'
    with respx.mock(assert_all_called=False) as mock:
        mock.get(NEW_DATASET).mock(
            return_value=httpx.Response(
                200, text=NEW_DATASET_TTL, headers={"content-type": "text/turtle", "link": link}
            )
        )
        async with FdpClient(_settings()) as client:
            with pytest.raises(EgressError):
                await transition_state(client, NEW_DATASET, to="PUBLISHED")


async def test_transition_state_unsupported_when_no_endpoint_works() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(NEW_DATASET).mock(
            return_value=httpx.Response(
                200, text=NEW_DATASET_TTL, headers={"content-type": "text/turtle"}
            )
        )
        mock.post(f"{BASE}/fdp-api/dataset/2/state").mock(return_value=httpx.Response(404))
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpUnsupportedError) as info:
                await transition_state(client, NEW_DATASET, to="PUBLISHED")
    assert info.value.capability == "state_transition"


async def test_transition_state_conflict_relays_allowed_transitions(
    register_fdpneo_write: Callable[[respx.MockRouter], None], write_surface: WriteSurface
) -> None:
    write_surface.exists = True
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo_write(mock)
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpConflictError) as info:
                await transition_state(client, NEW_DATASET, to="ARCHIVED")
    assert info.value.details == {
        "from": "DRAFT",
        "to": "ARCHIVED",
        "current_state": "DRAFT",
        "allowed_transitions": ["PUBLISHED"],
    }


async def test_transition_state_rejects_unknown_state() -> None:
    async with FdpClient(_settings()) as client:
        with pytest.raises(InvalidArgumentError):
            await transition_state(client, NEW_DATASET, to="GONE")
