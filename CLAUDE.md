# Claude Code context — fdp-mcp

This file is read automatically by Claude Code on every session. It establishes
the project context and conventions so each session starts informed.

## What this project is

`fdp-mcp` — a standalone MCP (Model Context Protocol) sidecar that exposes the
metadata of **any spec-compliant FAIR Data Point** to AI agents through a
read-only tool surface (plus an opt-in write extension, ADR-0024). It is the reference implementation of the tool
contract in `docs/mcp-tool-surface.md`, and the first increment of the agent
consumption programme.

This repo lives beside `../server` (FDPneo server) and `../client`
(fdp-client). It is deployed separately (own Docker image, own release
cycle) and must never assume it is talking to FDPneo specifically.

## Read these first

1. [`../server/docs/adr/0018-agent-consumption-mcp-server.md`](../server/docs/adr/0018-agent-consumption-mcp-server.md)
   — the binding placement/design decisions (sidecar, stack, credential
   pass-through, API-honesty rule). Do not improvise around them.
2. [`../server/docs/architecture/agent-consumption-vision.md`](../server/docs/architecture/agent-consumption-vision.md)
   — motivation, demo strategy, phased increments.
3. [`docs/mcp-tool-surface.md`](docs/mcp-tool-surface.md) — the tool contract
   (once written, task 1.1). The spec, not this code, is the contract.

## Ground rules (not negotiable without an ADR update)

- **Public surface only.** The bridge consumes exclusively the public,
  documented FDP surface: LDP containers/records via content-negotiated GET,
  the `/sparql` endpoint, the search API, published SHACL shapes. Never call
  an FDPneo-private endpoint. If a tool needs something the public surface
  cannot provide, record the gap in `docs/fdp-api-gaps.md` and degrade the
  tool explicitly — the gap report is a deliverable (ADR-0018 §4).
- **No authorization logic in the bridge.** The target FDP is the sole
  decision point. Anonymous by default; a client-supplied API key is forwarded
  verbatim on that session's requests. Credentials are never stored, cached,
  or logged.
- **Strict egress allowlist.** Outbound HTTP goes to `FDP_BASE_URL` and
  nowhere else. No dereferencing of arbitrary IRIs from metadata.
- **Read-only by default.** The four write tools (`create_record`,
  `update_record`, `delete_record`, `set_record_state`; ADR-0024) exist only
  behind `FDP_MCP_ENABLE_WRITE=true` and refuse anonymous sessions before any
  network call. They forward the session credential verbatim and the FDP alone
  decides — still no authorization logic in the bridge. `sparql_query` never
  carries an update form — reject before sending; PATCH updates are validated
  client-side (no `LOAD`/`SERVICE`, no off-origin graphs).
- **Thin adapter.** Tool handlers translate, paginate, and shape results; they
  contain no business logic and no caching of record content beyond
  per-session memoization.

## Stack and conventions

Python 3.12+, official `mcp` SDK (streamable-HTTP + stdio transports),
`httpx` (async) for the FDP client layer, `rdflib` for RDF. Tooling matches
the server repo exactly: `uv` for environments/locking, `ruff` (lint+format),
`pyright` strict, `pytest` (+ `respx` for mocking the FDP in unit tests).
Quality gate for every task: `ruff` clean, `pyright` 0 errors, tests green.

Layout (established by task 0.1):

```
src/fdp_mcp/
  config.py        # pydantic-settings; FDP_BASE_URL is the only required one
  server.py        # MCP server assembly, transports, session context
  fdp/             # FDP client layer: LDP, sparql, search, shapes (httpx)
  tools/           # one module per tool; thin handlers over fdp/
  shaping.py       # JSON-LD framing, pagination, error envelope
docs/
  mcp-tool-surface.md   # the implementation-agnostic tool contract
  fdp-api-gaps.md       # the API-honesty gap report (living document)
tests/
  unit/            # respx-mocked FDP
  integration/     # against a live FDPneo container (testcontainers)
  conformance/     # results validate against the tool-surface spec
```

## Working agreements

- Tasks live in `TASKS.md`, phased and status-marked like the server repo's.
  Done = code merged, tests passing, public surface documented.
- Cross-implementation compatibility is tested deliberately: unit fixtures
  include response shapes from both FDPneo and the Java reference
  implementation where they differ; differences worth spec attention go in
  the gap report.
- Coordinate with `../server` when a gap-report item is triaged into the
  server roadmap (server `TASKS.md` Phase 19) — link the items both ways.
