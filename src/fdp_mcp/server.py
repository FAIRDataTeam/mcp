"""MCP server assembly, transports, and per-session context.

Assembles the MCP server (official SDK), wires the streamable-HTTP transport
(ASGI/uvicorn, the default) and the stdio transport (behind the ``transport``
setting), and establishes the per-session context that carries the optional
forwarded bearer credential (memory only — never logged), the session id, and
the target FDP base URL.

Implemented in task 0.2; this module currently only exposes the ``main`` entry
point so the ``fdp-mcp`` console script resolves.
"""

from __future__ import annotations


def main() -> None:
    """Console-script entry point for the ``fdp-mcp`` bridge.

    Implemented in task 0.2 (MCP server assembly and transports).
    """
    raise NotImplementedError("fdp-mcp server assembly lands in task 0.2")
