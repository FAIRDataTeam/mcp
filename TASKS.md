# Implementation tasks — fdp-mcp

Phased build plan for the MCP bridge. Each task is sized to fit one focused
Claude Code session, ends in something runnable or testable, and leaves the
codebase in a working state.

Read [`CLAUDE.md`](CLAUDE.md) before starting anything, and the two documents
it points to in the server repo —
[ADR-0018](../server/docs/adr/0018-agent-consumption-mcp-server.md) and the
[Agent Consumption Vision](../server/docs/architecture/agent-consumption-vision.md).
The ground rules (public surface only, no authorization logic, no credential
storage, strict egress, read-only) are decided there; do not improvise around
them.

Status markers: `[x]` completed, `[~]` partially done, `[ ]` not started.

---

## Phase 0 — Repo foundations

### 0.1 [x] Project scaffold

- `uv`-managed Python 3.12+ project: `pyproject.toml` with the `mcp` SDK,
  `httpx`, `rdflib`, `pydantic-settings`, `structlog`; dev deps `ruff`,
  `pyright`, `pytest`, `pytest-asyncio`, `respx`, `testcontainers`. Follow the
  server repo's dependency-comment style (pin floors, note security-audit
  rationale).
- Source layout from `CLAUDE.md` (src/fdp_mcp/…); empty modules with
  docstrings; `config.py` with `FdpMcpSettings` (`FDP_BASE_URL` required,
  transport/port settings, log level).
- CI config mirroring the server repo's quality gate (ruff, pyright, pytest).
- `Dockerfile` (multi-stage, non-root, same base-image conventions as
  `../server/Dockerfile`).
- Smoke test: settings load from env; app module imports cleanly.

### 0.2 [x] MCP server assembly and transports

- `server.py`: MCP server instance (official SDK), streamable-HTTP transport
  as the default (ASGI, uvicorn) and stdio transport behind a flag for local
  agent use.
- Per-session context object carrying: optional forwarded bearer credential
  (memory only — never logged; redact in structlog processors), session id,
  target FDP base URL.
- Idle/lifetime timeouts and a max-concurrent-sessions limit.
- Tests: server starts on both transports; a session with and without a
  bearer token produces the right context; log output never contains the
  token (assert on captured logs).

References: ADR-0018 §2/§3.

---

## Phase 1 — Contract and FDP client layer

### 1.1 [x] Tool-surface specification (`docs/mcp-tool-surface.md`)

The contract this repo implements — written implementation-agnostically so
any party could implement it against any FDP:

- For each v1 tool (`fdp_info`, `list_records`, `get_record`, `get_schema`,
  `search`, `sparql_query`, `get_access_conditions`, `list_data_services`):
  name, parameters with JSON Schema, result shape, error envelope,
  pagination conventions, JSON-LD framing rules.
- Mark each tool **required** vs **optional**: optional tools degrade
  explicitly when the target FDP lacks the backing surface (e.g. no search
  endpoint), returning a structured `unsupported` result — never a fake
  answer. This required/optional split is informed by what the Java reference
  implementation exposes (open question 2 in the vision doc).
- Versioning statement for the contract itself.

### 1.2 [x] FDP client layer: LDP + root discovery

- `fdp/ldp.py`: content-negotiated GET of records and containers
  (`text/turtle`, `application/ld+json`), Link-header parsing (LDP types,
  `constrainedBy`, signposting relations where present), container paging.
- Root discovery: fetch `FDP_BASE_URL`, identify the root FDP record and the
  resource kinds present (enumerate — kinds are runtime-defined per FDP;
  never hard-code the DCAT five).
- Strict egress: a single `httpx.AsyncClient` whose request hook rejects any
  URL outside `FDP_BASE_URL`'s origin. Timeouts and response-size caps on
  every call.
- Unit tests with respx fixtures for **both** FDPneo and Java-reference
  response shapes; divergences found while writing fixtures go into
  `docs/fdp-api-gaps.md`.

