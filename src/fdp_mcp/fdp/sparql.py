"""SPARQL access — read-only query forms only.

The FDP's public SPARQL query endpoint, with the read-only guarantee enforced
**client-side before any network call** (CLAUDE.md ground rule, ADR-0018 §5):
the query is parsed with rdflib; update forms are rejected as ``ReadOnlyError``,
unparseable input as ``InvalidQueryError``, and a ``SERVICE`` (federation) clause
as ``InvalidQueryError`` (it would make the FDP fetch from a third party, outside
the strict-egress posture). Only ``SELECT``/``ASK``/``CONSTRUCT``/``DESCRIBE`` are
forwarded.

Results are shaped by form: SELECT/ASK come back as SPARQL Results JSON, and
CONSTRUCT/DESCRIBE as an RDF graph.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, cast

import httpx
from rdflib import Graph, URIRef
from rdflib.plugins.sparql.algebra import translateQuery, translateUpdate
from rdflib.plugins.sparql.parser import parseQuery, parseUpdate

from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import (
    FdpUnsupportedError,
    FdpUpstreamError,
    InvalidQueryError,
    ReadOnlyError,
    raise_for_status,
)
from fdp_mcp.fdp.rdf import parse_graph

QueryForm = Literal["select", "ask", "construct", "describe"]

_ALGEBRA_TO_FORM: dict[str, QueryForm] = {
    "SelectQuery": "select",
    "AskQuery": "ask",
    "ConstructQuery": "construct",
    "DescribeQuery": "describe",
}

_SPARQL_QUERY_CT = "application/sparql-query"
_RESULTS_JSON = "application/sparql-results+json"
_GRAPH_ACCEPT = "text/turtle;q=1.0, application/ld+json;q=0.9"

# The SPARQL endpoint may be absent/disabled; these statuses mean "no surface".
_UNSUPPORTED_STATUSES = frozenset({404, 405, 501})


@dataclass(frozen=True)
class SelectResult:
    form: Literal["select"]
    head: dict[str, Any]
    results: dict[str, Any]


@dataclass(frozen=True)
class AskResult:
    form: Literal["ask"]
    boolean: bool


@dataclass(frozen=True)
class GraphResult:
    form: Literal["construct", "describe"]
    graph: Graph


SparqlResult = SelectResult | AskResult | GraphResult


def _contains_service(node: object) -> bool:
    """Recursively scan a translated SPARQL algebra for a ``SERVICE`` clause."""
    if isinstance(node, dict):  # rdflib CompValue is a dict subclass
        mapping = cast("dict[str, object]", node)
        # CompValue exposes its production name as an attribute, not a dict key.
        if getattr(mapping, "name", None) == "ServiceGraphPattern":
            return True
        return any(_contains_service(value) for value in mapping.values())
    if isinstance(node, (list, tuple)):
        sequence = cast("list[object] | tuple[object, ...]", node)
        return any(_contains_service(item) for item in sequence)
    return False


def classify_query(query: str) -> QueryForm:
    """Classify a SPARQL string, rejecting non-read forms before any network call.

    Returns the read form, or raises ``ReadOnlyError`` (update),
    ``InvalidQueryError`` (unparseable, or contains ``SERVICE``).
    """
    try:
        parsed = parseQuery(query)
    except Exception as exc:
        # Not a read query — is it a (rejected) update, or just malformed?
        try:
            parseUpdate(query)
        except Exception as parse_exc:
            raise InvalidQueryError(f"not a valid SPARQL query: {parse_exc}") from parse_exc
        raise ReadOnlyError("SPARQL update forms are not permitted") from exc

    try:
        algebra = translateQuery(parsed).algebra
    except Exception as exc:
        raise InvalidQueryError(f"could not analyse SPARQL query: {exc}") from exc

    if _contains_service(algebra):
        raise InvalidQueryError("SERVICE (federation) clauses are not permitted")

    form = _ALGEBRA_TO_FORM.get(algebra.name)
    if form is None:  # pragma: no cover - the four read forms are exhaustive
        raise InvalidQueryError(f"unsupported query form: {algebra.name}")
    return form


# Update operations a record-level PATCH may carry: edits to the record's own
# triples. Graph-management verbs (CREATE/DROP/CLEAR/ADD/MOVE/COPY) and LOAD are
# not "edit this record" and are rejected; LOAD in particular would make the FDP
# fetch an arbitrary URL on the bridge's behalf (strict egress by proxy).
_ALLOWED_UPDATE_OPS = frozenset({"InsertData", "DeleteData", "DeleteWhere", "Modify"})


def _graph_names(op: object) -> list[URIRef]:
    """Named graphs an update operation addresses: quad keys, WITH, USING, GRAPH patterns."""
    found: list[URIRef] = []
    if not isinstance(op, dict):
        return found
    mapping = cast("dict[str, object]", op)
    if getattr(mapping, "name", None) == "Graph":  # GRAPH <iri> { ... } pattern
        term = mapping.get("term")
        if isinstance(term, URIRef):
            found.append(term)
    quads = mapping.get("quads")
    if isinstance(quads, dict):
        found.extend(k for k in cast("dict[object, object]", quads) if isinstance(k, URIRef))
    with_clause = mapping.get("withClause")
    if isinstance(with_clause, URIRef):
        found.append(with_clause)
    using = mapping.get("using")
    if isinstance(using, (list, tuple)):
        for clause in cast("list[object] | tuple[object, ...]", using):
            if isinstance(clause, dict):
                clause_map = cast("dict[str, object]", clause)
                for key in ("default", "named"):
                    value = clause_map.get(key)
                    if isinstance(value, URIRef):
                        found.append(value)
    for key, value in mapping.items():
        if key in ("quads", "using", "withClause"):
            continue
        if isinstance(value, dict):
            found.extend(_graph_names(cast("dict[str, object]", value)))
        elif isinstance(value, (list, tuple)):
            for item in cast("list[object] | tuple[object, ...]", value):
                found.extend(_graph_names(item))
    return found


def _same_origin(a: httpx.URL, b: httpx.URL) -> bool:
    def norm(u: httpx.URL) -> tuple[str, str, int]:
        return (u.scheme, u.host, u.port or (443 if u.scheme == "https" else 80))

    return norm(a) == norm(b)


def classify_update(update: str, *, origin: str) -> list[str]:
    """Validate a SPARQL *update* for use as a record PATCH, before any network call.

    Returns the operation names (e.g. ``["Modify"]``). Raises
    ``InvalidQueryError`` when the text is not a valid update, contains a
    read-query form, uses a disallowed operation (``LOAD``, ``CLEAR``, ``DROP``,
    ``CREATE``, ``ADD``, ``MOVE``, ``COPY``), contains ``SERVICE``, or names a
    graph outside the FDP ``origin`` (``scheme://host[:port]``).
    """
    try:
        parsed = parseUpdate(update)
    except Exception as exc:
        raise InvalidQueryError(f"not a valid SPARQL update: {exc}") from exc
    try:
        operations = translateUpdate(parsed).algebra
    except Exception as exc:
        raise InvalidQueryError(f"could not analyse SPARQL update: {exc}") from exc
    if not operations:
        raise InvalidQueryError("SPARQL update contains no operations")

    allowed_origin = httpx.URL(origin)
    names: list[str] = []
    for op in operations:
        name = str(op.name)
        if name not in _ALLOWED_UPDATE_OPS:
            raise InvalidQueryError(f"SPARQL update operation {name.upper()} is not permitted")
        if _contains_service(op):
            raise InvalidQueryError("SERVICE (federation) clauses are not permitted")
        for graph_iri in _graph_names(op):
            if not _same_origin(httpx.URL(str(graph_iri)), allowed_origin):
                raise InvalidQueryError(f"graph {graph_iri} is outside the FDP origin {origin}")
        names.append(name)
    return names


async def run_query(client: FdpClient, endpoint: str, query: str) -> SparqlResult:
    """Classify then execute a read-only SPARQL query against ``endpoint``.

    Raises ``FdpUnsupportedError`` (capability ``sparql``) when the endpoint is
    absent/disabled, plus the read-only/parse errors from ``classify_query`` and
    the transport errors from the client.
    """
    form = classify_query(query)
    accept = _RESULTS_JSON if form in ("select", "ask") else _GRAPH_ACCEPT
    doc = await client.post(endpoint, content=query, content_type=_SPARQL_QUERY_CT, accept=accept)

    if doc.status in _UNSUPPORTED_STATUSES:
        raise FdpUnsupportedError(
            "sparql",
            f"This FDP exposes no SPARQL endpoint at {endpoint} (HTTP {doc.status}).",
        )
    raise_for_status(doc.status, iri=endpoint)

    if form in ("select", "ask"):
        return _parse_results_json(doc.text, form, endpoint)
    graph = parse_graph(doc.text, doc.media_type, public_id=endpoint)
    return GraphResult(form=form, graph=graph)


def _parse_results_json(text: str, form: QueryForm, endpoint: str) -> SelectResult | AskResult:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FdpUpstreamError(
            f"SPARQL results from {endpoint} were not valid JSON: {exc}"
        ) from exc
    if form == "ask":
        return AskResult(form="ask", boolean=bool(payload.get("boolean", False)))
    return SelectResult(
        form="select",
        head=payload.get("head", {}),
        results=payload.get("results", {}),
    )
