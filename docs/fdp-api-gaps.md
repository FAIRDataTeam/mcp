# FDP public-API gap report

**Status:** Seeded (task 1.1). Expanded in earnest in task 1.3 as the FDP client
layer is written against real responses from both implementations.

This is a first-class, continuously maintained deliverable (ADR-0018 §4). The
bridge may use **only** the public, specified FDP surface; every capability the
[tool surface](mcp-tool-surface.md) needs that the public surface cannot provide
cleanly — a missing endpoint, a missing serialization, an under-specified
contract, or a divergence between implementations — is recorded here with the
concrete tool it blocks or degrades. The bridge **never** resolves a gap by
reaching for a private endpoint; it degrades the tool explicitly (returns the
`unsupported` result or an empty-but-honest answer) and logs the gap here.

The server repo triages this report into its roadmap (server `TASKS.md`
Phase 19). Link entries both ways when triaged.

## How to read an entry

| Field | Meaning |
|---|---|
| **Capability** | The bridge capability name surfaced in the `unsupported` result (e.g. `search-api`). |
| **Blocks / degrades** | The tool(s) affected and how (unsupported vs partial). |
| **Implementations affected** | Which FDP implementations lack/diverge (FDPneo, Java reference implementation). |
| **Public-surface status** | What the specified public surface offers today, and why it is insufficient. |
| **Suggested resolution** | The server-side or spec change that would close the gap. |
| **Severity** | `blocking` (tool cannot function), `degrading` (tool works but loses fidelity), `interop` (implementations disagree). |
| **Triage** | Link to a server `TASKS.md` Phase 19 item once triaged; else `untriaged`. |

---

## G-01 — No search endpoint on the Java reference implementation

- **Capability:** `search-api`
- **Blocks / degrades:** [`search`](mcp-tool-surface.md#55-search) → returns the
  `unsupported` result, `alternative` pointing at `sparql_query` / `list_records`.
- **Implementations affected:** Java reference implementation (no search API).
  FDPneo exposes `POST /fdp-api/search` (enabled by default).
- **Public-surface status:** search is not part of the core FDP specification;
  it is an FDPneo extension. An agent asking for keyword discovery against a Java
  RI FDP gets no backing surface.
- **Suggested resolution:** specify a minimal, optional search contract at the
  FDP-spec level, or document `sparql_query` as the interoperable discovery path.
  The required/optional split in the tool surface already treats `search` as
  optional in anticipation of this.
- **Severity:** interop / degrading (by design — `search` is optional).
- **Triage:** untriaged.

## G-02 — Shape discovery is under-specified across implementations

- **Capability:** `shapes`
- **Blocks / degrades:** [`get_schema`](mcp-tool-surface.md#54-get_schema) →
  `unsupported` when the bridge cannot resolve a kind to a fetchable SHACL shape.
- **Implementations affected:** FDPneo exposes shapes via
  `GET /fdp-api/schemas` / `/fdp-api/schemas/{id}`, the `/fdp-api/{prefix}/spec`
  NodeShape endpoint, and per-record `ldp:constrainedBy` links. The Java
  reference implementation separates schemas from resource definitions but
  exposes shape *discovery* differently; there is no single specified mechanism
  for "given a kind, get its shape document."
- **Public-surface status:** `ldp:constrainedBy` (LDP §4, R12) is the one
  cross-implementation signal, but it appears on records, not as a kind→shape
  directory, and its presence/target conventions vary.
- **Suggested resolution:** specify a canonical kind→shape resolution at the
  FDP-spec level (e.g. a required `constrainedBy` on containers, or a standard
  shapes-listing endpoint).
- **Severity:** interop / degrading.
- **Triage:** untriaged.

## G-03 — SPARQL endpoint presence/enablement is not guaranteed

- **Capability:** `sparql`
- **Blocks / degrades:** [`sparql_query`](mcp-tool-surface.md#56-sparql_query) →
  `unsupported` when no reachable public SPARQL query endpoint exists.
- **Implementations affected:** FDPneo exposes `/fdp-api/sparql`. Availability
  and anonymous reachability on arbitrary deployments (any implementation) is not
  guaranteed by the spec.
- **Public-surface status:** a SPARQL endpoint is part of the expected FDP
  surface but is not universally guaranteed enabled/anonymous.
- **Suggested resolution:** capability-probe on first use and degrade; longer
  term, a spec statement on SPARQL endpoint expectations.
- **Severity:** degrading.
- **Triage:** untriaged.

## G-04 — FAIR Signposting relations absent on the Java reference implementation

- **Capability:** `signposting` (degrades, does not block)
- **Blocks / degrades:** [`get_record`](mcp-tool-surface.md#53-get_record) — the
  `links` block (`cite_as`, `described_by`, `license`, `authors`, `item`,
  `collection`, `constrained_by`) is populated from the `Link` header. When the
  FDP emits no FAIR-Signposting relations, `get_record.links` is sparse and
  `get_schema` loses the per-record `constrainedBy` shape-resolution path.
- **Implementations affected:** FDPneo emits FAIR Signposting Level 1 on every
  `GET`/`HEAD`. The Java reference implementation emits (at most) the LDP
  interaction-model `type` links, not the citation/navigation relations.
- **Public-surface status:** signposting is specified (ADR-0017 references the
  FAIR Signposting profile) but not uniformly implemented. The bridge falls back
  to the RDF graph where it can (parent via `dct:isPartOf`, members via
  `ldp:contains`, `constrainedBy` via the graph triple), but `cite-as` and the
  per-media-type `describedby` set have no graph equivalent.
- **Suggested resolution:** make FAIR Signposting Level 1 a conformance
  expectation, or specify graph-level equivalents the bridge can rely on.
- **Severity:** interop / degrading. Confirmed by the task-1.2 client-layer
  fixtures (`tests/unit/test_fdp_ldp.py::test_java_jsonld_record_parses_with_sparse_links`).
- **Triage:** untriaged.

---

*Entries G-01…G-03 are seeded from the task-1.1 surface survey; G-04 is the first
confirmed-by-fixture divergence from task 1.2. Task 1.3 adds the SPARQL/search/
shapes client divergences found while writing fixtures for both implementations,
each tied to the tool it affects.*
