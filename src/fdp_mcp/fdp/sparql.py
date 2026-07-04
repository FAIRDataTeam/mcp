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

from rdflib import Graph
from rdflib.plugins.sparql.algebra import translateQuery
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
