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
from dataclasses import dataclass

from rdflib import Graph, URIRef
from rdflib.namespace import SH

from fdp_mcp.fdp.client import DEFAULT_RDF_ACCEPT, FdpClient
from fdp_mcp.fdp.errors import FdpUnsupportedError, raise_for_status
from fdp_mcp.fdp.ldp import fetch_resource
from fdp_mcp.fdp.rdf import parse_graph

# Shape fetch statuses that mean "no resolvable shape" rather than a hard error.
_UNSUPPORTED_STATUSES = frozenset({404, 405, 406, 501})


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
    """Extract target classes and a flat property digest from a SHACL shape graph."""
    subject = URIRef(shape_iri)
    targets = sorted(str(o) for o in graph.objects(subject, SH.targetClass))

    properties: list[ShapeProperty] = []
    for prop in graph.objects(subject, SH.property):
        # A property shape is usually a blank node; it is a valid triple subject.
        path = _value_str(graph, prop, SH.path)  # type: ignore[arg-type]
        name = _value_str(graph, prop, SH.name)  # type: ignore[arg-type]
        if name is None and path is not None:
            name = _local_name(path)
        properties.append(
            ShapeProperty(
                path=path,
                name=name,
                min_count=_value_int(graph, prop, SH.minCount),  # type: ignore[arg-type]
                max_count=_value_int(graph, prop, SH.maxCount),  # type: ignore[arg-type]
                datatype=_value_str(graph, prop, SH.datatype),  # type: ignore[arg-type]
                node_kind=_value_str(graph, prop, SH.nodeKind),  # type: ignore[arg-type]
                cls=_value_str(graph, prop, SH["class"]),  # type: ignore[arg-type]
                description=_value_str(graph, prop, SH.description),  # type: ignore[arg-type]
            )
        )
    return targets, properties


async def fetch_shape(client: FdpClient, shape_iri: str) -> ShapeDoc:
    """Fetch and digest a SHACL shape document by IRI."""
    doc = await client.get(shape_iri, accept=DEFAULT_RDF_ACCEPT)
    if doc.status in _UNSUPPORTED_STATUSES:
        raise FdpUnsupportedError(
            "shapes",
            f"No SHACL shape is resolvable at {shape_iri} (HTTP {doc.status}).",
        )
    raise_for_status(doc.status, iri=shape_iri)
    graph = parse_graph(doc.text, doc.media_type, public_id=shape_iri)
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
