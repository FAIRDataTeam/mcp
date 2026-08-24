"""Endpoint discovery from the FDP root metadata (ADR-0018 gap G-05).

A spec-compliant FDP does not standardise where its SPARQL/search endpoints live,
so historically the bridge had to be *configured* with their paths. FDPneo (and,
in time, any FDP) now **advertises** them in the root record, so the bridge can
*discover* them instead:

* SPARQL — the standard VoID ``void:sparqlEndpoint`` on the root (preferred), or a
  ``dcat:service`` ``dcat:DataService`` whose ``dcat:endpointDescription`` names the
  SPARQL protocol.
* Search — there is no standard predicate, so it is discovered heuristically: the
  single ``dcat:service`` ``dcat:DataService`` (by ``dcat:endpointURL``) that is
  *not* the SPARQL endpoint. Ambiguous (or absent) → no discovery.

Resolution precedence (per endpoint):

1. an **explicit operator override** of the configured path always wins;
2. else the **advertised** endpoint, provided it is on the FDP's own origin
   (the strict-egress rule — an advertisement pointing elsewhere is ignored);
3. else the **configured default** path (and the tool probes + degrades as before).

Discovery never relaxes the API-honesty rule: a resolved endpoint that 404s still
degrades the tool to ``unsupported``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from rdflib import Graph, URIRef
from rdflib.namespace import Namespace

from fdp_mcp.fdp.errors import FdpError
from fdp_mcp.fdp.ldp import fetch_root
from fdp_mcp.log import get_logger

if TYPE_CHECKING:
    from fdp_mcp.config import FdpMcpSettings
    from fdp_mcp.fdp.client import FdpClient

VOID = Namespace("http://rdfs.org/ns/void#")
DCAT = Namespace("http://www.w3.org/ns/dcat#")

log = get_logger(__name__)


def _origin(url: httpx.URL) -> tuple[str, str, int]:
    """The ``(scheme, host, port)`` origin with default ports applied.

    Mirrors the client's egress check exactly (``fdp.client._origin``) so a URL
    the resolver accepts is one the client would also allow — and so the
    comparison is robust to default-port normalisation differences between
    ``httpx.URL`` (port ``None``) and pydantic ``HttpUrl`` (explicit ``:443``).
    """
    default_port = 443 if url.scheme == "https" else 80
    return (url.scheme, url.host or "", url.port or default_port)


def _on_fdp_origin(url: str, settings: FdpMcpSettings) -> bool:
    """Whether ``url`` sits on the target FDP's origin (strict-egress gate)."""
    try:
        target = _origin(httpx.URL(url))
    except httpx.InvalidURL, ValueError:
        return False
    return target == _origin(httpx.URL(str(settings.fdp_base_url)))


def advertised_sparql_endpoint(graph: Graph, root_iri: str) -> str | None:
    """The SPARQL endpoint the root advertises, or ``None``.

    Prefers ``void:sparqlEndpoint``; falls back to a ``dcat:DataService`` whose
    ``dcat:endpointDescription`` identifies the SPARQL protocol.
    """
    root = URIRef(root_iri)
    direct = next(graph.objects(root, VOID.sparqlEndpoint), None)
    if direct is not None:
        return str(direct)
    for service in graph.objects(root, DCAT.service):
        descriptions = {str(d).lower() for d in graph.objects(service, DCAT.endpointDescription)}
        if any("sparql" in d for d in descriptions):
            url = next(graph.objects(service, DCAT.endpointURL), None)
            if url is not None:
                return str(url)
    return None


def advertised_search_endpoint(
    graph: Graph, root_iri: str, *, sparql_endpoint: str | None = None
) -> str | None:
    """The search endpoint the root advertises, or ``None``.

    Heuristic (no standard predicate): the single ``dcat:service``
    ``dcat:DataService`` whose ``dcat:endpointURL`` is not the SPARQL endpoint and
    that does not describe itself as SPARQL. Zero or several such → ``None`` (the
    bridge falls back rather than guess).
    """
    root = URIRef(root_iri)
    candidates: list[str] = []
    for service in graph.objects(root, DCAT.service):
        url = next(graph.objects(service, DCAT.endpointURL), None)
        if url is None:
            continue
        endpoint = str(url)
        if sparql_endpoint is not None and endpoint == sparql_endpoint:
            continue
        descriptions = {str(d).lower() for d in graph.objects(service, DCAT.endpointDescription)}
        if any("sparql" in d for d in descriptions):
            continue
        if endpoint not in candidates:
            candidates.append(endpoint)
    return candidates[0] if len(candidates) == 1 else None


async def _root_graph(
    client: FdpClient, root_graph: Graph | None, root_iri: str | None
) -> tuple[Graph, str] | None:
    """Return ``(graph, subject_iri)`` for the root, fetching it if not supplied.

    A fetch failure yields ``None`` — discovery is best-effort and must never break
    a tool that can still fall back to its configured endpoint.
    """
    if root_graph is not None:
        return root_graph, (root_iri or client.base_url)
    try:
        root = await fetch_root(client)
    except FdpError:
        return None
    return root.graph, root.iri


async def resolve_sparql_endpoint(
    client: FdpClient,
    settings: FdpMcpSettings,
    *,
    root_graph: Graph | None = None,
    root_iri: str | None = None,
) -> str:
    """Resolve the SPARQL endpoint: override → advertised (on-origin) → configured."""
    if not settings.sparql_path_is_default:
        return settings.fdp_sparql_endpoint
    resolved = await _root_graph(client, root_graph, root_iri)
    if resolved is None:
        return settings.fdp_sparql_endpoint
    graph, iri = resolved
    advertised = advertised_sparql_endpoint(graph, iri)
    if advertised is not None and _on_fdp_origin(advertised, settings):
        log.debug("sparql_endpoint_discovered", endpoint=advertised)
        return advertised
    return settings.fdp_sparql_endpoint


async def resolve_search_endpoint(
    client: FdpClient,
    settings: FdpMcpSettings,
    *,
    root_graph: Graph | None = None,
    root_iri: str | None = None,
) -> str:
    """Resolve the search endpoint: override → advertised (on-origin) → configured."""
    if not settings.search_path_is_default:
        return settings.fdp_search_endpoint
    resolved = await _root_graph(client, root_graph, root_iri)
    if resolved is None:
        return settings.fdp_search_endpoint
    graph, iri = resolved
    sparql = advertised_sparql_endpoint(graph, iri)
    advertised = advertised_search_endpoint(graph, iri, sparql_endpoint=sparql)
    if advertised is not None and _on_fdp_origin(advertised, settings):
        log.debug("search_endpoint_discovered", endpoint=advertised)
        return advertised
    return settings.fdp_search_endpoint


__all__ = [
    "advertised_search_endpoint",
    "advertised_sparql_endpoint",
    "resolve_search_endpoint",
    "resolve_sparql_endpoint",
]
