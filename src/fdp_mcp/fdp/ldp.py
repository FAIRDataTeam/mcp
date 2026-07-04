"""LDP access and root discovery.

Content-negotiated ``GET`` of records and containers, parsed into an
``LdpResource`` (RDF graph + parsed ``Link`` header + containment), plus:

* **container paging** — ``iter_container_members`` follows ``rel="next"`` and,
  failing that, the FDP's ``X-FDP-Page-*`` offset headers, bounded by a cap;
* **root discovery** — ``discover_root`` fetches the configured base URL, then
  enumerates the resource *kinds* present by a bounded breadth-first walk of the
  containment tree. Kinds are runtime-defined per FDP, so they are discovered,
  never hard-coded (the DCAT five are a common default, not a contract).

Everything here goes through the strict-egress :class:`~fdp_mcp.fdp.client.FdpClient`.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from rdflib import Graph, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, Namespace

from fdp_mcp.fdp.client import DEFAULT_RDF_ACCEPT, FdpClient
from fdp_mcp.fdp.errors import (
    FdpNotFoundError,
    FdpUnauthorizedError,
    FdpUpstreamError,
    raise_for_status,
)
from fdp_mcp.fdp.links import LinkSet
from fdp_mcp.fdp.rdf import parse_graph

LDP = Namespace("http://www.w3.org/ns/ldp#")

# rdf:type IRIs that describe structure/vocabulary rather than a resource kind;
# excluded when deriving kinds from a record's types.
_STRUCTURAL_TYPE_NS = (
    str(LDP),
    str(RDF),
    str(RDFS),
    str(OWL),
)

_TITLE_PREDICATES = (DCTERMS.title, RDFS.label, SKOS.prefLabel)


@dataclass(frozen=True)
class PageInfo:
    """The FDP's ``X-FDP-Page-*`` paging state for a container/page response."""

    offset: int
    limit: int
    total: int | None


@dataclass(frozen=True)
class LdpResource:
    """A fetched LDP record/container: its RDF graph, links, and containment."""

    iri: str
    requested_iri: str
    media_type: str
    text: str
    graph: Graph
    links: LinkSet
    status: int
    page: PageInfo | None

    @property
    def _subject(self) -> URIRef:
        return URIRef(self.iri)

    @property
    def type_iris(self) -> list[str]:
        """All ``rdf:type`` IRIs of the primary subject (sorted, deduped)."""
        return sorted({str(o) for o in self.graph.objects(self._subject, RDF.type)})

    @property
    def kind_type_iris(self) -> list[str]:
        """Subject types that denote a resource kind (structural types dropped)."""
        return [t for t in self.type_iris if not t.startswith(_STRUCTURAL_TYPE_NS)]

    @property
    def is_container(self) -> bool:
        return self.links.is_ldp_container or f"{LDP}Container" in self.type_iris

    @property
    def constrained_by(self) -> str | None:
        """The SHACL shape IRI, from the ``constrainedBy`` link or the graph."""
        from_header = self.links.constrained_by
        if from_header is not None:
            return from_header
        obj = next(self.graph.objects(self._subject, LDP.constrainedBy), None)
        return str(obj) if obj is not None else None

    @property
    def title(self) -> str | None:
        for predicate in _TITLE_PREDICATES:
            obj = next(self.graph.objects(self._subject, predicate), None)
            if obj is not None:
                return str(obj)
        return None

    @property
    def member_iris(self) -> list[str]:
        """Contained members: ``ldp:contains`` unioned with signposted ``item`` links."""
        members = [str(o) for o in self.graph.objects(self._subject, LDP.contains)]
        seen = set(members)
        for target in self.links.items:
            if target not in seen:
                seen.add(target)
                members.append(target)
        return members

    @property
    def parent_iri(self) -> str | None:
        obj = next(self.graph.objects(self._subject, DCTERMS.isPartOf), None)
        if obj is not None:
            return str(obj)
        collections = self.links.collections
        return collections[0] if collections else None


async def fetch_resource(
    client: FdpClient, iri: str, *, accept: str = DEFAULT_RDF_ACCEPT
) -> LdpResource:
    """Content-negotiated GET of one LDP record/container.

    Raises the typed FDP errors (``FdpNotFoundError`` for 404/hidden,
    ``FdpUnauthorizedError`` for 401/403, ``FdpUpstreamError`` for other errors
    or unparseable RDF, plus timeout/too-large/egress from the client).
    """
    doc = await client.get(iri, accept=accept)
    raise_for_status(doc.status, iri=iri)
    graph = parse_graph(doc.text, doc.media_type, public_id=iri)
    subject = _resolve_subject(graph, iri, doc.url)
    return LdpResource(
        iri=subject,
        requested_iri=iri,
        media_type=doc.media_type,
        text=doc.text,
        graph=graph,
        links=doc.links,
        status=doc.status,
        page=_page_info(doc.headers),
    )


