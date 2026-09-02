# fdp-mcp tool-surface specification

**Contract version:** 1.1.0-draft
**Status:** Draft (task 1.1; write extension task 5.1). Binding once tagged.
**Applies to:** the MCP tool surface exposed by a bridge over a single FAIR Data
Point (FDP): eight read tools, plus an **opt-in write extension** of four tools
([§5.9](#59-create_record)–[§5.12](#512-set_record_state); ADR-0024).

This document is the **contract**, written to be implementation-agnostic: any
party can implement it against any spec-compliant FDP, and `fdp-mcp` is its
reference implementation. Where this document and the code disagree, this
document wins — fix the code (or, if the contract is wrong, change it here first,
bumping the version per [§10](#10-contract-versioning)).

It is deliberately independent of any one FDP product. It refers only to the
**public, specified FDP surface**: content-negotiated LDP `GET` of records and
containers, the SPARQL query endpoint, an optional search API, published SHACL
shapes, and — for the write extension — LDP `POST`/`PUT`/`PATCH`/`DELETE` with
`If-Match` and the publication-state transition endpoint. It never refers to a private or product-specific endpoint. Product
specifics (how FDPneo or the Java reference implementation happen to expose a
thing) live in [§11](#11-reference-implementation-notes) and, where the public
surface falls short, in [`fdp-api-gaps.md`](fdp-api-gaps.md) — not in the
contract.

---

## 1. Scope and principles

The surface is **eight read tools**, plus **four opt-in write tools** that a
deployment exposes only when explicitly enabled (`FDP_MCP_ENABLE_WRITE`):

| Tool | Requirement | One-line purpose |
|---|---|---|
| [`fdp_info`](#51-fdp_info) | Required | Describe the repository (the root FDP record). |
| [`list_records`](#52-list_records) | Required | Enumerate records, by kind and/or parent, paged. |
| [`get_record`](#53-get_record) | Required | Fetch one record's full metadata, with signposting. |
| [`get_schema`](#54-get_schema) | Optional | The SHACL shape for a kind. |
| [`search`](#55-search) | Optional | Keyword/faceted discovery within the FDP. |
| [`sparql_query`](#56-sparql_query) | Optional | Read-only SPARQL over the public endpoint. |
| [`get_access_conditions`](#57-get_access_conditions) | Required | License, rights/ODRL, and contact for a record. |
| [`list_data_services`](#58-list_data_services) | Required | DCAT `DataService` records and their endpoints. |
| [`create_record`](#59-create_record) | Write extension | Create a record in a container (LDP `POST`). |
| [`update_record`](#510-update_record) | Write extension | Replace (`PUT`) or patch (SPARQL-update `PATCH`) a record under `If-Match`. |
| [`delete_record`](#511-delete_record) | Write extension | Delete a record under `If-Match`. |
| [`set_record_state`](#512-set_record_state) | Write extension | Move a record between `DRAFT`/`PUBLISHED`/`ARCHIVED`. |

"Required" vs "Optional" is defined in [§4](#4-required-vs-optional-and-explicit-degradation).

These principles bind every tool; they restate the ground rules in the repo
`CLAUDE.md` and ADR-0018, and the tool sections below do not repeat them:

1. **Public surface only.** A tool consumes only the documented FDP surface. If
   a capability needs something the public surface cannot provide, the tool
   degrades explicitly ([§4](#4-required-vs-optional-and-explicit-degradation))
   and the gap is recorded in `fdp-api-gaps.md`. A tool never reaches for a
   private endpoint.
2. **No authorization logic in the bridge.** The FDP is the sole decision point.
   Requests are anonymous unless the MCP client forwarded a credential, which is
   passed through verbatim ([§3.2](#32-credentials-and-sessions)). Results
   therefore reflect *the FDP's own* publication-state / policy decisions for the
   presented (or absent) credential — the bridge neither widens nor narrows them.
3. **Read-only by default.** With the write extension disabled (the default) no
   tool mutates FDP state; `sparql_query` always rejects update forms before any
   network call ([§5.6](#56-sparql_query)). When a deployment enables the write
   extension ([§5.9](#59-create_record)–[§5.12](#512-set_record_state)), writes
   are explicit tools, require a forwarded credential, and are decided solely by
   the FDP — the bridge still holds no authorization logic (principle 2).
4. **Strict egress.** A tool contacts only the configured target FDP's origin. It
   never dereferences an arbitrary IRI found in metadata.
5. **Cite by IRI.** Every record-shaped result carries the subject `iri`, so an
   agent can cite holdings instead of inventing them.
6. **Honest degradation.** A tool that cannot be satisfied returns a structured
   error or `unsupported` result ([§3.4](#34-the-error-envelope),
   [§3.5](#35-the-unsupported-result)) — never a fabricated or silently empty
   answer that reads as fact.

---

## 2. Notation

- Parameter and result schemas are given as **JSON Schema (draft 2020-12)**
  fragments. `additionalProperties` defaults to `false` for result objects
  unless stated; tools may add fields in a minor contract version.
- `iri` fields are absolute IRI strings.
- "record-shaped" means the [Record object](#36-the-record-object) of §3.6.
- MUST/SHOULD/MAY are used in the RFC 2119 sense for implementers of the
  contract.

---

## 3. Common conventions

### 3.1 Invocation

Each tool is an MCP tool: a name, a JSON input matching its parameter schema, and
a JSON result. A successful call returns the tool's **result object**
([§3.3](#33-the-result-envelope)); a failure returns the **error envelope**
([§3.4](#34-the-error-envelope)); an optional tool with no backing surface
returns the **unsupported result** ([§3.5](#35-the-unsupported-result)). Results
are returned as structured JSON content.

### 3.2 Credentials and sessions

The bridge is anonymous by default. An MCP client MAY supply an FDP credential
(e.g. an API key) as a bearer token on its MCP session; the bridge forwards it
verbatim on that session's FDP requests and on no others. The credential is held
in memory for the session only — never stored, cached, or logged. A tool's
results are exactly what the FDP returns for that credential (or for anonymous
access when none is supplied). The contract exposes **no credential parameter**
on any tool.

Write tools ([§5.9](#59-create_record)–[§5.12](#512-set_record_state)) cannot
succeed without a credential for the FDP to evaluate, so a write call on an
anonymous session is answered `authentication_required`
([§3.4](#34-the-error-envelope)) **before any network call**. This is a
fail-fast, not an authorization decision: every authenticated call is forwarded
verbatim and the FDP alone allows or denies it.

### 3.3 The result envelope

A successful result is a JSON object. Its shape is defined per tool. Tools that
return a set of records use the **page envelope**:

```json
{
  "items": [ /* Record objects, or tool-specific rows */ ],
  "page": {
    "limit": 50,
    "offset": 0,
    "count": 50,
    "has_more": true,
    "next_offset": 50,
    "total": 1234
  }
}
```

- `count` is `items.length` for this page.
- `has_more` is `true` when more results exist beyond this page.
- `next_offset` is present iff `has_more` is `true`; it is the `offset` to pass
  to retrieve the next page.
- `total` is the total across all pages **when the FDP reports it**; it is
  `null` when the backing surface does not expose a reliable total (a legitimate,
  common case — pagination MUST NOT depend on it).
- `truncated` (optional, boolean) is present and `true` when the result was
  produced by a bounded traversal that hit the bridge's crawl cap, so `total`
  and the item set are **partial**. Absent means the enumeration was complete.

See [§3.7](#37-pagination) for the request-side pagination parameters.

### 3.4 The error envelope

A failed call returns:

```json
{
  "error": {
    "code": "not_found",
    "message": "No record is visible at the given IRI.",
    "details": { "iri": "https://fdp.example.org/dataset/42" }
  }
}
```

`code` is one of a closed set; `message` is human-readable and MUST NOT contain
credentials; `details` is an optional object with structured context.

| `code` | Meaning | Typical cause |
|---|---|---|
| `invalid_argument` | The parameters failed validation. | Bad IRI, unknown enum, negative `limit`. |
| `not_found` | No such record is **visible**. | Unknown IRI, or a record the FDP hides from this credential (drafts, policy). The bridge cannot distinguish "absent" from "hidden" and MUST NOT try — see note below. |
| `read_only_violation` | A write/update was requested. | A SPARQL update form. |
| `upstream_error` | The FDP returned an error. | FDP `5xx`, malformed RDF, a `4xx` other than 404. |
| `upstream_unauthorized` | The FDP rejected the credential (or required one). | FDP `401`/`403`. The bridge relays this; it does not itself decide. |
| `upstream_timeout` | The FDP did not respond in time. | Slow endpoint, large query. |
| `too_large` | The FDP response exceeded the bridge's size cap. | Oversized graph/result. |
| `unsupported` | The tool's backing surface is absent on this FDP. | Optional tool only — but returned as a *result*, not an error; see [§3.5](#35-the-unsupported-result). |
| `precondition_failed` | The FDP refused a conditional write. | `If-Match` missing (`428`) or stale (`412`): re-read the record (`etag`) and retry. Write tools only. |
| `conflict` | The FDP reported a conflict. | `409`: a `slug` already in use; a publication-state transition the FDP does not allow (`details` carries the transitions it advertises). Write tools only. |
| `validation_failed` | The FDP rejected the body as invalid. | `422`: SHACL violations. `details` is the FDP's own report (`shape`, `violations[]`) so the agent can repair the body. Write tools only. |
| `unsupported_media_type` | The FDP does not accept the body's media type. | `415` on a write. Write tools only. |
| `authentication_required` | A write was requested on an anonymous session. | Refused by the bridge before any network call ([§3.2](#32-credentials-and-sessions)). Write tools only. |

> **Why 404 is not disambiguated.** A spec-compliant FDP returns `404` both for a
> nonexistent record and for one the caller is not allowed to see (publication
> state, policy) — deliberately, so unpublished work does not leak. The bridge
> honours that: `not_found` means "not visible to you," and the `message` says
> so. Supplying a credential may turn a `not_found` into a result.

### 3.5 The `unsupported` result

An **optional** tool whose backing surface is absent on the target FDP returns,
as a normal (non-error) result:

```json
{
  "unsupported": {
    "tool": "search",
    "reason": "This FDP does not expose a search endpoint.",
    "capability": "search-api",
    "alternative": "Use sparql_query or list_records to enumerate records."
  }
}
```

This is a first-class, machine-readable outcome, distinct from both success and
error, so an agent can route around a missing capability instead of treating a
blank as "nothing here." A **required** tool never returns `unsupported`. Every
`unsupported` a bridge can emit corresponds to an entry in `fdp-api-gaps.md`.

Capability names in use: `search-api`, `sparql`, `shapes`, `signposting`
(read tools); `ldp_patch` and `state_transition` (write extension,
[§5.10](#510-update_record) / [§5.12](#512-set_record_state)).

### 3.6 The Record object

The common shape for a single record. Framed JSON-LD by default
([§3.8](#38-rdf-result-shaping)):

```json
{
  "iri": "https://fdp.example.org/dataset/42",
  "types": ["http://www.w3.org/ns/dcat#Dataset"],
  "title": "Cohort X phenotype registry",
  "kind": "dataset",
  "etag": "\"a1b2c3\"",
  "metadata": { "@context": { /* … */ }, "@id": "…", "…": "…" },
  "links": {
    "parent": "https://fdp.example.org/catalog/7",
    "children": ["https://fdp.example.org/dataset/42/distribution/1"],
    "constrained_by": "https://fdp.example.org/schema/dataset",
    "cite_as": "https://doi.org/10.1234/abcd",
    "described_by": [
      { "href": "https://fdp.example.org/dataset/42", "type": "text/turtle" }
    ],
    "license": "https://creativecommons.org/licenses/by/4.0/",
    "authors": ["https://orcid.org/0000-0002-1825-0097"]
  }
}
```

- `iri` (required): the record's subject IRI. Always present.
- `types` (required): the record's `rdf:type` IRIs (may be empty).
- `title` (nullable): a human label (`dct:title`/`rdfs:label`/`skos:prefLabel`,
  first found), or `null`.
- `kind` (nullable): the runtime kind slug ([§3.9](#39-kinds)) when the bridge
  could resolve it, else `null`.
- `etag` (nullable; since 1.1.0): the FDP's `ETag` for the representation read,
  or `null` when it sent none. It is the value to pass as `if_match` to
  `update_record` / `delete_record` — read before you write.
- `metadata` (required): the record's own metadata as framed JSON-LD (or the raw
  serialization when `format` was requested — see §3.8).
- `links` (required object): navigation/citation links the FDP emitted, chiefly
  from signposting (`Link` header) and containment. Every field is optional;
  unknown/absent relations are omitted rather than nulled. `children` and
  `authors` are arrays (possibly empty); `described_by` lists the available
  serializations with media types.

### 3.7 Pagination

Tools that page accept:

```json
{ "limit": { "type": "integer", "minimum": 1, "maximum": 200, "default": 50 },
  "offset": { "type": "integer", "minimum": 0, "default": 0 } }
```

- Offset/limit is the contract's pagination model regardless of how the FDP
  paginates underneath; the bridge translates.
- A `limit` above the maximum is clamped to the maximum (not an error); the
  effective value is reported in `page.limit`.
- The bridge caps the maximum so an agent cannot request an unbounded page.

### 3.8 RDF result shaping

FDP metadata is RDF. Agents consume JSON more reliably than Turtle, so:

- **Default:** record `metadata` is returned as **framed JSON-LD** — a compacted,
  single-subject-rooted JSON-LD document (the requested/record IRI as `@id`),
  with a `@context` the bridge supplies. Blank-node structure is preserved;
  language-tagged and typed literals use JSON-LD value objects.
- **On request:** a tool that carries a `format` parameter MAY instead return the
  FDP's raw serialization. `format` is one of `"jsonld"` (default), `"turtle"`,
  `"ntriples"`, `"rdfxml"`. For a non-`jsonld` format, `metadata` is a **string**
  holding that serialization and the result adds `"metadata_media_type"`
  (e.g. `"text/turtle"`). The bridge requests the format from the FDP by content
  negotiation and returns the bytes as received (subject to the size cap).
- The subject `iri` is always present in the structured result regardless of
  `format`, so citation never depends on parsing `metadata`.

### 3.9 Kinds

A *kind* is a runtime-defined resource type of the FDP (e.g. catalog, dataset,
distribution, data service — but the set is **per-FDP and not fixed**; the DCAT
types are a common default, not a contract requirement). The contract identifies
a kind by a lowercase **slug** (a stable, URL-safe token, e.g. `"dataset"`) and
carries the kind's `rdf:type` IRI(s) alongside it where relevant. Tools that
accept or return a `kind` MUST treat the set as data discovered at runtime
([`list_records`](#52-list_records) with no `kind` enumerates what exists); they
MUST NOT hard-code a fixed list. `get_schema` and `list_records(kind=…)` operate
over whatever kinds the FDP actually exposes.

---

## 4. Required vs optional, and explicit degradation

**Required** tools are backed by surface every spec-compliant FDP exposes: the
LDP read surface (root record, containers, content-negotiated record `GET`) and
its metadata content. A required tool MUST be implementable against any
conformant FDP; if it fails it returns an **error**, never `unsupported`.

- Required: `fdp_info`, `list_records`, `get_record`, `get_access_conditions`,
  `list_data_services`.
  - `get_access_conditions` and `list_data_services` are required as *tools*: they
    read the LDP surface every FDP has. Their answers may be **empty** (a record
    with no stated license; an FDP with no `DataService` records) — an empty
    result is a valid, honest answer and is **not** `unsupported`.

**Optional** tools depend on surface a conformant FDP MAY omit. An optional tool
probes for its backing surface and, when absent, returns the `unsupported`
result ([§3.5](#35-the-unsupported-result)) and the gap is logged.

- Optional: `get_schema`, `search`, `sparql_query`.
  - `search` — many FDPs (notably the Java reference implementation as commonly
    deployed) expose no search API. → `unsupported`, capability `search-api`.
  - `sparql_query` — the SPARQL endpoint is part of the FDP surface but not
    guaranteed reachable/enabled on every deployment. → `unsupported`, capability
    `sparql`.
  - `get_schema` — SHACL shapes are published by conformant FDPs, but shape
    *discovery* (resolving a kind to its shape document) is under-specified and
    varies. When the bridge cannot resolve or fetch a kind's shape it returns
    `unsupported`, capability `shapes`.

**Write extension** tools are neither required nor optional in the above sense:
a conforming bridge MAY omit them entirely (read-only deployment) and, when it
offers them, MUST expose them only behind an explicit operator opt-in. Within
the extension, `create_record`, `update_record` (`body` mode) and
`delete_record` rest on the LDP write surface every conformant FDP exposes and
fail with an **error**; `update_record` (`patch` mode) and `set_record_state`
depend on surface an FDP MAY lack and degrade to `unsupported` (capabilities
`ldp_patch`, `state_transition`).

The required/optional split, and the exact capability probes, are informed by
what the Java reference implementation exposes vs. FDPneo; those differences are
recorded in [§11](#11-reference-implementation-notes) and drive
`fdp-api-gaps.md`.

---

## 5. Tools

Each tool section gives: requirement, purpose, parameters (JSON Schema), the
public surface it reads, the result shape, and its error/degradation behaviour.
The principles in [§1](#1-scope-and-principles) and conventions in
[§3](#3-common-conventions) apply throughout and are not repeated.

### 5.1 `fdp_info`

**Required.** Answer "what is this repository, who runs it, and what does it
hold?" from the root FDP record.

**Parameters:**

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "format": { "enum": ["jsonld", "turtle", "ntriples", "rdfxml"], "default": "jsonld" }
  }
}
```

**Backing surface:** content-negotiated `GET` of the FDP root (the repository
record), plus its container membership to enumerate the top-level kinds present.

**Result:**

```json
{
  "repository": { /* Record object for the root FDP record */ },
  "kinds": [
    { "slug": "catalog", "type_iris": ["http://www.w3.org/ns/dcat#Catalog"],
      "label": "Catalog", "top_level": true }
  ],
  "endpoints": {
    "sparql": true,
    "search": false
  },
  "truncated": false
}
```

- `repository` is the root as a [Record object](#36-the-record-object) (title,
  publisher, description, conformance profile all live inside `metadata`).
- `kinds` is the set of resource kinds the bridge discovered at runtime
  ([§3.9](#39-kinds)); `top_level` marks kinds directly under the root.
- `endpoints` reports which optional capabilities this FDP supports, so an agent
  knows up front whether `search`/`sparql_query` will work (mirrors the
  `unsupported` probes). Keys are capability names; values are booleans.
- `truncated` is `true` when kind discovery hit the bridge's crawl cap, so
  `kinds` may be incomplete.

**Errors:** `upstream_error`/`upstream_timeout` if the root is unreachable. The
root is expected to be anonymously visible on a usable FDP; a `not_found` here
signals a misconfigured target.

### 5.2 `list_records`

**Required.** Enumerate records, optionally filtered by kind and/or parent
container, paged.

**Parameters:**

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "kind":   { "type": "string", "description": "Kind slug (see fdp_info.kinds). Omit for all kinds." },
    "parent": { "type": "string", "format": "iri", "description": "Container IRI to enumerate within. Omit for repository-wide." },
    "limit":  { "type": "integer", "minimum": 1, "maximum": 200, "default": 50 },
    "offset": { "type": "integer", "minimum": 0, "default": 0 }
  }
}
```

**Backing surface:** LDP container membership (`ldp:contains` + typed member
relations), walked from `parent` (or from the root when omitted); the FDP's
containment paging translated to offset/limit.

**Result:** a [page envelope](#33-the-result-envelope) whose `items` are
[Record objects](#36-the-record-object). Each item's `metadata` is a **summary**
(subject, types, title, key labels) rather than the full record — call
[`get_record`](#53-get_record) for the complete graph. `iri` and `types` are
always present so results are citable and filterable without a second call.

**Errors:** `invalid_argument` for an unknown `kind` slug or malformed `parent`
IRI; `not_found` if `parent` is not visible.

### 5.3 `get_record`

**Required.** The full metadata of one record, with the signposting/containment
links the FDP emits.

**Parameters:**

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["iri"],
  "properties": {
    "iri":    { "type": "string", "format": "iri" },
    "format": { "enum": ["jsonld", "turtle", "ntriples", "rdfxml"], "default": "jsonld" }
  }
}
```

**Backing surface:** content-negotiated LDP `GET` of the record IRI, including
`Link`-header parsing for LDP types, `ldp:constrainedBy`, and signposting
relations (`cite-as`, `describedby`, `type`, `license`, `author`, `item`,
`collection`).

**Result:** a single [Record object](#36-the-record-object) with the full
`metadata`. `links` is populated from the emitted `Link` header and containment
(`children` from `item`/`ldp:contains`, `parent` from `collection`/`dct:isPartOf`,
`constrained_by`, `cite_as`, `described_by`, `license`, `authors`).

**Errors:** `invalid_argument` (malformed IRI), `not_found` (see the 404 note in
[§3.4](#34-the-error-envelope)), `too_large`, `upstream_*`.

### 5.4 `get_schema`

**Optional** (capability `shapes`). The SHACL shape for a kind, so an agent knows
what a kind's fields mean and what to expect.

**Parameters:**

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["kind"],
  "properties": {
    "kind":   { "type": "string", "description": "Kind slug (see fdp_info.kinds)." },
    "format": { "enum": ["jsonld", "turtle", "ntriples", "rdfxml"], "default": "jsonld" }
  }
}
```

**Backing surface:** the published SHACL shape for the kind, resolved via the
`ldp:constrainedBy` link on records of that kind and/or the FDP's shape
document(s), fetched by content negotiation.

**Result:**

```json
{
  "kind": "dataset",
  "shape_iri": "https://fdp.example.org/schema/dataset",
  "targets": ["http://www.w3.org/ns/dcat#Dataset"],
  "properties": [
    { "path": "http://purl.org/dc/terms/title", "name": "title",
      "min_count": 1, "max_count": 1, "datatype": "http://www.w3.org/2001/XMLSchema#string",
      "node_kind": null, "description": "Human-readable title." }
  ],
  "shape": { /* the full shape as framed JSON-LD, or a string when format != jsonld */ }
}
```

- `properties` is a flattened, agent-friendly digest of the shape's
  `sh:property` constraints (path, cardinality, datatype/nodeKind, description);
  `shape` carries the complete shape for fidelity. The digest reflects the
  shape's **`sh:node` closure**: a bridge SHOULD follow `sh:node` references
  (resolving each composed shape on the FDP's own origin, bounded) so inherited
  constraints appear, not just the primary shape's direct properties
  (see `fdp-api-gaps.md` G-06). Properties are de-duplicated and path-ordered.

**Degradation:** when the FDP publishes no resolvable shape for the kind →
`unsupported` (capability `shapes`). `invalid_argument` for an unknown `kind`.

### 5.5 `search`

**Optional** (capability `search-api`). Keyword/faceted discovery within the FDP.

**Parameters:**

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["query"],
  "properties": {
    "query":   { "type": "string", "minLength": 1 },
    "filters": {
      "type": "object",
      "description": "Optional facet filters, e.g. {\"kind\": \"dataset\"}. Facet keys are FDP-defined; unknown keys are ignored by the FDP.",
      "additionalProperties": true
    },
    "limit":   { "type": "integer", "minimum": 1, "maximum": 200, "default": 50 },
    "offset":  { "type": "integer", "minimum": 0, "default": 0 }
  }
}
```

**Backing surface:** the FDP search API, probed on first use.

**Result:** a [page envelope](#33-the-result-envelope) whose `items` are
[Record objects](#36-the-record-object) in summary form, each optionally carrying
a `score` (number) and `snippet` (string) under an added `match` field when the
FDP supplies relevance data:

```json
{ "iri": "…", "types": ["…"], "title": "…", "kind": "dataset",
  "metadata": { /* summary */ }, "links": { /* … */ },
  "match": { "score": 4.2, "snippet": "…age at <em>diagnosis</em>…" } }
```

**Degradation:** no search endpoint → `unsupported` (capability `search-api`,
`alternative` pointing at `sparql_query`/`list_records`).

### 5.6 `sparql_query`

**Optional** (capability `sparql`). Structured, **read-only** SPARQL over the
FDP's public endpoint.

**Parameters:**

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["query"],
  "properties": {
    "query": { "type": "string", "minLength": 1, "description": "A SPARQL 1.1 query. Read-only forms only." }
  }
}
```

**Read-only enforcement (normative):** the bridge parses the query client-side
and **rejects any update/management form before any network call** — `INSERT`,
`DELETE`, `LOAD`, `CLEAR`, `CREATE`, `DROP`, `ADD`, `MOVE`, `COPY`, `INSERT
DATA`, `DELETE DATA`, `DELETE/INSERT WHERE`. Only `SELECT`, `ASK`, `CONSTRUCT`,
and `DESCRIBE` are forwarded. A rejected update returns `read_only_violation`. A
query that fails to parse returns `invalid_argument`. The bridge also rejects a
query containing a `SERVICE` (federation) clause with `invalid_argument`, because
`SERVICE` would make the FDP fetch from a third party — outside the strict-egress
posture (a conformant FDP is expected to reject it too).

**Backing surface:** the public SPARQL query endpoint. The FDP's own named-graph
projection / access control decides which graphs are visible (anonymous sees only
published, non-internal graphs); the bridge adds nothing.

> **Default graph may be empty — query named graphs.** An FDP that stores one
> named graph per record (e.g. FDPneo) projects records into named graphs, so the
> **default graph can be empty**: a bare `SELECT ?s ?p ?o WHERE { ?s ?p ?o }`
> then returns nothing even when the repository is full. Match named graphs
> explicitly — `SELECT ?s ?p ?o WHERE { GRAPH ?g { ?s ?p ?o } }`. This is the
> FDP's projection model, not a bridge behaviour (`fdp-api-gaps.md` G-07).

**Result:** shaped by query form.

- `SELECT` → SPARQL 1.1 Results JSON, wrapped:

  ```json
  { "form": "select",
    "head": { "vars": ["s", "p", "o"] },
    "results": { "bindings": [ { "s": { "type": "uri", "value": "…" } } ] } }
  ```

- `ASK` →

  ```json
  { "form": "ask", "boolean": true }
  ```

- `CONSTRUCT`/`DESCRIBE` → a graph, framed JSON-LD by default:

  ```json
  { "form": "construct", "graph": { "@context": {}, "@graph": [ /* … */ ] } }
  ```

**Degradation:** endpoint absent/disabled → `unsupported` (capability `sparql`).
FDP query error → `upstream_error` (with the FDP's message in `details` where
safe); over-cap result → `too_large`; slow query → `upstream_timeout`.

### 5.7 `get_access_conditions`

**Required.** "May I use this data, under what terms, and whom do I contact?" —
resolved from a record's own metadata.

**Parameters:**

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["iri"],
  "properties": { "iri": { "type": "string", "format": "iri" } }
}
```

**Backing surface:** the record's metadata (from an LDP `GET`): `dct:license`,
`dct:rights`, `dct:accessRights`, referenced ODRL policies/offers, and contact
points (`dcat:contactPoint`/`vcard`). The bridge MAY fetch a referenced license
or policy document **when that document lives on the FDP's own origin** (e.g. an
ODRL Offer served by the FDP at its own IRI) — that is in-origin, allowed egress
— to fill `policies[].metadata`/labels. It MUST NOT dereference an **off-origin**
license or policy IRI (e.g. `creativecommons.org`, a foreign resolver); for those
it reports the IRI and only the label the FDP itself included.

**Result:**

```json
{
  "iri": "https://fdp.example.org/dataset/42",
  "license": { "iri": "https://creativecommons.org/licenses/by/4.0/",
               "label": "CC BY 4.0", "open": true },
  "rights": [ { "iri": "…", "label": "…" } ],
  "access_rights": { "iri": "http://publications.europa.eu/resource/authority/access-right/RESTRICTED",
                     "label": "restricted" },
  "policies": [
    { "iri": "https://fdp.example.org/policy/1", "type": "http://www.w3.org/ns/odrl/2/Offer",
      "summary": "Permits read for authenticated academic users; contact required.",
      "metadata": { /* framed JSON-LD of the policy, when present */ } }
  ],
  "contacts": [
    { "name": "Data Access Committee", "email": "mailto:dac@example.org", "iri": null }
  ],
  "determinable": true
}
```

- Every field is best-effort from what the record states. `license.open` is
  `true`/`false`/`null` — `null` when openness cannot be judged from the IRI
  alone (no external lookup).
- `determinable` is `false` when the record carries **no** license, rights,
  policy, or contact — an honest "the metadata does not say," distinct from a
  fabricated permissive answer. This is still a successful result, not
  `unsupported`.

**Errors:** `invalid_argument`, `not_found`, `upstream_*`.

### 5.8 `list_data_services`

**Required.** Enumerate DCAT `DataService` records — "what can be queried or
invoked here, and how?" The seed of the capability profile (vision §5).
Discovery only; the bridge never dispatches to a service.

**Parameters:**

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "limit":  { "type": "integer", "minimum": 1, "maximum": 200, "default": 50 },
    "offset": { "type": "integer", "minimum": 0, "default": 0 }
  }
}
```

**Backing surface:** records typed `dcat:DataService` in the LDP hierarchy
(enumerated like any kind); their `dcat:endpointURL`, `dcat:endpointDescription`,
`dcat:servesDataset`, and `dct:conformsTo` claims.

**Result:** a [page envelope](#33-the-result-envelope) whose `items` add a
`service` block to the [Record object](#36-the-record-object):

```json
{ "iri": "…", "types": ["http://www.w3.org/ns/dcat#DataService"], "title": "Beacon 2 endpoint",
  "kind": "data-service", "metadata": { /* summary */ }, "links": { /* … */ },
  "service": {
    "endpoint_url": "https://beacon.example.org/api",
    "endpoint_descriptions": ["https://beacon.example.org/api/openapi.json"],
    "serves_datasets": ["https://fdp.example.org/dataset/42"],
    "conforms_to": ["http://en.wikipedia.org/wiki/Beacon_v2"]
  } }
```

An FDP with no `DataService` records returns an empty page (`items: []`,
`total: 0` where known) — a valid answer, **not** `unsupported`.

**Errors:** `upstream_*` only (enumeration failure).

### 5.9 `create_record`

**Write extension.** Create a new record as a member of a container (LDP `POST`).

```json
{
  "type": "object",
  "required": ["parent_iri", "body"],
  "properties": {
    "parent_iri": { "type": "string", "format": "iri", "description": "The container to add to (the root, a catalog, a dataset…)." },
    "body": { "type": "string", "description": "RDF describing exactly one primary subject: use <> for the new record, or a single typed IRI." },
    "media_type": { "enum": ["text/turtle", "application/ld+json", "application/rdf+xml", "application/n-triples"], "default": "text/turtle" },
    "slug": { "type": "string", "description": "Suggested last path segment (LDP Slug); the FDP may ignore it." }
  }
}
```

**Surface:** `POST <parent_iri>` with `Content-Type: <media_type>` (and `Slug`),
then a content-negotiated `GET` of the `Location` the FDP minted. The FDP
validates the body against the container's member shape.

**Pre-network validation (bridge-side, syntactic only):** the body MUST parse
as `media_type`, be non-empty, and name exactly one primary subject (the
relative `<>`, or one IRI subject; when several IRIs appear, exactly one of
them typed). Anything else is `invalid_argument` before any request is sent.
The body is then sent **verbatim** — the bridge never reserialises or edits it,
and never runs SHACL itself.

**Result:**

```json
{
  "iri": "https://fdp.example.org/dataset/42",
  "etag": "\"v1\"",
  "state": "DRAFT",
  "record": { /* Record object, §3.6 */ }
}
```

`state` is the record's publication state when the FDP serves one
(`fdp:metadataState`), else `null`; new records typically start as `DRAFT` —
use [`set_record_state`](#512-set_record_state) to publish.

**Errors:** `authentication_required` (anonymous session); `invalid_argument`
(bad IRI, unparseable/ambiguous body, `parent_iri` does not accept `POST` —
HTTP 405); `validation_failed` (422, SHACL report in `details`); `conflict`
(409, `slug` taken); `unsupported_media_type` (415); `upstream_unauthorized`
(401/403 — the FDP's decision, relayed); `not_found`; `upstream_*`.

### 5.10 `update_record`

**Write extension.** Modify one record under an `If-Match` precondition, either
by full replacement (`body`, LDP `PUT` — portable) or by a SPARQL update
(`patch`, LDP `PATCH` with `application/sparql-update` — optional capability
`ldp_patch`). Exactly one of `body` / `patch` MUST be given.

```json
{
  "type": "object",
  "required": ["iri", "if_match"],
  "properties": {
    "iri": { "type": "string", "format": "iri" },
    "if_match": { "type": "string", "description": "The etag from get_record for the version you read. Mandatory." },
    "body": { "type": "string", "description": "Full replacement RDF (same rules as create_record.body)." },
    "media_type": { "enum": ["text/turtle", "application/ld+json", "application/rdf+xml", "application/n-triples"], "default": "text/turtle" },
    "patch": { "type": "string", "description": "A SPARQL 1.1 update: INSERT DATA / DELETE DATA / DELETE WHERE / DELETE…INSERT…WHERE." }
  }
}
```

**Why `if_match` is mandatory.** The bridge is stateless and never manufactures
a precondition it did not observe: the agent MUST read the record
([`get_record`](#53-get_record) → `etag`) and present that validator. A stale
value is `precondition_failed` — re-read and retry. This makes lost updates
impossible by construction.

**Pre-network validation:** `body` as in §5.9. `patch` MUST parse as a SPARQL
update whose operations are only `INSERT DATA`, `DELETE DATA`, `DELETE WHERE`,
or `DELETE/INSERT … WHERE`; `LOAD` (the FDP would fetch an arbitrary URL on the
bridge's behalf — egress by proxy), `SERVICE`, `CLEAR`, `DROP`, `CREATE`,
`ADD`, `MOVE`, `COPY`, and any `GRAPH`/`WITH`/`USING` naming a graph outside the
FDP origin are `invalid_argument` before any request is sent.

**Surface:** `PUT <iri>` or `PATCH <iri>` with `If-Match`, then a `GET` of the
updated record.

**Result:**

```json
{ "iri": "…", "etag": "\"v2\"", "mode": "replace", "record": { /* §3.6 */ } }
```

`mode` is `"replace"` or `"patch"`.

**Degradation:** an FDP that answers `PATCH` with 405/415 lacks SPARQL-update
PATCH → `unsupported`, capability `ldp_patch`, `alternative` pointing at `body`
mode. The write itself is the probe (no extra round trip; nothing is changed
when it is refused).

**Errors:** `authentication_required`; `invalid_argument` (neither/both of
`body`/`patch`, empty `if_match`, bad body/update); `precondition_failed`
(412/428); `validation_failed` (422); `conflict` (409); `upstream_unauthorized`;
`not_found`; `upstream_*`.

### 5.11 `delete_record`

**Write extension.** Delete one record (LDP `DELETE`) under `If-Match`.

```json
{
  "type": "object",
  "required": ["iri", "if_match"],
  "properties": {
    "iri": { "type": "string", "format": "iri" },
    "if_match": { "type": "string" }
  }
}
```

**Result:** `{ "iri": "…", "deleted": true }`.

**Errors:** `authentication_required`; `invalid_argument`; `precondition_failed`;
`conflict` (409 — e.g. the FDP refuses to delete a non-empty container);
`upstream_unauthorized`; `not_found`; `upstream_*`.

### 5.12 `set_record_state`

**Write extension; optional capability `state_transition`.** Request a
publication-state transition for a record.

```json
{
  "type": "object",
  "required": ["iri", "to"],
  "properties": {
    "iri": { "type": "string", "format": "iri" },
    "to": { "enum": ["DRAFT", "PUBLISHED", "ARCHIVED"] }
  }
}
```

**Surface:** the bridge first `GET`s the record and follows its advertised
state-transition affordance (`Link` `rel="https://w3id.org/fdp/fdp-o#hasStateTransition"`,
which MUST be on the FDP origin), `POST`ing `{"to": "<state>"}` as JSON. Where
that affordance is absent or does not resolve, an implementation MAY try a
documented product convention ([§11](#11-reference-implementation-notes)) before
degrading. The FDP alone decides which transitions the caller may perform; the
bridge never inspects `fdp:allowedStateTransition` to *block* — it only relays
those hints in a `conflict`'s `details`.

**Result:**

```json
{ "iri": "…", "from_state": "DRAFT", "to_state": "PUBLISHED", "record": { /* §3.6 */ } }
```

`from_state` is `null` when the FDP did not report it; `record` is `null` when
the record is no longer visible to the presented credential after the
transition (e.g. unpublishing to `DRAFT`).

**Degradation:** no working transition endpoint → `unsupported`, capability
`state_transition`.

**Errors:** `authentication_required`; `invalid_argument` (unknown `to`);
`conflict` (409 — disallowed transition; `details` includes `current_state` and
`allowed_transitions` when known); `upstream_unauthorized`; `not_found`;
`upstream_*`.

---

## 6. Egress and safety (contract-level)

- A conforming bridge MUST restrict outbound HTTP to the configured FDP origin
  and MUST NOT dereference IRIs found in metadata (license IRIs, `endpointURL`,
  `endpointDescription`, `servesDataset`, external shapes).
- Every FDP call MUST carry a timeout and a response-size cap; exceeding them
  yields `upstream_timeout` / `too_large` rather than an unbounded wait or buffer.
- `sparql_query` MUST enforce read-only classification client-side
  ([§5.6](#56-sparql_query)) — rejection happens before the network call.
- Write tools MUST be absent unless the operator has explicitly enabled the
  write extension; MUST refuse anonymous sessions before any network call
  ([§3.2](#32-credentials-and-sessions)); MUST validate RDF bodies and SPARQL
  updates client-side ([§5.9](#59-create_record), [§5.10](#510-update_record)),
  refusing `LOAD`/`SERVICE` and off-origin graph names; MUST send the agent's
  body verbatim; and MUST require `if_match` from the caller rather than
  fetching it themselves. Every write is forwarded to, and decided by, the FDP.

## 7. Determinism and honesty

- Results MUST reflect only what the FDP returned for the presented credential.
- Absence is reported as absence (`determinable: false`, empty `items`,
  `total: null`) — never as a confident negative or a fabricated value.
- A capability the FDP lacks is reported as `unsupported`, never silently
  swallowed.

## 8. Non-goals

No mutation through `sparql_query` (writes are explicit, opt-in tools only —
ADR-0024); no bridge-side SHACL or dry-run validation; no MCP resources/prompts;
no multi-FDP or Index-level operations; no external dereferencing; no
capability-profile schema authoring; no access-request drafting. (Vision
increments B–D; ADR-0018 §5 as amended by ADR-0024.)

## 9. Conformance

An implementation conforms to contract version *X* when: every required tool is
implemented and returns the specified shapes; every optional tool either works or
returns the `unsupported` result with a capability name; all results validate
against the JSON Schemas in this document; and the safety rules of
[§6](#6-egress-and-safety-contract-level) hold. The `fdp-mcp` conformance suite
(`tests/conformance/`) validates tool results against these schemas.

## 10. Contract versioning

This contract is versioned independently of the `fdp-mcp` code, as
`MAJOR.MINOR.PATCH`:

- **MAJOR** — a breaking change to a tool name, a required parameter, or a result
  shape that an existing client could rely on.
- **MINOR** — a backward-compatible addition (a new optional tool, a new optional
  parameter, an added result field).
- **PATCH** — clarifications and editorial fixes with no shape change.

The current version is stated at the top of this document. Clients SHOULD tolerate
unknown added result fields (forward-compatible parsing). The changelog is
[§12](#12-changelog).

## 11. Reference-implementation notes

*Non-normative.* How specific FDP products realise the public surface, and where
they diverge — this is what informs the required/optional split and feeds
[`fdp-api-gaps.md`](fdp-api-gaps.md). Paths below are for orientation and are
verified against the FDP client layer as it is built (tasks 1.2/1.3); the
contract itself never depends on them.

### FDPneo

- **Routing.** Records live directly under the base URL (the LDP catch-all is
  mounted at `""`); the root FDP record is served at `{base}/`. Every *fixed*
  endpoint sits under one reserved segment, `/fdp-api/…`.
- **LDP read.** Content negotiation across `text/turtle` (default),
  `application/ld+json`, `application/rdf+xml`, `application/n-triples`
  (unsupported `Accept` → `406`, `*/*` → Turtle). Direct Containers serve
  `ldp:contains` + typed membership triples inline; `Prefer` minimisation
  supported. Strong `ETag`; `HEAD` mirrors `GET`. → backs `fdp_info`,
  `list_records`, `get_record`, `get_access_conditions`, `list_data_services`.
- **Kinds.** Runtime-defined. Publicly enumerable via
  `GET /fdp-api/resource-definitions` → `{ definitions: [ { slug, urlPrefix,
  name, schema, isRoot, children[] } ] }` (the `schema` field is the kind's SHACL
  shape IRI); single kind at `/fdp-api/resource-definitions/{slug}`. Default
  profile kinds: Repository(root) → Catalog → Dataset / DataService →
  Distribution — a default, not a contract fixture. → backs `fdp_info.kinds`,
  `get_schema` shape resolution. Records of a kind are enumerated via container
  `GET` membership, the `/fdp-api/page/{child}` extension (RDF + `X-FDP-Page-*`
  headers), or `GET /fdp-api/instances?class=<typeIRI>` (`{iri,label,type}` JSON,
  offset/limit paging with `X-FDP-Page-Total/Offset/Limit`). → backs
  `list_records`.
- **Signposting.** FAIR Signposting Level 1 `Link` relations on `GET`/`HEAD`:
  `cite-as`, `describedby` (one per RDF media type), `type`, `license`, `author`,
  `collection`, `item`; capped at 30 (surplus `item` trimmed). → backs
  `get_record.links`.
- **Shapes.** `GET /fdp-api/schemas` (list `{id,iri,target_class,version}`),
  `GET /fdp-api/schemas/{id}` (Turtle; `?composed=true` for the `sh:node`
  closure), and `GET /fdp-api/{prefix}/spec` (content-negotiated NodeShape graph);
  also reachable via each record's `ldp:constrainedBy` link. → backs
  `get_schema`.
- **Search.** `POST /fdp-api/search` (POST only; enabled by default, `404` when
  disabled). Body: `{ query, types[], license, from, to, language, offset,
  limit }` (offset/limit, `limit` capped at 100). Response: `{ items:
  [{recordIri, typeIri, title, description, license, state, updatedAt}], total,
  facets }` — supplies `total` (so `page.total` is populated) and `type`/`license`
  facets, but **no per-hit score/snippet** (so `match` is omitted). → backs
  `search`.
- **SPARQL.** `/fdp-api/sparql`: `GET ?query=` and `POST`
  (`application/sparql-query`, `application/sparql-update`, or form-encoded).
  SELECT/ASK returned whole (results JSON/XML/CSV/TSV by negotiation);
  CONSTRUCT/DESCRIBE streamed as an RDF graph. Named-graph projection is the
  access control — anonymous sees only published, non-internal graphs;
  `…/meta`, `…/audit`, and resource-definition graphs are always excluded.
  `SERVICE` (federation) clauses are rejected server-side. → backs `sparql_query`.
- **Access conditions.** `dct:license` → a license document
  (`GET /fdp-api/licenses/{id}`, descriptive only); `dct:rights` → an ODRL Offer
  (`GET /fdp-api/policies/{id}`, PEP-enforced; **Permission/Prohibition only, no
  Duties**). Both documents are served on the FDP's own origin, so the bridge may
  fetch them under strict egress. Contact points are ordinary record triples
  (`dcat:contactPoint`/vCard), not a dedicated endpoint. → backs
  `get_access_conditions`.
- **DataService.** Just another runtime kind (`urlPrefix: data-service`, shape
  `dcat:DataService` with `dcat:endpointURL` [min 1], `dcat:endpointDescription`,
  `dcat:servesDataset`); no special API. → backs `list_data_services`.
- **Credentials.** API keys are bearer tokens prefixed `fdpk_`, presented as
  `Authorization: Bearer fdpk_…`; the auth layer dispatches by prefix (`fdpk_` →
  API-key path, else JWT). The bridge forwards whatever bearer the client sent,
  verbatim, and does not parse it.

- **Write surface.** Full LDP: `POST` to a container honours `Slug` and
  answers `201` + `Location` + `ETag` (`409` on a taken slug, `405` on a
  non-container); `PUT`/`PATCH`/`DELETE` require `If-Match` (`428` missing,
  `412` stale); `PATCH` accepts only `application/sparql-update` (`415` +
  `Accept-Patch` otherwise); SHACL failures are `422` with
  `{code: "fdp.schema_violation", details: {shape, violations[]}}`, which the
  bridge relays as `validation_failed`. New LDP-created records start `DRAFT`.
- **State transitions.** `POST {base}/fdp-api/{record path}/state` with
  `{"to": "PUBLISHED"}` → `{record, from_state, to_state}`; `409` on a
  disallowed transition. FDPneo advertises
  `Link: <{record}/state>; rel="…#hasStateTransition"` but that URL does **not**
  currently resolve (gap G-08), so the bridge falls back to the `/fdp-api/`
  convention (G-09) after trying the advertised link. The served record carries
  `fdp:metadataState` and informational `fdp:allowedStateTransition` literals.

### Java reference implementation

Divergences that drive the required/optional split and `fdp-api-gaps.md`:

- **No search endpoint** — `search` degrades to `unsupported` (capability
  `search-api`). This is the canonical optional-tool case.
- **Containment-only LDP with no PATCH** (a hand-rolled REST CRUD API rather than
  full LDP). Content-negotiated record `GET` is the common ground the required
  tools rely on. For the write extension: `update_record` in `patch` mode
  degrades to `unsupported` (`ldp_patch`); publication state is changed under
  `…/meta/state` with a different request shape, which the bridge does not
  attempt — `set_record_state` degrades to `unsupported` (`state_transition`)
  unless the RI advertises a `hasStateTransition` link (G-09).
- **Shape-discovery mechanics differ** — resolving a kind to its shape is
  under-specified across implementations; where the bridge cannot resolve a
  kind's shape, `get_schema` degrades to `unsupported` (capability `shapes`).
- Publication state (`DRAFT|PUBLISHED|ARCHIVED`) and per-user API keys exist in
  both, so the credential-passthrough and 404-hides-drafts behaviours are common.

Each divergence that blocks or degrades a tool has a corresponding
`fdp-api-gaps.md` entry (seeded there; expanded in task 1.3 as fixtures for both
implementations are written).

## 12. Changelog

- **1.1.0-draft** (task 5.1, ADR-0024) — opt-in **write extension**: four tools
  (`create_record`, `update_record`, `delete_record`, `set_record_state`,
  §5.9–§5.12); `etag` on the Record object (§3.6); error codes
  `precondition_failed`, `conflict`, `validation_failed`,
  `unsupported_media_type`, `authentication_required` (§3.4); capabilities
  `ldp_patch`, `state_transition` (§3.5); write safety rules (§6). Backward
  compatible (MINOR): the read surface is unchanged and the write tools are
  absent unless enabled.
- **1.0.0-draft** (task 1.1) — initial contract: eight read-only tools, common
  envelopes (result/page/error/unsupported), Record object, pagination, JSON-LD
  framing rules, required/optional split, versioning policy.
