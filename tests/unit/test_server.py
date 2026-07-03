"""Unit tests for server assembly, transports, and session middleware (task 0.2)."""

from __future__ import annotations

from typing import Any

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.types import Message, Receive, Scope, Send

import fdp_mcp.server as server_module
from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.server import (
    SessionMiddleware,
    build_server,
    create_app,
    run,
    session_context_from_scope,
)
from fdp_mcp.session import SessionContext, SessionRegistry


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> FdpMcpSettings:
    monkeypatch.setenv("FDP_BASE_URL", "https://fdp.example.org")
    return FdpMcpSettings()  # type: ignore[call-arg]  # filled from env


def _http_scope(headers: list[tuple[bytes, bytes]]) -> Scope:
    return {"type": "http", "method": "POST", "path": "/mcp", "headers": headers}


async def _receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


def _sink() -> tuple[list[Message], Send]:
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    return messages, send


def _fresh_registry() -> SessionRegistry:
    return SessionRegistry(max_sessions=10, idle_timeout_seconds=100, lifetime_timeout_seconds=1000)


# --- assembly ---------------------------------------------------------------


def test_build_server_registers_health_route(settings: FdpMcpSettings) -> None:
    server = build_server(settings)
    paths = {route.path for route in server._custom_starlette_routes}
    assert "/healthz" in paths


def test_create_app_exposes_mcp_and_health_routes(settings: FdpMcpSettings) -> None:
    app = create_app(settings)
    assert isinstance(app, Starlette)
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/mcp" in paths
    assert "/healthz" in paths


# --- session middleware -----------------------------------------------------


async def test_middleware_attaches_context_with_forwarded_bearer(
    settings: FdpMcpSettings,
) -> None:
    registry = _fresh_registry()
    captured: dict[str, SessionContext | None] = {}

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        captured["ctx"] = session_context_from_scope(scope)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = SessionMiddleware(downstream, settings=settings, registry=registry)
    scope = _http_scope([(b"authorization", b"Bearer secret-tok"), (b"mcp-session-id", b"S1")])
    _, send = _sink()
    await mw(scope, _receive, send)

    ctx = captured["ctx"]
    assert ctx is not None
    assert ctx.session_id == "S1"
    assert ctx.fdp_base_url == "https://fdp.example.org"
    assert ctx.is_authenticated
    assert ctx.credential is not None
    assert ctx.credential.get_secret_value() == "secret-tok"
    assert registry.active_count() == 1


async def test_middleware_anonymous_session_has_no_credential(
    settings: FdpMcpSettings,
) -> None:
    registry = _fresh_registry()
    captured: dict[str, SessionContext | None] = {}

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        captured["ctx"] = session_context_from_scope(scope)

    mw = SessionMiddleware(downstream, settings=settings, registry=registry)
    scope = _http_scope([(b"mcp-session-id", b"S2")])
    _, send = _sink()
    await mw(scope, _receive, send)

    ctx = captured["ctx"]
    assert ctx is not None
    assert ctx.session_id == "S2"
    assert ctx.is_authenticated is False
    assert ctx.credential is None


async def test_handshake_request_is_ephemeral_and_takes_no_slot(
    settings: FdpMcpSettings,
) -> None:
    registry = _fresh_registry()
    captured: dict[str, SessionContext | None] = {}

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        captured["ctx"] = session_context_from_scope(scope)

    mw = SessionMiddleware(downstream, settings=settings, registry=registry)
    scope = _http_scope([(b"authorization", b"Bearer tok")])  # no mcp-session-id
    _, send = _sink()
    await mw(scope, _receive, send)

    ctx = captured["ctx"]
    assert ctx is not None
    assert ctx.session_id.startswith("ephemeral-")
    assert ctx.is_authenticated  # credential still available to the handshake
    assert registry.active_count() == 0  # but no registry slot consumed


async def test_middleware_rejects_over_concurrency_cap(settings: FdpMcpSettings) -> None:
    registry = SessionRegistry(
        max_sessions=1, idle_timeout_seconds=100, lifetime_timeout_seconds=1000
    )
    registry.get_or_create(
        "existing",
        lambda: SessionContext(session_id="existing", fdp_base_url="https://fdp.example.org"),
    )

    downstream_called = False

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal downstream_called
        downstream_called = True

    mw = SessionMiddleware(downstream, settings=settings, registry=registry)
    scope = _http_scope([(b"mcp-session-id", b"NEW")])
    messages, send = _sink()
    await mw(scope, _receive, send)

    assert downstream_called is False
    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 503


async def test_middleware_passes_through_non_http_scopes(settings: FdpMcpSettings) -> None:
    reached = False

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal reached
        reached = True

    mw = SessionMiddleware(downstream, settings=settings, registry=_fresh_registry())
    await mw({"type": "lifespan"}, _receive, (_sink()[1]))
    assert reached is True


# --- transport dispatch -----------------------------------------------------


def test_run_dispatches_to_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDP_BASE_URL", "https://fdp.example.org")
    monkeypatch.setenv("FDP_MCP_TRANSPORT", "stdio")
    settings = FdpMcpSettings()  # type: ignore[call-arg]

    calls: dict[str, object] = {}

    def fake_anyio_run(func: Any, *args: Any, **kwargs: Any) -> object:
        calls["stdio"] = func
        return None

    monkeypatch.setattr(server_module.anyio, "run", fake_anyio_run)

    run(settings)
    assert "stdio" in calls


def test_run_dispatches_to_streamable_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDP_BASE_URL", "https://fdp.example.org")
    settings = FdpMcpSettings()  # type: ignore[call-arg]  # transport defaults to streamable-http

    calls: dict[str, dict[str, Any]] = {}

    def fake_uvicorn_run(app: Any, **kwargs: Any) -> None:
        calls["http"] = kwargs

    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)

    run(settings)
    assert "http" in calls
    assert calls["http"]["host"] == "127.0.0.1"
    assert calls["http"]["port"] == 8000
