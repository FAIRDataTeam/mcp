"""Result shaping: JSON-LD framing, the Record object, and the envelopes.

Turns the FDP client layer's ``LdpResource``/RDF into the JSON shapes the
tool-surface contract (``docs/mcp-tool-surface.md``) specifies:

* **framed JSON-LD** — a compacted, single-subject-rooted document (the record
  IRI as ``@id``), blank nodes embedded, predicate/type IRIs compacted to CURIEs
  against a bundled ``@context``; object IRIs stay absolute so agents can cite;
* the **Record object** (§3.6), **page envelope** (§3.3), **error envelope**
  (§3.4), and the **unsupported result** (§3.5);
* a mapping from the client layer's typed errors onto the contract error codes.

No external dereferencing and no network here — pure transformation.
"""

from __future__ import annotations

from typing import Any

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF

from fdp_mcp.fdp.errors import (
    EgressError,
    FdpError,
    FdpNotFoundError,
    FdpResponseTooLargeError,
    FdpTimeoutError,
    FdpUnauthorizedError,
    FdpUnsupportedError,
    FdpUpstreamError,
    InvalidArgumentError,
    InvalidQueryError,
    ReadOnlyError,
)
from fdp_mcp.fdp.ldp import LdpResource, slug_for_type
from fdp_mcp.fdp.search import SearchHit
from fdp_mcp.fdp.sparql import AskResult, SelectResult, SparqlResult

_XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"

# Bundled prefix map used to compact predicate/type IRIs into CURIEs in framed
# JSON-LD. Object IRIs are left absolute (citation), so this is display-only.
CONTEXT: dict[str, str] = {
    "dcterms": "http://purl.org/dc/terms/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "ldp": "http://www.w3.org/ns/ldp#",
    "odrl": "http://www.w3.org/ns/odrl/2/",
    "vcard": "http://www.w3.org/2006/vcard/ns#",
    "prov": "http://www.w3.org/ns/prov#",
    "sh": "http://www.w3.org/ns/shacl#",
    "fdp": "https://w3id.org/fdp/o#",
}


def compact_iri(iri: str) -> str:
    """Compact an IRI to a ``prefix:local`` CURIE when a bundled prefix matches."""
    for prefix, namespace in CONTEXT.items():
        if iri.startswith(namespace) and len(iri) > len(namespace):
            return f"{prefix}:{iri[len(namespace) :]}"
    return iri


def _literal_value(literal: Literal) -> Any:
    if literal.language:
        return {"@value": str(literal), "@language": literal.language}
    datatype = literal.datatype
    if datatype is not None and str(datatype) != _XSD_STRING:
        return {"@value": str(literal), "@type": compact_iri(str(datatype))}
    return str(literal)


def _term(obj: object, graph: Graph, seen: frozenset[str]) -> Any:
    if isinstance(obj, URIRef):
        return {"@id": str(obj)}  # object IRIs stay absolute for citation
    if isinstance(obj, BNode):
        key = str(obj)
        if key in seen:  # cycle guard
            return {"@id": f"_:{key}"}
        return _node(graph, obj, seen | {key}, include_id=False)
    if isinstance(obj, Literal):
        return _literal_value(obj)
    return str(obj)  # pragma: no cover - rdflib objects are URIRef/BNode/Literal


def _node(
    graph: Graph, subject: URIRef | BNode, seen: frozenset[str], *, include_id: bool
) -> dict[str, Any]:
    node: dict[str, Any] = {}
    if include_id and isinstance(subject, URIRef):
        node["@id"] = str(subject)
    types = [compact_iri(str(t)) for t in graph.objects(subject, RDF.type)]
    if types:
        node["@type"] = types
    grouped: dict[str, list[Any]] = {}
    for predicate, obj in graph.predicate_objects(subject):
        if predicate == RDF.type:
            continue
        grouped.setdefault(compact_iri(str(predicate)), []).append(_term(obj, graph, seen))
    for key, values in grouped.items():
        node[key] = values[0] if len(values) == 1 else values
    return node


def frame_record(graph: Graph, subject_iri: str) -> dict[str, Any]:
    """Frame a record graph as compacted JSON-LD rooted at ``subject_iri``."""
    node = _node(graph, URIRef(subject_iri), frozenset({subject_iri}), include_id=True)
    node["@context"] = dict(CONTEXT)
    return node


def frame_graph(graph: Graph) -> dict[str, Any]:
    """Frame a multi-subject graph (e.g. a CONSTRUCT result) as ``@graph`` JSON-LD.

    Named subjects become top-level nodes; blank nodes are embedded where
    referenced. Used for ``sparql_query`` CONSTRUCT/DESCRIBE results.
    """
    subjects = sorted({str(s) for s in graph.subjects() if isinstance(s, URIRef)})
    nodes = [_node(graph, URIRef(s), frozenset({s}), include_id=True) for s in subjects]
    return {"@context": dict(CONTEXT), "@graph": nodes}


