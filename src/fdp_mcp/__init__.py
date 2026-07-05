"""fdp-mcp — an MCP sidecar over the public surface of a FAIR Data Point.

A standalone Model Context Protocol server that exposes the metadata of any
spec-compliant FAIR Data Point to AI agents through a read-only tool surface.
It consumes only the public, documented FDP surface (LDP, ``/sparql``, search,
SHACL shapes) and holds no authorization logic of its own — see ``CLAUDE.md``
for the binding ground rules and ADR-0018 for the design decisions.
"""

from __future__ import annotations

__version__ = "0.1.1"
