"""`list_data_services` — enumerate DCAT DataService records.

Contract: docs/mcp-tool-surface.md §5.8 (required). Discovery only — the bridge
never dispatches to a service. Records are found by a bounded breadth-first walk
of the containment tree (the cross-implementation way to enumerate a type), and
each carries a ``service`` block (endpoint URL/descriptions, served datasets,
conformance claims) — the seed of the capability profile (vision §5).
"""

from __future__ import annotations

from collections import deque
from typing import Any

from rdflib import URIRef
from rdflib.namespace import DCTERMS, Namespace

from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import FdpError
from fdp_mcp.fdp.ldp import LdpResource, fetch_resource
from fdp_mcp.shaping import page_envelope, record_object
from fdp_mcp.tools._common import MEMBER_CAP, clamp_limit

DCAT = Namespace("http://www.w3.org/ns/dcat#")
DATA_SERVICE_TYPE = "http://www.w3.org/ns/dcat#DataService"


async def handle(client: FdpClient, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Enumerate DataService records as a page of Record objects with a service block."""
    limit = clamp_limit(limit)
    offset = max(0, offset)
    services = await _collect_data_services(client, cap=MEMBER_CAP)
    total = len(services)
    items = [_service_item(res) for res in services[offset : offset + limit]]
    return page_envelope(items, limit=limit, offset=offset, total=total)


async def _collect_data_services(client: FdpClient, *, cap: int) -> list[LdpResource]:
    """Breadth-first walk from the root, collecting dcat:DataService records."""
    root = await fetch_resource(client, client.base_url)
    queue: deque[str] = deque(root.member_iris)
    visited: set[str] = {root.iri, root.requested_iri}
    found: list[LdpResource] = []
    fetches = 1
    while queue and fetches < cap:
        iri = queue.popleft()
        if iri in visited:
            continue
        visited.add(iri)
        try:
            resource = await fetch_resource(client, iri)
        except FdpError:
            continue
        fetches += 1
        if DATA_SERVICE_TYPE in resource.type_iris:
            found.append(resource)
        if resource.is_container:
            queue.extend(m for m in resource.member_iris if m not in visited)
    return found


def _service_item(resource: LdpResource) -> dict[str, Any]:
    subject = URIRef(resource.iri)
    graph = resource.graph
    item = record_object(resource, kind="data-service", summary=True)
    endpoint_url = next(graph.objects(subject, DCAT.endpointURL), None)
    item["service"] = {
        "endpoint_url": str(endpoint_url) if endpoint_url is not None else None,
        "endpoint_descriptions": [str(o) for o in graph.objects(subject, DCAT.endpointDescription)],
        "serves_datasets": [str(o) for o in graph.objects(subject, DCAT.servesDataset)],
        "conforms_to": [str(o) for o in graph.objects(subject, DCTERMS.conformsTo)],
    }
    return item
