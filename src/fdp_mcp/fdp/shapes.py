"""SHACL shape retrieval and digest.

Resolves the shape for a record via its ``ldp:constrainedBy`` link (the one
cross-implementation signal, LDP R12) and fetches it by content negotiation,
then digests the ``sh:property`` constraints into an agent-friendly list so
``get_schema`` can tell an agent what a kind's fields mean.

When a record advertises no resolvable shape, or the shape cannot be fetched,
the capability degrades to ``FdpUnsupportedError`` (capability ``shapes``) —
shape discovery is under-specified across FDPs (see fdp-api-gaps.md G-02).
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass

from rdflib import Graph, URIRef
from rdflib.namespace import SH

from fdp_mcp.fdp.client import DEFAULT_RDF_ACCEPT, FdpClient
from fdp_mcp.fdp.errors import FdpError, FdpUnsupportedError, raise_for_status
from fdp_mcp.fdp.ldp import fetch_resource
from fdp_mcp.fdp.rdf import parse_graph

# Shape fetch statuses that mean "no resolvable shape" rather than a hard error.
_UNSUPPORTED_STATUSES = frozenset({404, 405, 406, 501})

# Bound on how many shapes the sh:node closure walk will fetch (defence against a
# pathological or cyclic composition chain).
_MAX_CLOSURE_SHAPES = 25


@dataclass(frozen=True)
class ShapeProperty:
    """A digested ``sh:property`` constraint."""

    path: str | None
    name: str | None
    min_count: int | None
    max_count: int | None
    datatype: str | None
    node_kind: str | None
    cls: str | None
    description: str | None


@dataclass(frozen=True)
class ShapeDoc:
    """A fetched SHACL shape: its targets, digested properties, and raw graph."""

    shape_iri: str
    target_class_iris: list[str]
    properties: list[ShapeProperty]
    media_type: str
    text: str
    graph: Graph


def _local_name(iri: str) -> str:
    return re.split(r"[#/]", iri.rstrip("/"))[-1] or iri


def _value_str(graph: Graph, subject: URIRef, predicate: URIRef) -> str | None:
    value = graph.value(subject, predicate)
    return str(value) if value is not None else None


def _value_int(graph: Graph, subject: URIRef, predicate: URIRef) -> int | None:
    value = graph.value(subject, predicate)
    if value is None:
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def digest_shape(graph: Graph, shape_iri: str) -> tuple[list[str], list[ShapeProperty]]:
    """Extract target classes and a property digest from a (possibly composed) shape graph.

    ``target_class`` is read from the primary shape only (the kind's own type),
    while properties are aggregated across **every** ``sh:property`` in the graph
    — so a graph that includes the ``sh:node`` closure (see ``fetch_shape``)
    yields the full effective field set, not just the primary shape's direct
    properties (fdp-api-gaps.md G-06). Exact-duplicate properties are collapsed
    and the result is sorted by path for determinism.
    """
    subject = URIRef(shape_iri)
    targets = sorted(str(o) for o in graph.objects(subject, SH.targetClass))

    by_signature: dict[tuple[str | None, ...], ShapeProperty] = {}
    for prop in graph.objects(None, SH.property):
        # A property shape is usually a blank node; it is a valid triple subject.
        path = _value_str(graph, prop, SH.path)  # type: ignore[arg-type]
        name = _value_str(graph, prop, SH.name)  # type: ignore[arg-type]
        if name is None and path is not None:
            name = _local_name(path)
        datatype = _value_str(graph, prop, SH.datatype)  # type: ignore[arg-type]
        node_kind = _value_str(graph, prop, SH.nodeKind)  # type: ignore[arg-type]
        cls = _value_str(graph, prop, SH["class"])  # type: ignore[arg-type]
        min_count = _value_int(graph, prop, SH.minCount)  # type: ignore[arg-type]
        max_count = _value_int(graph, prop, SH.maxCount)  # type: ignore[arg-type]
        signature = (
            path,
            datatype,
            node_kind,
            cls,
            str(min_count),
            str(max_count),
        )
        if signature in by_signature:
            continue
        by_signature[signature] = ShapeProperty(
            path=path,
            name=name,
            min_count=min_count,
            max_count=max_count,
            datatype=datatype,
            node_kind=node_kind,
            cls=cls,
            description=_value_str(graph, prop, SH.description),  # type: ignore[arg-type]
        )
    properties = sorted(by_signature.values(), key=lambda p: (p.path or "", p.datatype or ""))
    return targets, properties


async def _compose_closure(client: FdpClient, merged: Graph, *, root: str) -> None:
    """Fetch the shapes ``root`` composes via ``sh:node`` and merge them in place.

    Follows ``sh:node`` references breadth-first, bounded and cycle-guarded. Each
    referenced shape is fetched through the egress-guarded client, so an
    off-origin reference (or one that errors/404s) is simply skipped — the
    closure is best-effort and never breaks the primary shape's digest.
    """
    seen = {root}
    queue: deque[str] = deque(
        str(o) for o in merged.objects(None, SH.node) if isinstance(o, URIRef)
    )
    while queue and len(seen) < _MAX_CLOSURE_SHAPES:
        iri = queue.popleft()
        if iri in seen:
            continue
        seen.add(iri)
        try:
            doc = await client.get(iri, accept=DEFAULT_RDF_ACCEPT)
        except FdpError:
            continue  # off-origin (egress) or transport failure on a reference
        if doc.status >= 400:
            continue
        graph = parse_graph(doc.text, doc.media_type, public_id=iri)
        merged += graph
        for ref in graph.objects(None, SH.node):
            if isinstance(ref, URIRef) and str(ref) not in seen:
                queue.append(str(ref))


async def fetch_shape(client: FdpClient, shape_iri: str) -> ShapeDoc:
    """Fetch a SHACL shape, compose its ``sh:node`` closure, and digest it.

    The primary shape's fetch governs success/unsupported; the closure
    (composed shapes reached via ``sh:node``) is merged best-effort so the digest
    reflects the effective field set (G-06).
    """
    doc = await client.get(shape_iri, accept=DEFAULT_RDF_ACCEPT)
    if doc.status in _UNSUPPORTED_STATUSES:
        raise FdpUnsupportedError(
            "shapes",
            f"No SHACL shape is resolvable at {shape_iri} (HTTP {doc.status}).",
        )
    raise_for_status(doc.status, iri=shape_iri)
    graph = parse_graph(doc.text, doc.media_type, public_id=shape_iri)
    await _compose_closure(client, graph, root=shape_iri)
    targets, properties = digest_shape(graph, shape_iri)
    return ShapeDoc(
        shape_iri=shape_iri,
        target_class_iris=targets,
        properties=properties,
        media_type=doc.media_type,
        text=doc.text,
        graph=graph,
    )


async def fetch_shape_for_record(client: FdpClient, record_iri: str) -> ShapeDoc:
    """Resolve a record's ``constrainedBy`` shape and fetch it.

    Degrades to ``FdpUnsupportedError`` (capability ``shapes``) when the record
    advertises no shape.
    """
    record = await fetch_resource(client, record_iri)
    shape_iri = record.constrained_by
    if shape_iri is None:
        raise FdpUnsupportedError(
            "shapes",
            f"The record {record_iri} advertises no constrainedBy shape.",
        )
    return await fetch_shape(client, shape_iri)
