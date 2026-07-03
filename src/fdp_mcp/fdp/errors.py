"""Typed errors for the FDP client layer.

These map cleanly onto the tool-surface error envelope
(`docs/mcp-tool-surface.md` §3.4) — the tool layer catches them and renders the
corresponding ``code`` — but the client layer stays transport-focused and does
not know about MCP result shapes.
"""

from __future__ import annotations


class FdpError(Exception):
    """Base class for all FDP client-layer failures."""


class EgressError(FdpError):
    """A request targeted a URL outside the configured FDP origin.

    The strict-egress guard (ADR-0018 §3): the bridge speaks only to the target
    FDP. This is raised before any network call, and again on any redirect hop
    that would leave the origin.
    """


class FdpTimeoutError(FdpError):
    """The FDP did not respond within the configured timeout."""


class FdpResponseTooLargeError(FdpError):
    """The FDP response exceeded the configured size cap."""


class FdpNotFoundError(FdpError):
    """The FDP returned 404 — the resource is not visible (absent or hidden).

    Per the contract, 404 is not disambiguated: a draft/policy-hidden record and
    a nonexistent one look the same, deliberately (no existence leak).
    """


class FdpUnauthorizedError(FdpError):
    """The FDP rejected the credential (or required one): 401/403."""


class FdpUpstreamError(FdpError):
    """The FDP returned an unexpected error, or its response was unparseable."""


def raise_for_status(status: int, *, iri: str) -> None:
    """Map an FDP HTTP status onto the client error hierarchy.

    A no-op for 2xx. 3xx is not expected here (the client follows same-origin
    redirects itself), so it is treated as an upstream error if it surfaces.
    """
    if status < 400:
        return
    if status == 404:
        raise FdpNotFoundError(iri)
    if status in (401, 403):
        raise FdpUnauthorizedError(f"{status} for {iri}")
    raise FdpUpstreamError(f"{status} for {iri}")
