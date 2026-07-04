"""Shared helpers for the tool handlers: formats, IRI validation, kind slugs."""

from __future__ import annotations

from typing import Literal

from fdp_mcp.fdp.client import DEFAULT_RDF_ACCEPT
from fdp_mcp.fdp.errors import InvalidArgumentError
from fdp_mcp.fdp.ldp import LdpResource, slug_for_type

Format = Literal["jsonld", "turtle", "ntriples", "rdfxml"]

# Which Accept header to send for each requested output format. For JSON-LD the
# bridge frames from the graph, so it negotiates the FDP's preferred RDF; the
# raw formats request that serialization directly.
FORMAT_ACCEPT: dict[str, str] = {
    "jsonld": DEFAULT_RDF_ACCEPT,
    "turtle": "text/turtle",
    "ntriples": "application/n-triples",
    "rdfxml": "application/rdf+xml",
}

# The bounded number of container members the bridge will enumerate for one
# list_records call (kind filtering needs the whole membership).
MEMBER_CAP = 1000


def accept_for(fmt: str) -> str:
    accept = FORMAT_ACCEPT.get(fmt)
    if accept is None:
        raise InvalidArgumentError(f"unsupported format {fmt!r}")
    return accept


def validate_iri(iri: str) -> None:
    if not (iri.startswith("http://") or iri.startswith("https://")):
        raise InvalidArgumentError(f"not an absolute http(s) IRI: {iri!r}")


def clamp_limit(limit: int, *, maximum: int = 200) -> int:
    """Clamp a page size into [1, maximum] (contract: over-max is clamped, not an error)."""
    return max(1, min(limit, maximum))


def kind_slug(resource: LdpResource) -> str | None:
    """The kind slug for a record, from its most specific non-structural type."""
    types = resource.kind_type_iris
    return slug_for_type(types[0]) if types else None
