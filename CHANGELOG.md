# Changelog

All notable changes to `fdp-mcp` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
[semantic versioning](https://semver.org/). The **tool-surface contract** is
versioned independently — see `docs/mcp-tool-surface.md` §10.

## [0.1.0] — unreleased

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