def _resolve_subject(graph: Graph, requested: str, response_url: str) -> str:
    """Pick the record's primary subject IRI.

    An FDP may canonicalise the request (trailing slash, PID base), so the
    subject in the graph can differ from the requested URL. Prefer a candidate
    that carries an ``rdf:type``; fall back to any candidate that is a subject,
    then to the requested IRI.
    """
    candidates: list[str] = []
    for raw in (requested, response_url):
        # A page/listing request carries a ?offset= query while its RDF subject
        # is the query-less container IRI, so try the stripped form too.
        core = raw.split("#", 1)[0].split("?", 1)[0]
        for base in (raw, core):
            for variant in (base, base.rstrip("/"), base if base.endswith("/") else base + "/"):
                if variant not in candidates:
                    candidates.append(variant)

    typed = [c for c in candidates if (URIRef(c), RDF.type, None) in graph]
    if typed:
        return typed[0]
    for candidate in candidates:
        if (URIRef(candidate), None, None) in graph:
            return candidate
    return requested.rstrip("/") or requested


def _page_info(headers: httpx.Headers) -> PageInfo | None:
    def _int(name: str) -> int | None:
        value = headers.get(name)
        return int(value) if value is not None and value.lstrip("-").isdigit() else None

    offset, limit, total = (
        _int("x-fdp-page-offset"),
        _int("x-fdp-page-limit"),
        _int("x-fdp-page-total"),
    )
    if offset is None and limit is None and total is None:
        return None
    return PageInfo(offset=offset or 0, limit=limit or 0, total=total)


def _next_page_url(resource: LdpResource, current_url: str) -> str | None:
    """The next page's URL: ``rel="next"`` if present, else ``X-FDP-Page-*`` math."""
    explicit = resource.links.first_target("next")
    if explicit is not None:
        return explicit
    page = resource.page
    if page is not None and page.limit > 0 and page.total is not None:
        next_offset = page.offset + page.limit
        if next_offset < page.total:
            return str(httpx.URL(current_url).copy_set_param("offset", str(next_offset)))
    return None


async def iter_container_members(
    client: FdpClient,
    container_iri: str,
    *,
    max_members: int = 1000,
    accept: str = DEFAULT_RDF_ACCEPT,
) -> AsyncIterator[str]:
    """Yield the member IRIs of a container, following paging, up to ``max_members``.

    Reads inline ``ldp:contains`` membership from each page and follows the next
    page (``rel="next"`` or ``X-FDP-Page-*``) until exhausted or the cap is hit.
    Members are de-duplicated across pages, order preserved.
    """
    seen: set[str] = set()
    yielded = 0
    url: str | None = container_iri
    while url is not None and yielded < max_members:
        resource = await fetch_resource(client, url, accept=accept)
        for member in resource.member_iris:
            if member in seen:
                continue
            seen.add(member)
            yield member
            yielded += 1
            if yielded >= max_members:
                return
        url = _next_page_url(resource, url)


@dataclass(frozen=True)
class Kind:
    """A resource kind discovered at runtime (never hard-coded)."""

    slug: str
    type_iris: tuple[str, ...]
    label: str | None
    is_root: bool
    example_iri: str | None


@dataclass(frozen=True)
class RootDiscovery:
    """The root FDP record plus the kinds reachable from it."""

    root: LdpResource
    kinds: tuple[Kind, ...]
    truncated: bool


def _local_name(iri: str) -> str:
    tail = re.split(r"[#/]", iri.rstrip("/"))[-1]
    return tail or iri


def _slug_for_type(iri: str) -> str:
    name = _local_name(iri)
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", name)
    name = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "-", name)
    return name.lower() or iri


def _register_kind(
    kinds: dict[tuple[str, ...], Kind], resource: LdpResource, *, is_root: bool
) -> None:
    types = tuple(resource.kind_type_iris)
    if not types:
        return
    if types in kinds:
        return
    primary = types[0]
    kinds[types] = Kind(
        slug=_slug_for_type(primary),
        type_iris=types,
        label=_local_name(primary),
        is_root=is_root,
        example_iri=resource.iri,
    )


async def discover_root(client: FdpClient, *, max_fetches: int = 50) -> RootDiscovery:
    """Fetch the root FDP record and enumerate the kinds reachable from it.

    Kinds are derived from the ``rdf:type``s of records found by a bounded
    breadth-first walk of the containment tree (descending only into
    containers). ``max_fetches`` bounds the walk; ``truncated`` reports whether
    the cap was reached before the tree was exhausted.
    """
    root = await fetch_resource(client, client.base_url)
    kinds: dict[tuple[str, ...], Kind] = {}
    _register_kind(kinds, root, is_root=True)

    queue: deque[str] = deque(root.member_iris)
    visited: set[str] = {root.iri, root.requested_iri}
    fetches = 1
    truncated = False

    while queue:
        if fetches >= max_fetches:
            truncated = True
            break
        iri = queue.popleft()
        if iri in visited:
            continue
        visited.add(iri)
        try:
            resource = await fetch_resource(client, iri)
        except (FdpNotFoundError, FdpUnauthorizedError, FdpUpstreamError):
            # A hidden, missing, or malformed member does not abort discovery.
            continue
        fetches += 1
        _register_kind(kinds, resource, is_root=False)
        if resource.is_container:
            queue.extend(m for m in resource.member_iris if m not in visited)

    return RootDiscovery(root=root, kinds=tuple(kinds.values()), truncated=truncated)
