"""RFC 8288 ``Link`` header parsing, preserving multiplicity.

``httpx.Response.links`` collapses links by ``rel`` (last wins), which loses the
repeated ``type`` and ``item`` relations an FDP emits. This module parses the raw
header into an ordered list that keeps every link, and exposes a ``LinkSet`` with
accessors for the LDP + FAIR-Signposting relations the tool surface needs
(``constrainedBy``, ``cite-as``, ``describedby``, ``type``, ``license``,
``author``, ``item``, ``collection``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Relation names / IRIs the bridge cares about.
REL_CONSTRAINED_BY = "http://www.w3.org/ns/ldp#constrainedBy"
REL_TYPE = "type"
REL_CITE_AS = "cite-as"
REL_DESCRIBED_BY = "describedby"
REL_LICENSE = "license"
REL_AUTHOR = "author"
REL_ITEM = "item"
REL_COLLECTION = "collection"

_LDP_NS = "http://www.w3.org/ns/ldp#"

# Every LDP container type is a container. FDPneo types its containers
# `ldp:DirectContainer` (not the bare `ldp:Container`), so checking only for
# `ldp:Container` would miss them — recognise the whole family.
LDP_CONTAINER_TYPES = frozenset(
    {
        f"{_LDP_NS}Container",
        f"{_LDP_NS}BasicContainer",
        f"{_LDP_NS}DirectContainer",
        f"{_LDP_NS}IndirectContainer",
    }
)


@dataclass(frozen=True)
class Link:
    """One RFC 8288 link: a target IRI, its ``rel`` tokens, and its parameters."""

    target: str
    rels: tuple[str, ...]
    params: dict[str, str] = field(default_factory=dict[str, str])


def _split_top(text: str, sep: str) -> list[str]:
    """Split ``text`` on ``sep`` at the top level only.

    Commas/semicolons inside ``<...>`` or a double-quoted string do not split —
    RFC 8288 allows both a comma between links and a comma inside a quoted
    parameter value.
    """
    parts: list[str] = []
    buf: list[str] = []
    in_angle = False
    in_quote = False
    for ch in text:
        if ch == '"' and not in_angle:
            in_quote = not in_quote
            buf.append(ch)
        elif ch == "<" and not in_quote:
            in_angle = True
            buf.append(ch)
        elif ch == ">" and not in_quote:
            in_angle = False
            buf.append(ch)
        elif ch == sep and not in_angle and not in_quote:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _parse_params(text: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for chunk in _split_top(text, ";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        if key and key not in params:
            params[key] = value
    return params


def parse_link_header(value: str | None) -> list[Link]:
    """Parse a raw ``Link`` header value into an ordered list of links."""
    if not value:
        return []
    links: list[Link] = []
    for field_text in _split_top(value, ","):
        field_text = field_text.strip()
        start = field_text.find("<")
        end = field_text.find(">", start + 1)
        if start != 0 or end == -1:
            continue
        target = field_text[start + 1 : end]
        params = _parse_params(field_text[end + 1 :])
        rel = params.get("rel", "")
        rels = tuple(rel.split()) if rel else ()
        links.append(Link(target=target, rels=rels, params=params))
    return links


@dataclass(frozen=True)
class LinkSet:
    """An ordered set of parsed links with relation-aware accessors."""

    links: tuple[Link, ...] = ()

    @classmethod
    def from_header(cls, value: str | None) -> LinkSet:
        return cls(tuple(parse_link_header(value)))

    def with_rel(self, rel: str) -> list[Link]:
        return [link for link in self.links if rel in link.rels]

    def targets(self, rel: str) -> list[str]:
        return [link.target for link in self.with_rel(rel)]

    def first_target(self, rel: str) -> str | None:
        links = self.with_rel(rel)
        return links[0].target if links else None

    # --- Named relations the tool surface consumes -------------------------

    @property
    def constrained_by(self) -> str | None:
        return self.first_target(REL_CONSTRAINED_BY)

    @property
    def cite_as(self) -> str | None:
        return self.first_target(REL_CITE_AS)

    @property
    def license(self) -> str | None:
        return self.first_target(REL_LICENSE)

    @property
    def authors(self) -> list[str]:
        return self.targets(REL_AUTHOR)

    @property
    def items(self) -> list[str]:
        return self.targets(REL_ITEM)

    @property
    def collections(self) -> list[str]:
        return self.targets(REL_COLLECTION)

    @property
    def described_by(self) -> list[dict[str, str]]:
        """``describedby`` links as ``{"href", "type"}`` (type may be empty)."""
        return [
            {"href": link.target, "type": link.params.get("type", "")}
            for link in self.with_rel(REL_DESCRIBED_BY)
        ]

    @property
    def ldp_type_iris(self) -> list[str]:
        """``rel="type"`` targets in the LDP namespace (interaction model)."""
        return [t for t in self.targets(REL_TYPE) if t.startswith(_LDP_NS)]

    @property
    def rdf_type_iris(self) -> list[str]:
        """``rel="type"`` targets outside the LDP namespace (signposted rdf:types)."""
        return [t for t in self.targets(REL_TYPE) if not t.startswith(_LDP_NS)]

    @property
    def is_ldp_container(self) -> bool:
        return any(t in LDP_CONTAINER_TYPES for t in self.targets(REL_TYPE))
