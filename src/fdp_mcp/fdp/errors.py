"""Typed errors for the FDP client layer.

These map cleanly onto the tool-surface error envelope
(`docs/mcp-tool-surface.md` §3.4) — the tool layer catches them and renders the
corresponding ``code`` — but the client layer stays transport-focused and does
not know about MCP result shapes.
"""

from __future__ import annotations

import json
from typing import Any, cast


class FdpError(Exception):
    """Base class for all FDP client-layer failures.

    ``details`` is an optional, JSON-serialisable object forwarded verbatim into
    the error envelope's ``details`` (e.g. the FDP's SHACL violation report).
    """

    def __init__(self, message: str = "", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details


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


class FdpPreconditionError(FdpError):
    """The FDP refused a conditional write: ``If-Match`` missing (428) or stale (412)."""


class FdpConflictError(FdpError):
    """The FDP reported a conflict (409): slug taken, invalid state transition."""


class FdpValidationError(FdpError):
    """The FDP rejected a write body as invalid (422, typically a SHACL report).

    ``details`` carries the FDP's own ``details`` object (shape, violations)
    verbatim so an agent can repair the body.
    """


class FdpUnsupportedMediaTypeError(FdpError):
    """The FDP does not accept the write body's media type (415)."""


class AuthenticationRequiredError(FdpError):
    """A write was requested on an anonymous session.

    Raised by the bridge *before any network call*. This is a fail-fast, not an
    authorization decision: a write cannot succeed without a credential for the
    FDP to evaluate, so the bridge refuses to spend a round trip. Every
    authenticated call is forwarded and the FDP alone decides (ADR-0024).
    """


class InvalidArgumentError(FdpError):
    """A tool parameter failed validation (bad IRI, unknown kind, out-of-range)."""


class ReadOnlyError(FdpError):
    """A write/update was requested on the read-only surface (e.g. SPARQL update)."""


class InvalidQueryError(FdpError):
    """A query failed validation before any network call (bad SPARQL, SERVICE)."""


class FdpUnsupportedError(FdpError):
    """An optional capability is absent on this FDP; the tool degrades explicitly.

    Carries the machine-readable ``capability`` name (and an optional
    ``alternative``) that the tool layer renders into the contract's
    ``unsupported`` result (``docs/mcp-tool-surface.md`` §3.5).
    """

    def __init__(self, capability: str, reason: str, *, alternative: str | None = None) -> None:
        super().__init__(reason)
        self.capability = capability
        self.reason = reason
        self.alternative = alternative


_WRITE_STATUS_ERRORS: dict[int, type[FdpError]] = {
    409: FdpConflictError,
    412: FdpPreconditionError,
    415: FdpUnsupportedMediaTypeError,
    422: FdpValidationError,
    428: FdpPreconditionError,
}


def parse_error_body(text: str, media_type: str) -> tuple[str | None, dict[str, Any] | None]:
    """Extract ``(message, details)`` from an FDP JSON error envelope, if any.

    FDPneo (and the Java RI) answer errors with ``{code, message, details}``;
    non-JSON or malformed bodies yield ``(None, None)``. Never raises.
    """
    if not media_type.endswith("json") or not text:
        return None, None
    try:
        payload = json.loads(text)
    except ValueError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    data = cast("dict[str, Any]", payload)
    message = data.get("message")
    details = data.get("details")
    return (
        message if isinstance(message, str) else None,
        cast("dict[str, Any]", details) if isinstance(details, dict) else None,
    )


def raise_for_status(status: int, *, iri: str, body: str = "", media_type: str = "") -> None:
    """Map an FDP HTTP status onto the client error hierarchy.

    A no-op for 2xx. 3xx is not expected here (the client follows same-origin
    redirects itself), so it is treated as an upstream error if it surfaces.
    Write-specific statuses (409/412/415/422/428) become their typed errors and
    carry the FDP's JSON ``message``/``details`` when the body provides them.
    """
    if status < 400:
        return
    if status == 404:
        raise FdpNotFoundError(iri)
    if status in (401, 403):
        raise FdpUnauthorizedError(f"{status} for {iri}")
    error_type = _WRITE_STATUS_ERRORS.get(status)
    if error_type is not None:
        message, details = parse_error_body(body, media_type)
        raise error_type(
            f"{status} for {iri}: {message}" if message else f"{status} for {iri}", details=details
        )
    raise FdpUpstreamError(f"{status} for {iri}")