References: CLAUDE.md ground rules; ADR-0018 §1/§3.

### 1.3 [x] FDP client layer: SPARQL, search, shapes

- `fdp/sparql.py`: POST to the public `/sparql`; **read-only query forms
  only** — parse and reject updates client-side before sending; result
  handling for SELECT (JSON) and CONSTRUCT (graph).
- `fdp/search.py`: the FDP search API where available; capability-probe on
  first use, degrade per the contract when absent.
- `fdp/shapes.py`: retrieve the SHACL shape for a kind (via `constrainedBy`
  links / published shape endpoints).
- Start `docs/fdp-api-gaps.md` in earnest: template (capability, blocking
  tool, implementations affected, suggested server-side fix) + entries found
  so far.

References: ADR-0018 §4/§5.

---

## Phase 2 — Tools

### 2.1 [x] Read tools: `fdp_info`, `list_records`, `get_record`, `get_schema`

- Thin handlers over Phase 1 client layer; results per the 1.1 contract
  (framed JSON-LD default, raw serialisation on request, IRIs always
  present so agents can cite).
- `get_record` includes signposting relations when the FDP emits them.
- Tests: contract-shape validation for every result; unknown IRI → structured
  NotFound envelope; both implementation fixture sets.

### 2.2 [x] Query tools: `search`, `sparql_query`, `get_access_conditions`, `list_data_services`

- `search` and `sparql_query` over 1.3, including the explicit-degrade path.
- `get_access_conditions(iri)`: resolve the record's `dct:license`,
  `dct:rights` / ODRL policy references and contact points into the contract's
  JSON shape — this tool answers "may I use it, and whom do I ask?".
- `list_data_services()`: enumerate DCAT `DataService` records with endpoint
  descriptions and `dct:conformsTo` claims — the seed of the capability
  profile (vision §5). Discovery only; no dispatching.
- Tests: SPARQL update forms rejected before any network call; degrade paths
  return the contract's `unsupported` shape.

References: vision doc §4/§5.

---

## Phase 3 — End-to-end, demo assets, release

### 3.1 [x] Integration + conformance suites

- Integration: testcontainers-launched FDPneo instance; full golden-path
  session via a real MCP SDK client (initialize → list tools → search →
  get_record → get_access_conditions → get_schema → sparql_query).
- Anonymous vs forwarded-API-key session against the same instance: results
  differ per the FDP's own visibility rules; bridge logs contain no token.
