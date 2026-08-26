"""LDP write operations: create, replace, patch, delete, and state transitions.

The public, spec-compliant write surface of an FDP (contract §5.9-§5.12,
ADR-0024): ``POST`` to a container, ``PUT``/``PATCH``/``DELETE`` on a record
under an ``If-Match`` precondition, and the publication-state transition
endpoint. Everything goes through the strict-egress :class:`FdpClient`; the
FDP alone authorises and validates (SHACL). What the bridge does *before* the
network call is syntactic only:

* the RDF body must parse and name exactly one primary subject (the FDP would
  answer ``400``; failing early gives the agent a better message and is
  portable across implementations);
* a SPARQL-update PATCH must be a valid update using only record-editing
  operations — ``LOAD``/``SERVICE`` are refused (egress by proxy).

PATCH and state transitions are optional capabilities (``ldp_patch``,
``state_transition``); when the FDP lacks them the caller gets
``FdpUnsupportedError`` and the tool degrades explicitly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, cast

import httpx
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, Namespace

from fdp_mcp.fdp.client import FdpClient, FetchedDocument
from fdp_mcp.fdp.errors import (
    FdpConflictError,
    FdpNotFoundError,
    FdpUnsupportedError,
    FdpUpstreamError,
    InvalidArgumentError,
    raise_for_status,
)
from fdp_mcp.fdp.ldp import LdpResource, fetch_resource
from fdp_mcp.fdp.rdf import MEDIA_TO_RDFLIB
from fdp_mcp.fdp.sparql import classify_update

FDP_O = Namespace("https://w3id.org/fdp/o#")
REL_HAS_STATE_TRANSITION = str(FDP_O.hasStateTransition)

WriteMediaType = Literal[
    "text/turtle", "application/ld+json", "application/rdf+xml", "application/n-triples"
]
WRITE_MEDIA_TYPES: frozenset[str] = frozenset(
    {"text/turtle", "application/ld+json", "application/rdf+xml", "application/n-triples"}
)
RecordState = Literal["DRAFT", "PUBLISHED", "ARCHIVED"]
RECORD_STATES: frozenset[str] = frozenset({"DRAFT", "PUBLISHED", "ARCHIVED"})

SPARQL_UPDATE_CT = "application/sparql-update"
_JSON_ACCEPT = "application/json"
_STATE_UNSUPPORTED = frozenset({404, 405})


@dataclass(frozen=True)
class WriteOutcome:
    """What a successful write told us: the record IRI and its new validator."""

    iri: str
    etag: str | None
    status: int


@dataclass(frozen=True)
class StateOutcome:
    iri: str
    from_state: str | None
    to_state: str


# --- pre-network validation --------------------------------------------------


def validate_rdf_body(body: str, media_type: str, *, base_iri: str, max_bytes: int) -> Graph:
    """Parse an agent-supplied RDF body and check it has one primary subject.

    ``base_iri`` resolves relative IRIs (``<>`` for "this record"). Raises
    ``InvalidArgumentError`` for an unsupported media type, an oversized or
    unparseable body, an empty graph, or a graph whose named subjects are not
    exactly one IRI. Blank-node subjects (nested structures) are fine.
    """
    if media_type not in WRITE_MEDIA_TYPES:
        raise InvalidArgumentError(
            f"unsupported media_type {media_type!r}; use one of {sorted(WRITE_MEDIA_TYPES)}"
        )
    if len(body.encode("utf-8")) > max_bytes:
        raise InvalidArgumentError(f"body exceeds the {max_bytes}-byte cap")
    graph = Graph()
    try:
        graph.parse(data=body, format=MEDIA_TO_RDFLIB[media_type], publicID=base_iri)
    except Exception as exc:  # rdflib raises a variety of parse errors
        raise InvalidArgumentError(f"body is not valid {media_type}: {exc}") from exc
    if len(graph) == 0:
        raise InvalidArgumentError("body contains no triples")
    named = {s for s in graph.subjects() if isinstance(s, URIRef)}
    if not named:
        raise InvalidArgumentError("body has no IRI subject (blank nodes only)")
    if len(named) > 1:
        # Typed IRI subjects are candidates for "the record"; others are
        # ancillary (e.g. an inline foaf:Agent). Exactly one candidate is required.
        typed = {s for s in named if (s, RDF.type, None) in graph}
        if len(typed) != 1:
            raise InvalidArgumentError(
                "body must have exactly one primary subject (use <> or a single typed IRI); "
                f"found {len(named)} IRI subjects, {len(typed)} typed"
            )
    return graph


def validate_update(update: str, *, origin: str) -> None:
    """Validate a SPARQL update for PATCH (see ``sparql.classify_update``)."""
    classify_update(update, origin=origin)


# --- operations ---------------------------------------------------------------


def _raise(doc: FetchedDocument, iri: str) -> None:
    raise_for_status(doc.status, iri=iri, body=doc.text, media_type=doc.media_type)


async def create_member(
    client: FdpClient,
    container_iri: str,
    *,
    body: str,
    media_type: str,
    slug: str | None = None,
) -> WriteOutcome:
    """``POST`` a new member to a container; returns the minted IRI + ETag.

    405 means the target does not accept POST (not a container) → ``InvalidArgumentError``.
    409 (slug taken) → ``FdpConflictError``; 422 → ``FdpValidationError``.
    """
    extra = {"slug": slug} if slug else None
    doc = await client.post(
        container_iri,
        content=body,
        content_type=media_type,
        accept=_JSON_ACCEPT,
        extra_headers=extra,
    )
    if doc.status == 405:
        raise InvalidArgumentError(f"{container_iri} does not accept POST (not a container)")
    _raise(doc, container_iri)
    location = doc.headers.get("location")
    if doc.status != 201 or not location:
        raise FdpUpstreamError(
            f"POST to {container_iri} returned {doc.status} without a Location header"
        )
    iri = str(httpx.URL(container_iri).join(location))
    client._check_egress(httpx.URL(iri))  # pyright: ignore[reportPrivateUsage]
    return WriteOutcome(iri=iri, etag=doc.headers.get("etag"), status=doc.status)


async def replace_resource(
    client: FdpClient, iri: str, *, body: str, media_type: str, if_match: str
) -> WriteOutcome:
    """``PUT`` a full replacement body under ``If-Match``."""
    doc = await client.put(iri, content=body, content_type=media_type, if_match=if_match)
    _raise(doc, iri)
    return WriteOutcome(iri=iri, etag=doc.headers.get("etag"), status=doc.status)


async def patch_resource(
    client: FdpClient, iri: str, *, update: str, if_match: str
) -> WriteOutcome:
    """``PATCH`` with ``application/sparql-update`` under ``If-Match``.

    415/405 → ``FdpUnsupportedError("ldp_patch")``: the FDP has no SPARQL-update
    PATCH (the Java RI, for one). The write itself is the probe.
    """
    doc = await client.patch(iri, content=update, content_type=SPARQL_UPDATE_CT, if_match=if_match)
    if doc.status in (405, 415):
        accepted = doc.headers.get("accept-patch")
        reason = f"This FDP does not accept {SPARQL_UPDATE_CT} PATCH on {iri} (HTTP {doc.status}"
        reason += f"; Accept-Patch: {accepted})." if accepted else ")."
        raise FdpUnsupportedError(
            "ldp_patch", reason, alternative="update_record with body= (full PUT replace)"
        )
    _raise(doc, iri)
    return WriteOutcome(iri=iri, etag=doc.headers.get("etag"), status=doc.status)


async def delete_resource(client: FdpClient, iri: str, *, if_match: str) -> None:
    """``DELETE`` under ``If-Match``."""
    doc = await client.delete(iri, if_match=if_match)
    _raise(doc, iri)


def record_state(resource: LdpResource) -> str | None:
    """The ``fdp:metadataState`` literal on the record, when the FDP serves one."""
    obj = next(resource.graph.objects(URIRef(resource.iri), FDP_O.metadataState), None)
    return str(obj) if obj is not None else None


def allowed_transitions(resource: LdpResource) -> list[str]:
    """``fdp:allowedStateTransition`` hints served with the record (informational only)."""
    return sorted(
        str(o) for o in resource.graph.objects(URIRef(resource.iri), FDP_O.allowedStateTransition)
    )


def _conventional_state_url(client: FdpClient, iri: str) -> str | None:
    """FDPneo's ``{base}/fdp-api/{record path}/state`` (gap G-09; removable once G-08 is fixed)."""
    base = httpx.URL(client.base_url)
    target = httpx.URL(iri)
    if (target.scheme, target.host, target.port) != (base.scheme, base.host, base.port):
        return None
    base_path = base.path.rstrip("/")
    if not target.path.startswith(base_path):
        return None
    record_path = target.path[len(base_path) :].strip("/")
    if not record_path:
        return None
    return str(base.copy_with(path=f"{base_path}/fdp-api/{record_path}/state", query=None))


