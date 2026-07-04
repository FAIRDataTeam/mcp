"""`get_access_conditions` — "may I use this data, and whom do I ask?"

Contract: docs/mcp-tool-surface.md §5.7 (required). Resolves a record's
``dct:license``, ``dct:rights`` (ODRL Offer references), ``dct:accessRights``,
and contact points into the contract JSON. A referenced policy/license document
is enriched only when it lives on the FDP's own origin — the egress guard makes
an off-origin dereference fail, which we treat as "report the IRI only" (strict
egress; no external lookups, so ``license.open`` is best-effort from the IRI).
"""

from __future__ import annotations

from typing import Any

from rdflib import Literal, URIRef
from rdflib.namespace import DCTERMS, RDFS, SKOS, Namespace

from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import FdpError
from fdp_mcp.fdp.ldp import LdpResource, fetch_resource
from fdp_mcp.shaping import frame_record
from fdp_mcp.tools._common import validate_iri

DCAT = Namespace("http://www.w3.org/ns/dcat#")
VCARD = Namespace("http://www.w3.org/2006/vcard/ns#")

# IRI fragments of licenses that are unambiguously open; anything else is
# reported with ``open: null`` (openness is not judged without a lookup).
_OPEN_LICENSE_MARKERS = (
    "creativecommons.org/licenses/by/",
    "creativecommons.org/licenses/by-sa/",
    "creativecommons.org/publicdomain/zero/",
    "creativecommons.org/publicdomain/mark/",
    "opendatacommons.org/licenses/pddl/",
    "opendatacommons.org/licenses/by/",
)

_LABEL_PREDICATES = (DCTERMS.title, RDFS.label, SKOS.prefLabel)


async def handle(client: FdpClient, *, iri: str) -> dict[str, Any]:
    """Resolve a record's access conditions into the contract shape."""
    validate_iri(iri)
    record = await fetch_resource(client, iri)
    subject = URIRef(record.iri)
    graph = record.graph

    license_block = _license(record)
    rights: list[dict[str, Any]] = []
    policies: list[dict[str, Any]] = []
    for obj in graph.objects(subject, DCTERMS.rights):
        if isinstance(obj, URIRef):
            policies.append(await _policy(client, str(obj)))
        elif isinstance(obj, Literal):
            rights.append({"iri": None, "label": str(obj)})

    access_rights = _term_with_label(record, DCTERMS.accessRights)
    contacts = _contacts(record)

    determinable = any(
        (license_block is not None, rights, policies, access_rights is not None, contacts)
    )
    return {
        "iri": record.iri,
        "license": license_block,
        "rights": rights,
        "access_rights": access_rights,
        "policies": policies,
        "contacts": contacts,
        "determinable": determinable,
    }


def _label_for(record: LdpResource, subject: URIRef) -> str | None:
    for predicate in _LABEL_PREDICATES:
        value = next(record.graph.objects(subject, predicate), None)
        if value is not None:
            return str(value)
    return None


def _license(record: LdpResource) -> dict[str, Any] | None:
    obj = next(record.graph.objects(URIRef(record.iri), DCTERMS.license), None)
    if obj is None:
        return None
    iri = str(obj)
    open_flag: bool | None = True if any(m in iri for m in _OPEN_LICENSE_MARKERS) else None
    label = _label_for(record, obj) if isinstance(obj, URIRef) else None
    return {"iri": iri, "label": label, "open": open_flag}


def _term_with_label(record: LdpResource, predicate: URIRef) -> dict[str, Any] | None:
    obj = next(record.graph.objects(URIRef(record.iri), predicate), None)
    if obj is None:
        return None
    if isinstance(obj, URIRef):
        return {"iri": str(obj), "label": _label_for(record, obj)}
    return {"iri": None, "label": str(obj)}


async def _policy(client: FdpClient, iri: str) -> dict[str, Any]:
    """A policy/Offer reference, enriched from its document when on-origin."""
    entry: dict[str, Any] = {"iri": iri, "type": None, "summary": None}
    try:
        policy = await fetch_resource(client, iri)
    except FdpError:
        # Off-origin (egress guard) or unfetchable — report the IRI only.
        return entry
    types = policy.kind_type_iris or policy.type_iris
    entry["type"] = types[0] if types else None
    entry["summary"] = policy.title
    entry["metadata"] = frame_record(policy.graph, policy.iri)
    return entry


def _contacts(record: LdpResource) -> list[dict[str, Any]]:
    contacts: list[dict[str, Any]] = []
    for obj in record.graph.objects(URIRef(record.iri), DCAT.contactPoint):
        name = next(record.graph.objects(obj, VCARD.fn), None)  # type: ignore[arg-type]
        email = next(record.graph.objects(obj, VCARD.hasEmail), None)  # type: ignore[arg-type]
        contacts.append(
            {
                "name": str(name) if name is not None else None,
                "email": str(email) if email is not None else None,
                "iri": str(obj) if isinstance(obj, URIRef) else None,
            }
        )
    return contacts