- Conformance: every tool result validates against `docs/mcp-tool-surface.md`
  schemas (single source: generate validators from the spec's JSON Schemas).
- If feasible, a second integration target against a Java reference
  implementation container; findings → gap report.

### 3.2 [x] Demo assets and quickstart

- `docs/agent-quickstart.md`: connecting Claude / generic MCP clients
  (config snippets per client), one `docker run` bring-up, and the scripted
  three-minute demo from the vision document §6 (including the "re-point at a
  Java FDP" reach moment).
- Coordinate `../server`: add the `fdp-mcp` service to the standard deploy
  profiles (server TASKS.md Phase 19) so FDPneo installs come up agent-ready.

### 3.3 [x] v0.1.0 release

- Image published (GHCR, via CI on push to `main`); release notes + tag
  (`v0.1.0` at `9c9000f`, GitHub Release published). README instructions
  verified.
- Gap report triaged with the server team (G-01…G-06 → server Phase 19 /
  `server/docs/conformance/agent-ready.md`, linked both ways).
- Quality gate green: ruff clean, pyright 0 errors, unit + conformance +
  integration suites.

---

## Phase 4 — Post-v0.1 maintenance and enhancements

Shipped so far: **v0.1.0** (initial read-only surface); **v0.1.1** (root-metadata
endpoint discovery + the DirectContainer fix, PR #1); **v0.2.0** (SHACL shape
closure, discovery memoization, truncation flags, G-07 docs, PR #2).

### 4.1 [x] G-05 — consume advertised SPARQL/search endpoints (bridge side)

- `fdp/discovery.py`: resolve each endpoint by *override → advertised on the FDP
  origin → configured default*, reading `void:sparqlEndpoint` / DCAT
  `dcat:DataService` from the root; off-origin advertisements refused; a resolved
  endpoint that 404s still degrades to `unsupported`. Root fetched once per
  session and shared with kind enumeration. Shipped v0.1.1; verified against a
  live FDPneo. Server side shipped in FDPneo (see 4.7 — reconcile the version).

### 4.2 [x] Fix: recognise `ldp:DirectContainer` as a container

- FDPneo types containers `ldp:DirectContainer` (not the bare `ldp:Container`);
  `is_container` / `is_ldp_container` now recognise the whole LDP container family.
  Found by live validation — `list_data_services` and `discover_root` previously
  failed to descend. Fixtures made `DirectContainer`-only to guard the regression.
  Shipped v0.1.1.

### 4.3 [x] G-06 — compose the SHACL shape closure (bridge side)

- `get_schema` follows `sh:node` references (on-origin, bounded, cycle-guarded)
  so inherited/composed properties appear in the digest. No server change needed
  (FDPneo already serves the closure via `?composed=true` / `/{prefix}/spec`).

### 4.4 [x] G-07 — the anonymous SPARQL default-graph trap

- Anonymous SPARQL sees an **empty default graph**; data lives in named graphs
  (one-graph-per-record, ADR-0007). A naive `SELECT ?s ?p ?o WHERE { ?s ?p ?o }`
  returns nothing. Verified live: 0 triples in the default graph, 573 across 31
  named graphs. Add gap entry **G-07**; document the `GRAPH ?g { … }` requirement
  in the `sparql_query` contract section + quickstart; add a hint to the tool
  description.

### 4.5 [x] Per-session discovery memoization + faster kind resolution

- `fdp_info`, `get_schema`, and `list_data_services` each trigger a full
  containment BFS. Cache `RootDiscovery` on the client (as `root_resource` is),
  and short-circuit the BFS in `get_schema` once the requested kind is found.

### 4.6 [x] Surface BFS truncation honestly

- `discover_root` computes `truncated`, but `fdp_info` / `list_data_services`
  don't expose it — an agent can't tell a partial crawl from a complete one.

### 4.7 [ ] Cross-repo coordination (server hand-off)

- `server/docs/conformance/agent-ready.md` still marks **G-05 "bridge-pending"**
  (now shipped in v0.1.1 → flip to resolved-both-sides) and cites **v0.5.0**
  while our gap report cites **v0.6.0** — reconcile the version.
- Add the `fdp-mcp` service to the standard FDPneo deploy profiles (the 3.2
  hand-off; compose snippet is in `docs/agent-quickstart.md` §6 and README).

### Later / strategic (own ADR where noted)

- [ ] MCP **resources + prompts** — expose records as resources; a guided
  "explore this FDP" prompt (vision open question 3; v1 is tools-only).
- [ ] MCP **OAuth authorization** flow, beyond API-key pass-through (open
  question 1), once client support stabilises.
- [ ] **Increment B** — capability-profile schema package (`DataService` +
  `dct:conformsTo` vocabulary); `list_data_services` is the seed.
- [ ] **Increment C** — Index-level MCP: multi-FDP discovery + query
  dispatch/aggregation over an FDP Index (own ADR).
- [ ] **Increment D** — access-request drafting tools (against ODRL Offers).
- [ ] Observability: OpenTelemetry spans on FDP calls; a readiness probe that
  checks FDP reachability (distinct from `/healthz`).
- [ ] Broaden `get_access_conditions` license-openness (SPDX-based map).

---

**Out of scope for v1 (tracked in Phase 4):** mutation tools (permanently out —
read-only by design); MCP resources/prompts (4.x later); multi-FDP / Index-level
operation (increment C — own ADR); capability-profile schema package
(increment B); access-request drafting (increment D); MCP OAuth flow (open
question 1).
