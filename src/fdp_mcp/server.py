"""MCP server assembly, transports, and per-session context wiring.

Assembles the FastMCP server (official SDK) and runs it on one of two
transports (ADR-0018 §2):

* **streamable-HTTP** (default) — a long-lived network sidecar served by
  uvicorn. A pure-ASGI ``SessionMiddleware`` establishes the per-session
  context (forwarded credential, session id, target FDP) on every request and
  enforces the concurrency cap; it is pure-ASGI rather than
  ``BaseHTTPMiddleware`` because the MCP endpoint streams (SSE) and
  ``BaseHTTPMiddleware`` would buffer it.
* **stdio** — the bridge as a local subprocess of a desktop MCP client. stdio
  carries no HTTP headers, so its session is anonymous (no forwarded
  credential); the FDP's own anonymous authorization applies.

Tool handlers (Phase 2) read the current ``SessionContext`` from
``request.state`` via ``session_context_from_scope`` / the Starlette request the
SDK exposes on ``ctx.request_context.request``.

Session/credential handling honours the ground rules: the credential lives in
memory only, is a ``SecretStr``, and is never logged (see ``log`` redaction).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Literal

import anyio
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from fdp_mcp.config import FdpMcpSettings, LogLevel, get_settings
from fdp_mcp.log import configure_logging, get_logger
from fdp_mcp.session import (
    SCOPE_STATE_KEY,
    SessionContext,
    SessionLimitError,
    SessionRegistry,
    extract_bearer_credential,
    session_context_from_scope,
)
from fdp_mcp.tools.registry import register_read_tools

# Re-exported for callers/tests that resolve it from the server module.
__all__ = ["build_server", "create_app", "main", "run", "session_context_from_scope"]

if TYPE_CHECKING:
    from starlette.applications import Starlette

logger = get_logger(__name__)

SERVER_NAME = "fdp-mcp"
SERVER_INSTRUCTIONS = (
    "Read-only access to the metadata of a FAIR Data Point (FDP): its records, "
    "schemas, licenses, and access conditions. Cite results by IRI; the bridge "
    "never invents holdings and adds no authorization of its own."
)
# The MCP endpoint path on the streamable-HTTP transport.
STREAMABLE_HTTP_PATH = "/mcp"

# FastMCP's log-level literal is upper-case; map from our lower-case setting.
_FASTMCP_LEVEL: dict[LogLevel, Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]] = {
    "debug": "DEBUG",
    "info": "INFO",
    "warning": "WARNING",
    "error": "ERROR",
    "critical": "CRITICAL",
}


def build_server(settings: FdpMcpSettings) -> FastMCP:
    """Construct the FastMCP server (transport-agnostic).

    Registers the liveness route; tools are registered in Phase 2.
    """
    server = FastMCP(
        name=SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        host=settings.host,
        port=settings.port,
        log_level=_FASTMCP_LEVEL[settings.log_level],
        streamable_http_path=STREAMABLE_HTTP_PATH,
        # Stateful: the SDK assigns and tracks an mcp-session-id per client, which
        # our SessionMiddleware keys the session registry on.
        stateless_http=False,
    )

    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # Registered by explicit call (not decorator sugar) so the handler is a
    # referenced local — the endpoint is public and unauthenticated by design.
    server.custom_route("/healthz", methods=["GET"])(healthz)
    register_read_tools(server, settings)
    return server


class SessionMiddleware:
    """Pure-ASGI middleware: establish the per-session context and enforce the cap.

    For every HTTP request it extracts the forwarded bearer (if any), resolves
    the session against the registry, and attaches the resulting
    ``SessionContext`` to ``scope["state"]``. Requests carrying no
    ``mcp-session-id`` (the transport handshake, before the SDK assigns one) get
    an ephemeral context and do **not** occupy a registry slot; the established
    session is counted once the client sends its assigned id. When a new session
    would exceed the cap the request is rejected with ``503`` before reaching the
    MCP app.
    """

    def __init__(
        self, app: ASGIApp, *, settings: FdpMcpSettings, registry: SessionRegistry
    ) -> None:
        self.app = app
        self.settings = settings
        self.registry = registry
        self._fdp_base_url = str(settings.fdp_base_url).rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = _headers_from_scope(scope)
        credential = extract_bearer_credential(headers)
        mcp_session_id = headers.get("mcp-session-id")

        if mcp_session_id is None:
            # Handshake / non-session request: ephemeral context, no slot taken.
            context = SessionContext(
                session_id=f"ephemeral-{uuid.uuid4()}",
                fdp_base_url=self._fdp_base_url,
                credential=credential,
            )
        else:
            try:
                context = self.registry.get_or_create(
                    mcp_session_id,
                    lambda: SessionContext(
                        session_id=mcp_session_id,
                        fdp_base_url=self._fdp_base_url,
                        credential=credential,
                    ),
                )
            except SessionLimitError:
                logger.warning(
                    "session_limit_exceeded",
                    active=self.registry.active_count(),
                    limit=self.settings.max_concurrent_sessions,
                )
                response = JSONResponse(
                    {
                        "error": "session_limit_exceeded",
                        "message": "The bridge is at its concurrent-session limit; retry later.",
                    },
                    status_code=503,
                )
                await response(scope, receive, send)
                return

        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state[SCOPE_STATE_KEY] = context
        # Never log the credential itself — only whether one is present.
        logger.debug(
            "session_request",
            session_id=context.session_id,
            authenticated=context.is_authenticated,
        )
        await self.app(scope, receive, send)


def _headers_from_scope(scope: Scope) -> dict[str, str]:
    """Decode ASGI raw headers into a lower-cased ``dict`` (last value wins)."""
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


def create_app(settings: FdpMcpSettings, *, registry: SessionRegistry | None = None) -> Starlette:
    """Build the streamable-HTTP ASGI application with session handling."""
    server = build_server(settings)
    app = server.streamable_http_app()
    registry = registry or _build_registry(settings)
    app.add_middleware(SessionMiddleware, settings=settings, registry=registry)
    return app


def _build_registry(settings: FdpMcpSettings) -> SessionRegistry:
    return SessionRegistry(
        max_sessions=settings.max_concurrent_sessions,
        idle_timeout_seconds=settings.session_idle_timeout_seconds,
        lifetime_timeout_seconds=settings.session_lifetime_timeout_seconds,
    )


def run(settings: FdpMcpSettings | None = None) -> None:
    """Configure logging and serve the bridge on the configured transport."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    if settings.transport == "stdio":
        _run_stdio(settings)
    else:
        _run_streamable_http(settings)


def _run_stdio(settings: FdpMcpSettings) -> None:
    server = build_server(settings)
    logger.info("starting", transport="stdio", fdp=settings.fdp_origin)
    anyio.run(server.run_stdio_async)


def _run_streamable_http(settings: FdpMcpSettings) -> None:
    import uvicorn

    app = create_app(settings)
    logger.info(
        "starting",
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        fdp=settings.fdp_origin,
    )
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level)


def main() -> None:
    """Console-script entry point for the ``fdp-mcp`` bridge."""
    run()
