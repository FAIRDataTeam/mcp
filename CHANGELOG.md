# Changelog

All notable changes to `fdp-mcp` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
[semantic versioning](https://semver.org/). The **tool-surface contract** is
versioned independently — see `docs/mcp-tool-surface.md` §10.

## [0.3.1] — 2026-09-02

### Changed

- **FDP-O namespace dual-accept** (fdpneo-server 0.16 / ADR-0026). The server
  moved its vocabulary from the unregistered `https://w3id.org/fdp/o#` to the
  published FDP Ontology namespace `https://w3id.org/fdp/fdp-o#`. The sidecar
  now reads `metadataState`/`allowedStateTransition` and matches the
  `hasStateTransition` Link relation in both namespaces, so it works against
  pre- and post-0.16 servers. JSON-LD compaction gains the new `fdp:` prefix
  (the legacy namespace compacts as `fdp-legacy:`).

## [0.3.0] — 2026-08-26

### Added

- **Opt-in write extension (ADR-0024; contract 1.1.0-draft).** Four new tools —
  `create_record` (LDP `POST`), `update_record` (`PUT` replace or SPARQL-update
  `PATCH`), `delete_record`, `set_record_state` (`DRAFT`/`PUBLISHED`/`ARCHIVED`)
  — registered **only** when `FDP_MCP_ENABLE_WRITE=true`. They refuse anonymous
  sessions before any network call (`authentication_required`), require the
  caller to present `if_match` (the record's `etag`), validate RDF bodies
  (parse + one primary subject) and SPARQL updates (no `LOAD`/`SERVICE`/graph
  management/off-origin graphs) client-side, send the body verbatim, and
  forward every write for the FDP to decide. PATCH and state transitions are
  optional capabilities (`ldp_patch`, `state_transition`) that degrade to
  `unsupported`.
- **`etag` on the Record object** (`get_record`, `list_records` items) — the
  validator to pass as `if_match`.
- **Error codes** `precondition_failed` (412/428), `conflict` (409),
  `validation_failed` (422, the FDP's SHACL report relayed in `details`),
  `unsupported_media_type` (415), `authentication_required`.
- `FdpClient.put/patch/delete`, `fdp/write.py`, `sparql.classify_update`.
- Server instructions switch to a read-write text when enabled; a warning is
  logged for `stdio` + write (inert: no credential can be forwarded).

### Documented

- **G-08** the advertised `hasStateTransition` link does not resolve on FDPneo
  (the bridge tries it first, then falls back to the `/fdp-api/…/state`
  convention); **G-09** the state-transition endpoint is not standardised
  across implementations; **G-10** FDPneo's OpenAPI omits `PATCH`, `/state`,
  and `securitySchemes`.

## [0.2.0] — 2026-07-05

### Added

- **SHACL shape closure in `get_schema` (G-06).** The digest now follows
  `sh:node` references — fetching each composed shape on the FDP origin (bounded,
  cycle-guarded) and aggregating their `sh:property` — so inherited constraints
  appear, not just the primary shape's direct properties. Verified against a
  live FDPneo catalog shape (~7 direct → 48 composed). Closes the bridge side of
  gap G-06 (no server change needed).
- **Per-session discovery memoization.** Root discovery (root record + kinds) is
  cached on the client, so `fdp_info`, `get_schema`, and `list_data_services`
  share a single containment crawl per session instead of re-crawling.
- **Truncation surfaced.** `fdp_info.truncated` and the page envelope's
  `page.truncated` (`list_data_services`) report when a bounded traversal hit the
  crawl cap — so a partial result is distinguishable from a complete one.

### Documented

- **G-07 — anonymous SPARQL default-graph trap.** An FDP that stores one named
  graph per record (ADR-0007) leaves the *default* graph empty, so a bare
  `SELECT ?s ?p ?o WHERE { ?s ?p ?o }` returns no rows even against a full
  repository. The `GRAPH ?g { … }` requirement is now documented in the
  tool-surface spec (§5.6), the `sparql_query` tool description, and the
  quickstart; recorded as gap **G-07**. Verified live: 0 triples in the default
  graph vs 573 across 31 named graphs.

## [0.1.1] — 2026-07-05

### Added

- **Endpoint discovery (G-05).** `sparql_query`, `search`, and `fdp_info` now
  resolve the FDP's SPARQL/search endpoints from the **root metadata** — VoID
  `void:sparqlEndpoint` and DCAT `dcat:DataService` / `dcat:endpointURL` — rather
  than relying only on configured paths (`fdp_mcp/fdp/discovery.py`). Resolution
  precedence per endpoint: an explicit operator override
  (`FDP_MCP_FDP_SPARQL_PATH` / `FDP_MCP_FDP_SEARCH_PATH`) → the advertised endpoint
  **on the FDP's own origin** (off-origin advertisements are refused — strict
  egress) → the configured default. A resolved endpoint that 404s still degrades
  the tool to `unsupported`, so API honesty is preserved. The root record is
  fetched once per session (`FdpClient.root_resource` / `ldp.fetch_root`) and
  shared by discovery and kind enumeration. Closes the bridge side of gap G-05
  (server side shipped in FDPneo v0.6.0).

### Fixed

- **Container recognition for `ldp:DirectContainer`.** `LdpResource.is_container`
  (and `LinkSet.is_ldp_container`) recognised only the bare `ldp:Container`, but
  FDPneo types its containers `ldp:DirectContainer`. The containment walks in
  `list_data_services` and `discover_root` therefore never descended past the
  top-level containers — so `list_data_services` returned empty and `fdp_info`
  under-reported kinds against a real FDP. Now the whole LDP container family
  (`Container` / `BasicContainer` / `DirectContainer` / `IndirectContainer`) is
  recognised. Caught by live validation against FDPneo v0.6.0; the mocked-FDP
  fixtures are now `DirectContainer`-only so the suite guards against regression.

## [0.1.0] — 2026-07-04

First release: a standalone MCP sidecar that exposes the metadata of any
spec-compliant FAIR Data Point to AI agents through a read-only tool surface.

### Added

- **Tool-surface contract** (`docs/mcp-tool-surface.md`, v1.0.0-draft) — the
  implementation-agnostic specification of the eight read-only tools, common
  envelopes (result / page / error / `unsupported`), the Record object,
  pagination, JSON-LD framing rules, the required-vs-optional split, and a
  versioning policy. This repo is its reference implementation.
- **Eight read-only tools**: `fdp_info`, `list_records`, `get_record`,
  `get_schema`, `search`, `sparql_query`, `get_access_conditions`,
  `list_data_services`. Framed JSON-LD by default with raw serialisations on
  request; every record-shaped result carries its IRI for citation.
- **FDP client layer** over the public surface only: content-negotiated LDP GET
  with RFC 8288 `Link` parsing (LDP types, `constrainedBy`, FAIR Signposting),
  container paging, runtime kind discovery, read-only SPARQL (update and
  `SERVICE` forms rejected client-side before any network call), the search API
  with explicit degradation, and SHACL shape resolution + digest.
- **MCP server** on streamable-HTTP (default) and stdio transports, with a
  per-session context, idle/lifetime timeouts, and a concurrent-session cap.
- **Security posture**: strict egress (outbound HTTP pinned to `FDP_BASE_URL`'s
  origin, no dereferencing of arbitrary IRIs, `SERVICE` federation refused);
  anonymous by default with per-session credential pass-through held in memory
  only and redacted from all logs; response size caps and timeouts on every call.
- **Explicit degradation**: optional tools return a structured `unsupported`
  result when the target FDP lacks the backing surface — never a fabricated
  answer. Each gap is recorded in `docs/fdp-api-gaps.md` (G-01…G-06).
- **Tests**: unit (respx-mocked FDP, both FDPneo and Java-reference response
  shapes), conformance (every tool result validated against the contract's JSON
  Schemas), and integration (a real MCP client driving the server end-to-end,
  plus credential-forwarding visibility and no-token-in-logs). An opt-in live-FDP
  integration test runs against `FDP_MCP_IT_BASE_URL`.
- **Docs**: `README.md`, `docs/agent-quickstart.md` (one-command bring-up, client
  configs, the three-minute demo), and the living gap report.
- **Packaging**: `uv`-managed project, multi-stage non-root `Dockerfile`, CI
  (ruff + pyright + pytest) and a dependency-audit + SBOM workflow.

### Notes

- v1 is read-only and single-FDP. No mutation tools, no MCP resources/prompts,
  no Index-level / multi-FDP operation (vision increments B–D).
