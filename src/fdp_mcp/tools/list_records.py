"""`list_records` — enumerate records by kind and/or parent, paged.

Contract: docs/mcp-tool-surface.md §5.2 (required). Enumerates the direct
members of a container (``parent``, or the root when omitted). A ``kind`` filter
materialises the (bounded) membership and keeps records whose runtime kind slug
matches, so pagination is over the filtered set.
"""

from __future__ import annotations

from typing import Any

from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import FdpNotFoundError, FdpUnauthorizedError
from fdp_mcp.fdp.ldp import LdpResource, fetch_resource, iter_container_members, slug_for_type
from fdp_mcp.shaping import page_envelope, record_object
from fdp_mcp.tools._common import MEMBER_CAP, clamp_limit, kind_slug, validate_iri


async def handle(
    client: FdpClient,
    *,
    kind: str | None = None,
    parent: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Enumerate a container's members as summary Record objects, paged."""
    if parent is not None:
        validate_iri(parent)
    limit = clamp_limit(limit)
    offset = max(0, offset)
    container = parent if parent is not None else client.base_url

    member_iris = [
        m async for m in iter_container_members(client, container, max_members=MEMBER_CAP)
    ]

    if kind is None:
        total = len(member_iris)
        page_iris = member_iris[offset : offset + limit]
        items = [
            record_object(res, kind=kind_slug(res), summary=True)
            for res in await _fetch_all(client, page_iris)
        ]
        return page_envelope(items, limit=limit, offset=offset, total=total)

    # Kind filter: resolve every member's type, keep matches, then paginate.
    matched = [
        res
        for res in await _fetch_all(client, member_iris)
        if kind in {slug_for_type(t) for t in res.kind_type_iris}
    ]
    total = len(matched)
    items = [
        record_object(res, kind=kind, summary=True) for res in matched[offset : offset + limit]
    ]
    return page_envelope(items, limit=limit, offset=offset, total=total)


async def _fetch_all(client: FdpClient, iris: list[str]) -> list[LdpResource]:
    """Fetch each IRI, skipping members hidden or missing for this credential."""
    resources: list[LdpResource] = []
    for iri in iris:
        try:
            resources.append(await fetch_resource(client, iri))
        except (FdpNotFoundError, FdpUnauthorizedError):
            continue
    return resources
