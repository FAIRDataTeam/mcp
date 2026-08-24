# fdp-mcp — MCP bridge for FAIR Data Points

A standalone [Model Context Protocol](https://modelcontextprotocol.io) (MCP)
server that makes **any spec-compliant FAIR Data Point (FDP)** consumable by AI
agents. Point it at an FDP, connect an MCP client (Claude, or any other), and
converse with the repository's metadata — datasets, schemas, licenses, access
conditions — grounded in real records and cited by IRI.

```bash
docker run --rm -p 8080:8000 \
  -e FDP_BASE_URL=https://your-fdp.example.org \
  ghcr.io/fairdatateam/fdp-mcp:latest
```

- **Works on the network that exists.** It consumes only the public, specified
  FDP surface (LDP, `/sparql`, the search API, SHACL shapes) — so it works
  against FDPneo **and** the Java reference implementation with no server-side
  changes.
- **Read-only and safe.** No mutation tools; strict egress (talks only to the
  target FDP); anonymous by default, or it forwards your FDP API key per session
  (never stored, never logged).
- **Honest.** A capability the target FDP lacks degrades to a structured
  `unsupported` result — never a fabricated answer. Every record result carries
  its IRI so the agent cites holdings instead of inventing them.
- **Contract-first.** The tool contract is implementation-agnostic and published
  in [`docs/mcp-tool-surface.md`](docs/mcp-tool-surface.md); this codebase is its
  reference implementation.

- [What it can do](#what-it-can-do)
- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Build from source](#build-from-source)
- [Configuration](#configuration)
- [Deploy](#deploy)
- [Connect an MCP client](#connect-an-mcp-client)
- [Security posture](#security-posture)
- [Develop](#develop)
- [Project docs](#project-docs)

---

## What it can do

Eight read-only tools over one FDP:

| Tool | Purpose | Notes |
|---|---|---|
| `fdp_info` | Describe the repository: root record, the resource kinds it holds, and which optional endpoints (SPARQL, search) it supports. | Kinds are discovered at runtime, never hard-coded. |
| `list_records` | Enumerate records, optionally by `kind` and/or `parent` container, paged. | Summary records; IRIs always present. |
| `get_record` | Full metadata for one record IRI, with signposting/containment links. | Framed JSON-LD by default; raw Turtle/JSON-LD/RDF-XML/N-Triples on request. |
| `get_schema` | The SHACL shape for a kind — what its fields mean and expect. | Optional (capability `shapes`). |
| `search` | Keyword/faceted discovery within the FDP. | Optional (capability `search-api`); degrades where absent. |
| `sparql_query` | Read-only SPARQL over the public endpoint. | Update/`SERVICE` forms refused **before** any network call. Optional (`sparql`). |
| `get_access_conditions` | "May I use this, under what licence, and whom do I contact?" — resolves `dct:license`, ODRL `dct:rights`, `dct:accessRights`, and contact points. | Reports `determinable: false` honestly when the metadata is silent. |
| `list_data_services` | Enumerate DCAT `DataService` records with their endpoints and `dct:conformsTo` claims. | Discovery only; the seed of the capability profile. |

**Endpoint discovery.** When the FDP advertises its service endpoints in the
root record (VoID `void:sparqlEndpoint`, DCAT `dcat:DataService`), the bridge
discovers them automatically; otherwise it falls back to configured paths. An
explicit operator override always wins, and an advertised endpoint is used only
if it sits on the FDP's own origin (strict egress).

---

## How it works

```
MCP client  ──MCP──▶  fdp-mcp  ──HTTP (public surface only)──▶  FAIR Data Point
(Claude, …)          (this)      LDP GET · /sparql · search · SHACL shapes
```

`fdp-mcp` is a **thin adapter**: each tool translates, paginates, and shapes
results from the FDP's public HTTP surface into agent-friendly JSON. It holds no
authorization logic — the FDP's own publication-state / policy machinery decides
what a request (anonymous, or with a forwarded key) may see. Because the bridge
may use only the public surface, every capability it cannot implement cleanly is
recorded as a public-API gap in [`docs/fdp-api-gaps.md`](docs/fdp-api-gaps.md)
and fed back to the FDP roadmap.

Motivation and placement: the
[Agent Consumption Vision](../server/docs/architecture/agent-consumption-vision.md)
and [ADR-0018](../server/docs/adr/0018-agent-consumption-mcp-server.md).

---

## Quick start

The only required setting is `FDP_BASE_URL`.

```bash
docker run --rm -p 8080:8000 \
  -e FDP_BASE_URL=https://your-fdp.example.org \
  ghcr.io/fairdatateam/fdp-mcp:latest
```

The bridge serves the **streamable-HTTP** MCP transport at
`http://localhost:8080/mcp` and a liveness probe at
`http://localhost:8080/healthz`. For the full walkthrough — client configs and a
scripted three-minute demo — see
[`docs/agent-quickstart.md`](docs/agent-quickstart.md).

---

## Build from source

Requires Python 3.14+ and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync                                   # install deps into .venv
FDP_BASE_URL=https://your-fdp.example.org uv run fdp-mcp
```

Build the container image locally:

```bash
docker build -t fdp-mcp:local .
docker run --rm -p 8080:8000 -e FDP_BASE_URL=https://your-fdp.example.org fdp-mcp:local
```

The image is multi-stage (uv build → slim, non-root runtime). CI publishes
`ghcr.io/fairdatateam/fdp-mcp` on every push to `main`.

---

## Configuration

`FDP_BASE_URL` is required; everything else has a safe default. Non-URL settings
are namespaced under `FDP_MCP_`.

| Variable | Default | Purpose |
|---|---|---|
| `FDP_BASE_URL` | *(required)* | Base URL of the target FDP. The bridge speaks **only** to this origin. |
| `FDP_MCP_TRANSPORT` | `streamable-http` | `streamable-http` (network sidecar) or `stdio` (desktop-client subprocess). |
| `FDP_MCP_HOST` | `127.0.0.1` | Bind address for streamable-HTTP. The image sets `0.0.0.0`. |
| `FDP_MCP_PORT` | `8000` | Bind port for streamable-HTTP. |
| `FDP_MCP_LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error` / `critical`. Credentials are always redacted. |
| `FDP_MCP_FDP_TIMEOUT_SECONDS` | `30` | Per-request timeout for FDP calls. |
| `FDP_MCP_FDP_MAX_RESPONSE_BYTES` | `10485760` | Response-size cap (10 MiB); oversized responses are aborted. |
| `FDP_MCP_FDP_SPARQL_PATH` | `/fdp-api/sparql` | SPARQL endpoint path override. When left default, an advertised endpoint is preferred. |
| `FDP_MCP_FDP_SEARCH_PATH` | `/fdp-api/search` | Search endpoint path override. Same discovery behaviour. |
| `FDP_MCP_MAX_CONCURRENT_SESSIONS` | `100` | Cap on concurrent sessions (streamable-HTTP). |
| `FDP_MCP_SESSION_IDLE_TIMEOUT_SECONDS` | `300` | Drop a session after this idle period. |
| `FDP_MCP_SESSION_LIFETIME_TIMEOUT_SECONDS` | `3600` | Absolute session lifetime ceiling. |

There is **no** credential setting and **no** egress allow-list setting by
design — a forwarded API key is per-session and memory-only, and egress is
pinned to `FDP_BASE_URL`'s origin in code.

---

## Deploy

Run the published image with `FDP_BASE_URL` (see [Quick start](#quick-start)),
or add it to a compose stack alongside the FDP so an FDPneo install comes up
agent-ready:

```yaml
services:
  fdp-mcp:
    image: ghcr.io/fairdatateam/fdp-mcp:latest
    environment:
      FDP_BASE_URL: http://server:8000   # the FDP container's in-network URL
      FDP_MCP_HOST: 0.0.0.0
    ports:
      - "8080:8000"
    depends_on:
      - server
    restart: unless-stopped
```

Terminate TLS and apply rate limits at a reverse proxy in front of the sidecar,
as for any long-lived-connection service.

---

## Connect an MCP client

**Claude Desktop (stdio).** Add to `claude_desktop_config.json`:

```jsonc
{
  "mcpServers": {
    "fdp": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "FDP_BASE_URL=https://your-fdp.example.org",
        "-e", "FDP_MCP_TRANSPORT=stdio",
        "ghcr.io/fairdatateam/fdp-mcp:latest"
      ]
    }
  }
}
```

**Generic streamable-HTTP clients.** Connect to `http://localhost:8080/mcp`.

**Forwarding an API key.** Anonymous by default; to see restricted records the
client supplies your FDP API key as the session bearer (`Authorization: Bearer
<key>`), forwarded verbatim to the FDP for that session only.

Per-client config snippets, MCP Inspector usage, and the demo script are in
[`docs/agent-quickstart.md`](docs/agent-quickstart.md).

---

## Security posture

- **Strict egress** — outbound HTTP is pinned to `FDP_BASE_URL`'s origin
  (redirects included); no arbitrary IRIs are dereferenced, and SPARQL `SERVICE`
  (federation) is refused.
- **Read-only** — no mutation tools; SPARQL update forms are rejected
  client-side before any network call.
- **Credentials** — anonymous by default; a forwarded key is memory-only,
  session-scoped, never persisted, and redacted from all logs.
- **Bounded** — per-request timeouts, a response-size cap, and a
  concurrent-session cap.

---

## Develop

Tooling matches the server repo: `uv`, `ruff`, `pyright` (strict), `pytest`.

```bash
uv sync --extra dev
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest                       # unit + conformance + in-process integration
```

Run the live integration test against a real FDP:

```bash
FDP_MCP_IT_BASE_URL=http://localhost:8000 uv run pytest tests/integration/test_live_fdp.py
```

Layout: `src/fdp_mcp/` — `config.py`, `server.py`, `fdp/` (client layer:
`client`, `ldp`, `sparql`, `search`, `shapes`, `discovery`), `tools/` (one
module per tool), `shaping.py` (JSON-LD framing + envelopes). Conventions and
ground rules for contributors are in [`CLAUDE.md`](CLAUDE.md).

---

## Project docs

- [`docs/mcp-tool-surface.md`](docs/mcp-tool-surface.md) — the implementation-agnostic tool contract (the spec, not this code, is authoritative).
- [`docs/agent-quickstart.md`](docs/agent-quickstart.md) — connect-your-agent guide + three-minute demo.
- [`docs/fdp-api-gaps.md`](docs/fdp-api-gaps.md) — the public-API gap report (a living deliverable).
- [`CHANGELOG.md`](CHANGELOG.md) · [`TASKS.md`](TASKS.md) · [`CLAUDE.md`](CLAUDE.md)

## Status

Released — the full read-only tool surface (eight tools), root-metadata endpoint
discovery, and unit/conformance/integration suites are in place and validated
against a live FDPneo. See [`CHANGELOG.md`](CHANGELOG.md).

## License

[Apache-2.0](LICENSE) (matching the FDP server).
