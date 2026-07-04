# fdp-mcp — MCP bridge for FAIR Data Points

A standalone [Model Context Protocol](https://modelcontextprotocol.io) server
that makes **any spec-compliant FAIR Data Point** consumable by AI agents.
Point it at an FDP, connect an MCP client (Claude, or any other), and converse
with the repository's metadata — datasets, schemas, licenses, access
conditions — grounded in real records, cited by IRI.

```
docker run -e FDP_BASE_URL=https://fdp.example.org ghcr.io/fairdatateam/fdp-mcp
```

- Works against FDPneo **and** the Java reference implementation — it consumes
  only the public, specified FDP surface (LDP, `/sparql`, search, SHACL
  shapes). No server-side changes required.
- Read-only in v1. The bridge adds no authorization of its own: anonymous by
  default, or it forwards your FDP API key per session (never stored, never
  logged).
- The tool contract is implementation-agnostic and published in
  [`docs/mcp-tool-surface.md`](docs/mcp-tool-surface.md); this codebase is its
  reference implementation.

## Why this exists

The FDP ecosystem solved metadata *provisioning*; this bridge is the first
increment of the *consumption* layer — see the
[Agent Consumption Vision](../server/docs/architecture/agent-consumption-vision.md)
and [ADR-0018](../server/docs/adr/0018-agent-consumption-mcp-server.md) in the
server repo for the strategy and the placement decision.

A deliberate side effect: the bridge may only use the public FDP surface, so
every capability it cannot implement cleanly is a documented public-API gap —
tracked in [`docs/fdp-api-gaps.md`](docs/fdp-api-gaps.md) and fed back into
the server roadmap.

## Getting started

See [`docs/agent-quickstart.md`](docs/agent-quickstart.md) for one-command
bring-up, MCP client configuration (Claude and generic clients), and the
scripted three-minute demo.

```bash
docker run --rm -p 8080:8000 \
  -e FDP_BASE_URL=https://your-fdp.example.org \
  ghcr.io/fairdatateam/fdp-mcp:latest
```

## Status

v0.1.0 — the full read-only tool surface (eight tools), the
implementation-agnostic contract, and unit/conformance/integration suites are in
place. `CHANGELOG.md` records the release; `TASKS.md` holds the phased build
plan; `CLAUDE.md` holds the conventions and ground rules for contributors and
coding agents. The image publishes to GHCR from CI on push to `main`.

## License

Apache-2.0 (matching the FDP server).
