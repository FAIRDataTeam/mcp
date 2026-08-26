"""Register the opt-in write tools with a FastMCP server (ADR-0024).

Only called when ``FDP_MCP_ENABLE_WRITE`` is true. Each tool runs through the
same ``_run`` adapter as the read tools, with ``require_credential=True``: an
anonymous session is answered ``authentication_required`` before any network
call. That is a fail-fast (a write cannot succeed without a credential for the
FDP to evaluate), not an authorization decision — every authenticated call is
forwarded verbatim and the FDP alone allows or denies it.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.write import RecordState, WriteMediaType
from fdp_mcp.tools import create_record, delete_record, set_record_state, update_record
from fdp_mcp.tools.registry import _run

WRITE_TOOL_NAMES = frozenset(
    {"create_record", "update_record", "delete_record", "set_record_state"}
)


def register_write_tools(server: FastMCP, settings: FdpMcpSettings) -> None:
    """Register create_record, update_record, delete_record, set_record_state."""

    async def create_record_tool(
        ctx: Context[Any, Any, Any],
        parent_iri: str,
        body: str,
        media_type: WriteMediaType = "text/turtle",
        slug: str | None = None,
    ) -> dict[str, Any]:
        """Create a record inside a container (LDP POST); requires a credential.

        `body` is RDF in `media_type` describing exactly one primary subject
        (use `<>` for the new record). The FDP validates it against the
        container's member shape (see get_schema) and answers
        `validation_failed` with the violations if it does not conform. New
        records typically start as DRAFT; publish with set_record_state.
        """
        return await _run(
            "create_record",
            settings,
            ctx,
            lambda client: create_record.handle(
                client,
                settings,
                parent_iri=parent_iri,
                body=body,
                media_type=media_type,
                slug=slug,
            ),
            require_credential=True,
        )

    async def update_record_tool(
        ctx: Context[Any, Any, Any],
        iri: str,
        if_match: str,
        body: str | None = None,
        media_type: WriteMediaType = "text/turtle",
        patch: str | None = None,
    ) -> dict[str, Any]:
        """Replace (body) or patch (SPARQL update) one record; requires a credential.

        `if_match` must be the `etag` returned by get_record for the version you
        read — a stale one is `precondition_failed`, so re-read and retry.
        Provide exactly one of `body` (full replacement, portable) or `patch`
        (`application/sparql-update`; optional capability, may be `unsupported`).
        """
        return await _run(
            "update_record",
            settings,
            ctx,
            lambda client: update_record.handle(
                client,
                settings,
                iri=iri,
                if_match=if_match,
                body=body,
                media_type=media_type,
                patch=patch,
            ),
            require_credential=True,
        )

    async def delete_record_tool(
        ctx: Context[Any, Any, Any], iri: str, if_match: str
    ) -> dict[str, Any]:
        """Delete one record (LDP DELETE); requires a credential and the current etag."""
        return await _run(
            "delete_record",
            settings,
            ctx,
            lambda client: delete_record.handle(client, iri=iri, if_match=if_match),
            require_credential=True,
        )

    async def set_record_state_tool(
        ctx: Context[Any, Any, Any], iri: str, to: RecordState
    ) -> dict[str, Any]:
        """Move a record to DRAFT, PUBLISHED, or ARCHIVED; requires a credential.

        The FDP decides which transitions are allowed for you (a refused one is
        `conflict`, with the transitions it advertises in `details`). Optional
        capability: an FDP without a transition endpoint yields `unsupported`.
        """
        return await _run(
            "set_record_state",
            settings,
            ctx,
            lambda client: set_record_state.handle(client, iri=iri, to=to),
            require_credential=True,
        )

    server.tool(name="create_record")(create_record_tool)
    server.tool(name="update_record")(update_record_tool)
    server.tool(name="delete_record")(delete_record_tool)
    server.tool(name="set_record_state")(set_record_state_tool)
