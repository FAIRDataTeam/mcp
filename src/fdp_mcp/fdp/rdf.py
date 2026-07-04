"""Shared RDF parsing for the FDP client layer.

One place that maps FDP response media types onto rdflib parser formats and
turns a response body into a graph, so ``ldp``, ``sparql``, and ``shapes`` parse
consistently and raise the same typed error on malformed RDF.
"""

from __future__ import annotations

from rdflib import Graph

from fdp_mcp.fdp.errors import FdpUpstreamError

# Response media type → rdflib parser format.
MEDIA_TO_RDFLIB: dict[str, str] = {
    "text/turtle": "turtle",
    "application/ld+json": "json-ld",
    "application/rdf+xml": "xml",
    "application/n-triples": "nt",
    "application/n-quads": "nquads",
    "application/trig": "trig",
}


def parse_graph(text: str, media_type: str, *, public_id: str) -> Graph:
    """Parse an RDF body into a graph, resolving relative IRIs against ``public_id``.

    Unknown media types fall back to Turtle (the FDP default). A parse failure
    is surfaced as ``FdpUpstreamError``.
    """
    fmt = MEDIA_TO_RDFLIB.get(media_type, "turtle")
    graph = Graph()
    try:
        graph.parse(data=text, format=fmt, publicID=public_id)
    except Exception as exc:  # rdflib raises a variety of parse errors
        raise FdpUpstreamError(
            f"could not parse {media_type or '?'} from {public_id}: {exc}"
        ) from exc
    return graph
