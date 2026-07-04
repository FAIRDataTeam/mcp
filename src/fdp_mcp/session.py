"""Per-session context and the session registry.

A *session* is one MCP client's conversation with the bridge. Its context holds
only what a tool handler needs to talk to the FDP on that client's behalf:

* ``session_id`` — the MCP session identifier (or an ephemeral id for the
  transport handshake, before one is assigned);
* ``fdp_base_url`` — the single target FDP (from settings);
* ``credential`` — the optional bearer the client forwarded, as a ``SecretStr``
  held in memory only. It is never persisted or logged (ADR-0018 §3).

The ``SessionRegistry`` tracks established sessions so the bridge can enforce an
idle timeout, an absolute lifetime, and a concurrency cap — bounding how long a
forwarded credential lives in memory and defending against unbounded growth.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Lock
from typing import cast

from pydantic import SecretStr

# ASGI scope key under which the streamable-HTTP middleware stashes the resolved
# SessionContext; Starlette surfaces ``scope["state"]`` as ``request.state``.
SCOPE_STATE_KEY = "session_context"


@dataclass(frozen=True)
class SessionContext:
    """Immutable context for one session. ``credential`` is memory-only."""

    session_id: str
    fdp_base_url: str
    credential: SecretStr | None = None

    @property
    def is_authenticated(self) -> bool:
        """Whether the client forwarded a bearer credential for this session."""
        return self.credential is not None


def session_context_from_scope(scope: object) -> SessionContext | None:
    """Return the SessionContext attached to an ASGI scope, if any."""
    if isinstance(scope, Mapping):
        state = cast("Mapping[str, object]", scope).get("state")
        if isinstance(state, dict):
            value = cast("dict[str, object]", state).get(SCOPE_STATE_KEY)
            if isinstance(value, SessionContext):
                return value
    return None


def extract_bearer_credential(headers: Mapping[str, str]) -> SecretStr | None:
    """Pull a forwarded bearer token from request headers, if present.

    Returns the token (scheme stripped) as a ``SecretStr``, or ``None`` when
    there is no ``Authorization`` header or it is not a non-empty ``Bearer``
    credential. Header lookup is case-insensitive.
    """
    raw = next((v for k, v in headers.items() if k.lower() == "authorization"), None)
    if not raw:
        return None
    scheme, _, token = raw.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return SecretStr(token.strip())


class SessionLimitError(RuntimeError):
    """Raised when a new session would exceed ``max_sessions``."""


@dataclass
class _Entry:
    context: SessionContext
    created_at: float
    last_seen: float


class SessionRegistry:
    """Tracks established sessions with idle/lifetime eviction and a cap.

    Thread-safe (a ``threading.Lock`` guards the map): the ASGI server may
    dispatch concurrent requests across a threadpool. Expiry is evaluated
    lazily on every access — there is no background sweeper — which is
    sufficient because access is what creates and refreshes entries.
    """

    def __init__(
        self,
        *,
        max_sessions: int,
        idle_timeout_seconds: float,
        lifetime_timeout_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_sessions = max_sessions
        self._idle_timeout = idle_timeout_seconds
        self._lifetime_timeout = lifetime_timeout_seconds
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._lock = Lock()

    def _is_expired(self, entry: _Entry, now: float) -> bool:
        return (
            now - entry.last_seen >= self._idle_timeout
            or now - entry.created_at >= self._lifetime_timeout
        )

    def _purge_expired(self, now: float) -> None:
        expired = [sid for sid, e in self._entries.items() if self._is_expired(e, now)]
        for sid in expired:
            del self._entries[sid]

    def get_or_create(
        self, session_id: str, context_factory: Callable[[], SessionContext]
    ) -> SessionContext:
        """Return the session's context, creating it on first sight.

        Expired sessions are purged first. Creating a new session when the map
        is already at ``max_sessions`` raises ``SessionLimitError``. Seeing
        an existing session refreshes its idle clock.
        """
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            entry = self._entries.get(session_id)
            if entry is not None:
                entry.last_seen = now
                return entry.context
            if len(self._entries) >= self._max_sessions:
                raise SessionLimitError(
                    f"active sessions ({len(self._entries)}) at limit ({self._max_sessions})"
                )
            context = context_factory()
            self._entries[session_id] = _Entry(context=context, created_at=now, last_seen=now)
            return context

    def discard(self, session_id: str) -> None:
        """Forget a session (e.g. on explicit client termination)."""
        with self._lock:
            self._entries.pop(session_id, None)

    def active_count(self) -> int:
        """Number of non-expired sessions currently tracked."""
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            return len(self._entries)
