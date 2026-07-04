"""Search access — where the FDP exposes a search API.

Search is not part of the core FDP surface (the Java reference implementation
has none), so it is capability-probed on first use: an absent/disabled endpoint
(HTTP 404/405/406/501) degrades to ``FdpUnsupportedError`` (capability
``search-api``), which the tool layer renders as the contract's ``unsupported``
result. The request/response shape follows FDPneo's ``POST`` search JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import FdpUnsupportedError, FdpUpstreamError, raise_for_status

_JSON_CT = "application/json"

# Statuses that mean "no search surface here" rather than a query error.
_UNSUPPORTED_STATUSES = frozenset({404, 405, 406, 501})

_UNSUPPORTED_ALTERNATIVE = "Use sparql_query or list_records to enumerate records."


@dataclass(frozen=True)
class SearchHit:
    """One search result row, as the FDP search API reports it."""

    record_iri: str
    type_iri: str | None
    title: str | None
    description: str | None
    license: str | None
    state: str | None
    updated_at: str | None


@dataclass(frozen=True)
class SearchResult:
    items: list[SearchHit]
    total: int | None
    facets: dict[str, Any] = field(default_factory=dict[str, Any])


async def run_search(
    client: FdpClient,
    endpoint: str,
    *,
    query: str,
    types: list[str] | None = None,
    license: str | None = None,
    language: str | None = None,
    updated_from: str | None = None,
    updated_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> SearchResult:
    """Run a search, degrading to ``FdpUnsupportedError`` when the API is absent."""
    body: dict[str, Any] = {"query": query, "offset": offset, "limit": limit}
    if types:
        body["types"] = types
    if license is not None:
        body["license"] = license
    if language is not None:
        body["language"] = language
    if updated_from is not None:
        body["from"] = updated_from
    if updated_to is not None:
        body["to"] = updated_to

    doc = await client.post(
        endpoint, content=json.dumps(body), content_type=_JSON_CT, accept=_JSON_CT
    )
    if doc.status in _UNSUPPORTED_STATUSES:
        raise FdpUnsupportedError(
            "search-api",
            f"This FDP exposes no search endpoint at {endpoint} (HTTP {doc.status}).",
            alternative=_UNSUPPORTED_ALTERNATIVE,
        )
    raise_for_status(doc.status, iri=endpoint)

    try:
        payload = json.loads(doc.text)
    except json.JSONDecodeError as exc:
        raise FdpUpstreamError(
            f"search results from {endpoint} were not valid JSON: {exc}"
        ) from exc

    items = [_hit(row) for row in payload.get("items", [])]
    total = payload.get("total")
    return SearchResult(
        items=items,
        total=total if isinstance(total, int) else None,
        facets=payload.get("facets", {}) or {},
    )


def _hit(row: dict[str, Any]) -> SearchHit:
    return SearchHit(
        record_iri=str(row.get("recordIri", "")),
        type_iri=row.get("typeIri"),
        title=row.get("title"),
        description=row.get("description"),
        license=row.get("license"),
        state=row.get("state"),
        updated_at=row.get("updatedAt"),
    )
