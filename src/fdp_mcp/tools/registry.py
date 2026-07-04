"""Register the read tools with a FastMCP server.

Adapts the thin per-tool handlers (which take an ``FdpClient``) to MCP tools:
each call resolves the session (and its forwarded credential) from the request,
opens a per-call egress-guarded client, runs the handler, and maps any
client-layer error onto the contract error / unsupported result. Keeping this in
one place means the handlers stay pure and every tool degrades identically.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import FdpError
from fdp_mcp.session import SessionContext, session_context_from_scope
from fdp_mcp.shaping import result_from_error
from fdp_mcp.tools import fdp_info, get_record, get_schema, list_records
from fdp_mcp.tools._common import Format

Handler = Callable[[FdpClient], Awaitable[dict[str, Any]]]


def _session(ctx: Context[Any, Any, Any], settings: FdpMcpSettings) -> SessionContext:
    """Resolve the SessionContext for this call (anonymous under stdio)."""
    try:
        request = ctx.request_context.request
    except (LookupError, AttributeError):
        request = None
    if request is not None:
        resolved = session_context_from_scope(request.scope)
        if resolved is not None:
            return resolved
    return SessionContext(
        session_id="local",
        fdp_base_url=str(settings.fdp_base_url).rstrip("/"),
        credential=None,
    )


async def _run(
    tool: str, settings: FdpMcpSettings, ctx: Context[Any, Any, Any], handler: Handler
) -> dict[str, Any]:
    session = _session(ctx, settings)
    try:
        async with FdpClient(settings, credential=session.credential) as client:
            return await handler(client)
    except FdpError as exc:
        return result_from_error(tool, exc)


def register_read_tools(server: FastMCP, settings: FdpMcpSettings) -> None:
    """Register fdp_info, list_records, get_record, get_schema on ``server``.

    Tools are registered by explicit call rather than decorator sugar so the
    handler names are referenced (not flagged unused).
    """

    async def fdp_info_tool(
        ctx: Context[Any, Any, Any], format: Format = "jsonld"
    ) -> dict[str, Any]:
        """Describe this FDP: its root record, kinds, and optional endpoints."""
        return await _run(
            "fdp_info", settings, ctx, lambda client: fdp_info.handle(client, settings, fmt=format)
        )

    async def list_records_tool(
        ctx: Context[Any, Any, Any],
        kind: str | None = None,
        parent: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Enumerate records, optionally filtered by kind and/or parent container."""
        return await _run(
            "list_records",
            settings,
            ctx,
            lambda client: list_records.handle(
                client, kind=kind, parent=parent, limit=limit, offset=offset
            ),
        )

    async def get_record_tool(
        ctx: Context[Any, Any, Any], iri: str, format: Format = "jsonld"
    ) -> dict[str, Any]:
        """Full metadata of one record, with signposting links."""
        return await _run(
            "get_record",
            settings,
            ctx,
            lambda client: get_record.handle(client, iri=iri, fmt=format),
        )

    async def get_schema_tool(
        ctx: Context[Any, Any, Any], kind: str, format: Format = "jsonld"
    ) -> dict[str, Any]:
        """The SHACL shape for a kind — what its fields mean and what to expect."""
        return await _run(
            "get_schema",
            settings,
            ctx,
            lambda client: get_schema.handle(client, kind=kind, fmt=format),
        )

    server.tool(name="fdp_info")(fdp_info_tool)
    server.tool(name="list_records")(list_records_tool)
    server.tool(name="get_record")(get_record_tool)
    server.tool(name="get_schema")(get_schema_tool)