async def _post_state(client: FdpClient, url: str, to: str) -> FetchedDocument:
    return await client.post(
        url, content=json.dumps({"to": to}), content_type=_JSON_ACCEPT, accept=_JSON_ACCEPT
    )


async def transition_state(client: FdpClient, iri: str, *, to: str) -> StateOutcome:
    """Move a record to publication state ``to`` via the FDP's transition endpoint.

    Endpoint resolution ladder (spec-honest first): (a) the record's advertised
    ``hasStateTransition`` Link (must be on-origin); (b) on 404/405 only, the
    FDPneo path convention; (c) neither works →
    ``FdpUnsupportedError("state_transition")``. 409 → ``FdpConflictError`` with
    the served ``allowedStateTransition`` hints in ``details``.
    """
    if to not in RECORD_STATES:
        raise InvalidArgumentError(f"unknown state {to!r}; use one of {sorted(RECORD_STATES)}")
    resource = await fetch_resource(client, iri)
    candidates: list[str] = []
    advertised = resource.links.first_target(REL_HAS_STATE_TRANSITION)
    if advertised is not None:
        client._check_egress(httpx.URL(advertised))  # pyright: ignore[reportPrivateUsage]
        candidates.append(advertised)
    conventional = _conventional_state_url(client, resource.iri)
    if conventional is not None and conventional not in candidates:
        candidates.append(conventional)

    doc: FetchedDocument | None = None
    for url in candidates:
        doc = await _post_state(client, url, to)
        if doc.status not in _STATE_UNSUPPORTED:
            break
    if doc is None or doc.status in _STATE_UNSUPPORTED:
        raise FdpUnsupportedError(
            "state_transition",
            f"This FDP exposes no working state-transition endpoint for {resource.iri}.",
            alternative="publish or archive the record through the FDP's own UI/API",
        )
    try:
        _raise(doc, resource.iri)
    except FdpConflictError as exc:
        details = dict(exc.details or {})
        details.setdefault("current_state", record_state(resource))
        details.setdefault("allowed_transitions", allowed_transitions(resource))
        raise FdpConflictError(str(exc), details=details) from exc
    except FdpNotFoundError:
        raise
    payload = _parse_json_object(doc, resource.iri)
    from_state = payload.get("from_state")
    to_state = payload.get("to_state")
    return StateOutcome(
        iri=resource.iri,
        from_state=str(from_state) if isinstance(from_state, str) else record_state(resource),
        to_state=str(to_state) if isinstance(to_state, str) else to,
    )


def _parse_json_object(doc: FetchedDocument, iri: str) -> dict[str, object]:
    if not doc.text.strip():
        return {}
    try:
        payload = json.loads(doc.text)
    except ValueError as exc:
        raise FdpUpstreamError(f"state response for {iri} was not valid JSON: {exc}") from exc
    return cast("dict[str, object]", payload) if isinstance(payload, dict) else {}


__all__ = [
    "RECORD_STATES",
    "REL_HAS_STATE_TRANSITION",
    "SPARQL_UPDATE_CT",
    "WRITE_MEDIA_TYPES",
    "RecordState",
    "StateOutcome",
    "WriteMediaType",
    "WriteOutcome",
    "allowed_transitions",
    "create_member",
    "delete_resource",
    "patch_resource",
    "record_state",
    "replace_resource",
    "transition_state",
    "validate_rdf_body",
    "validate_update",
]