def sparql_result_object(result: SparqlResult) -> dict[str, Any]:
    """Shape a SPARQL result per the contract (§5.6), by query form."""
    if isinstance(result, SelectResult):
        return {"form": "select", "head": result.head, "results": result.results}
    if isinstance(result, AskResult):
        return {"form": "ask", "boolean": result.boolean}
    return {"form": result.form, "graph": frame_graph(result.graph)}


def search_hit_object(hit: SearchHit) -> dict[str, Any]:
    """Shape one search hit as a summary Record object (§5.5)."""
    types = [hit.type_iri] if hit.type_iri else []
    metadata: dict[str, Any] = {"@id": hit.record_iri, "@type": [compact_iri(t) for t in types]}
    if hit.title is not None:
        metadata["dcterms:title"] = hit.title
    if hit.description is not None:
        metadata["dcterms:description"] = hit.description
    return {
        "iri": hit.record_iri,
        "types": types,
        "title": hit.title,
        "kind": slug_for_type(hit.type_iri) if hit.type_iri else None,
        "metadata": metadata,
        "links": {},
    }


def _summary_metadata(resource: LdpResource) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "@id": resource.iri,
        "@type": [compact_iri(t) for t in resource.type_iris],
    }
    if resource.title is not None:
        metadata["dcterms:title"] = resource.title
    return metadata


def _links(resource: LdpResource) -> dict[str, Any]:
    links: dict[str, Any] = {}
    if resource.parent_iri is not None:
        links["parent"] = resource.parent_iri
    members = resource.member_iris
    if members:
        links["children"] = members
    if resource.constrained_by is not None:
        links["constrained_by"] = resource.constrained_by
    if resource.links.cite_as is not None:
        links["cite_as"] = resource.links.cite_as
    described_by = resource.links.described_by
    if described_by:
        links["described_by"] = described_by
    if resource.links.license is not None:
        links["license"] = resource.links.license
    if resource.links.authors:
        links["authors"] = resource.links.authors
    return links


def record_object(
    resource: LdpResource,
    *,
    kind: str | None = None,
    summary: bool = False,
    fmt: str = "jsonld",
) -> dict[str, Any]:
    """Build the contract Record object (§3.6) from a fetched resource."""
    obj: dict[str, Any] = {
        "iri": resource.iri,
        "types": resource.type_iris,
        "title": resource.title,
        "kind": kind,
        "links": _links(resource),
    }
    if fmt == "jsonld":
        obj["metadata"] = (
            _summary_metadata(resource) if summary else frame_record(resource.graph, resource.iri)
        )
    else:
        obj["metadata"] = resource.text
        obj["metadata_media_type"] = resource.media_type
    return obj


def page_envelope(
    items: list[dict[str, Any]],
    *,
    limit: int,
    offset: int,
    total: int | None,
    truncated: bool = False,
) -> dict[str, Any]:
    """Wrap a page of items in the contract page envelope (§3.3).

    ``truncated`` (when the underlying enumeration hit the bridge's crawl cap and
    the totals are therefore partial) is surfaced on the page so an agent can
    tell an incomplete result from a complete one.
    """
    count = len(items)
    # With a reliable total, "more" is exact; without one, a full page suggests more.
    has_more = offset + count < total if total is not None else count >= limit
    page: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "count": count,
        "has_more": has_more,
        "total": total,
    }
    if has_more:
        page["next_offset"] = offset + count
    if truncated:
        page["truncated"] = True
    return {"items": items, "page": page}


# --- error / unsupported envelopes -----------------------------------------

_ERROR_CODES: dict[type[FdpError], str] = {
    InvalidArgumentError: "invalid_argument",
    InvalidQueryError: "invalid_argument",
    EgressError: "invalid_argument",
    ReadOnlyError: "read_only_violation",
    FdpNotFoundError: "not_found",
    FdpUnauthorizedError: "upstream_unauthorized",
    FdpTimeoutError: "upstream_timeout",
    FdpResponseTooLargeError: "too_large",
    FdpUpstreamError: "upstream_error",
}


def error_result(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """The contract error envelope (§3.4)."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


def unsupported_result(tool: str, exc: FdpUnsupportedError) -> dict[str, Any]:
    """The contract unsupported result (§3.5) for an optional tool."""
    body: dict[str, Any] = {
        "tool": tool,
        "reason": exc.reason,
        "capability": exc.capability,
    }
    if exc.alternative is not None:
        body["alternative"] = exc.alternative
    return {"unsupported": body}


def result_from_error(tool: str, exc: FdpError) -> dict[str, Any]:
    """Map a client-layer error onto the contract error / unsupported result."""
    if isinstance(exc, FdpUnsupportedError):
        return unsupported_result(tool, exc)
    code = _ERROR_CODES.get(type(exc), "upstream_error")
    return error_result(code, str(exc) or code)
