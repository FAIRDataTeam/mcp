"""Unit tests for the session context and registry (task 0.2)."""

from __future__ import annotations

import pytest

from fdp_mcp.session import (
    SessionContext,
    SessionLimitError,
    SessionRegistry,
    extract_bearer_credential,
)


class FakeClock:
    """A controllable monotonic clock for deterministic expiry tests."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# --- bearer extraction ------------------------------------------------------


def test_extract_bearer_returns_token() -> None:
    cred = extract_bearer_credential({"Authorization": "Bearer abc.123"})
    assert cred is not None
    assert cred.get_secret_value() == "abc.123"


def test_extract_bearer_is_case_insensitive_on_header_and_scheme() -> None:
    cred = extract_bearer_credential({"authorization": "bearer tok"})
    assert cred is not None
    assert cred.get_secret_value() == "tok"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer    "},
    ],
)
def test_extract_bearer_returns_none_without_valid_bearer(headers: dict[str, str]) -> None:
    assert extract_bearer_credential(headers) is None


# --- SessionContext ---------------------------------------------------------


def test_is_authenticated_reflects_credential() -> None:
    anon = SessionContext(session_id="s", fdp_base_url="https://fdp.example.org")
    assert anon.is_authenticated is False

    authed = extract_bearer_credential({"Authorization": "Bearer tok"})
    ctx = SessionContext(session_id="s", fdp_base_url="https://fdp.example.org", credential=authed)
    assert ctx.is_authenticated is True


def test_credential_never_appears_in_repr() -> None:
    cred = extract_bearer_credential({"Authorization": "Bearer super-secret-value"})
    ctx = SessionContext(session_id="s", fdp_base_url="https://fdp.example.org", credential=cred)
    assert "super-secret-value" not in repr(ctx)
    assert "super-secret-value" not in str(ctx)


# --- SessionRegistry --------------------------------------------------------


def _anon(session_id: str) -> SessionContext:
    return SessionContext(session_id=session_id, fdp_base_url="https://fdp.example.org")


def test_get_or_create_creates_then_reuses() -> None:
    registry = SessionRegistry(
        max_sessions=10, idle_timeout_seconds=100, lifetime_timeout_seconds=1000
    )
    first = registry.get_or_create("s1", lambda: _anon("s1"))
    second = registry.get_or_create("s1", lambda: _anon("s1"))
    assert first is second
    assert registry.active_count() == 1


def test_concurrency_cap_rejects_new_session() -> None:
    registry = SessionRegistry(
        max_sessions=2, idle_timeout_seconds=100, lifetime_timeout_seconds=1000
    )
    registry.get_or_create("a", lambda: _anon("a"))
    registry.get_or_create("b", lambda: _anon("b"))
    with pytest.raises(SessionLimitError):
        registry.get_or_create("c", lambda: _anon("c"))
    # An existing session is still served while at the cap.
    assert registry.get_or_create("a", lambda: _anon("a")).session_id == "a"


def test_idle_timeout_evicts_and_frees_a_slot() -> None:
    clock = FakeClock()
    registry = SessionRegistry(
        max_sessions=1, idle_timeout_seconds=10, lifetime_timeout_seconds=1000, clock=clock
    )
    registry.get_or_create("a", lambda: _anon("a"))
    clock.advance(15)  # past idle timeout
    assert registry.active_count() == 0  # "a" purged lazily
    # The freed slot admits a new session.
    assert registry.get_or_create("b", lambda: _anon("b")).session_id == "b"


def test_activity_refreshes_idle_clock() -> None:
    clock = FakeClock()
    registry = SessionRegistry(
        max_sessions=5, idle_timeout_seconds=10, lifetime_timeout_seconds=1000, clock=clock
    )
    registry.get_or_create("a", lambda: _anon("a"))
    clock.advance(8)
    registry.get_or_create("a", lambda: _anon("a"))  # touch → last_seen = 8
    clock.advance(7)  # only 7s since last activity, still alive
    assert registry.active_count() == 1


def test_lifetime_timeout_evicts_even_when_active() -> None:
    clock = FakeClock()
    registry = SessionRegistry(
        max_sessions=5, idle_timeout_seconds=1000, lifetime_timeout_seconds=100, clock=clock
    )
    registry.get_or_create("a", lambda: _anon("a"))
    clock.advance(50)
    registry.get_or_create("a", lambda: _anon("a"))  # recent activity...
    clock.advance(51)  # ...but total lifetime now 101 > 100
    assert registry.active_count() == 0


def test_discard_forgets_session() -> None:
    registry = SessionRegistry(
        max_sessions=5, idle_timeout_seconds=100, lifetime_timeout_seconds=1000
    )
    registry.get_or_create("a", lambda: _anon("a"))
    registry.discard("a")
    assert registry.active_count() == 0
