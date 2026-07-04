# Connect your agent to a FAIR Data Point

`fdp-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server
that makes **any spec-compliant FAIR Data Point (FDP)** consumable by an AI
agent. Point it at an FDP, connect an MCP client, and converse with the
repository's metadata — datasets, schemas, licenses, access conditions —
grounded in real records and cited by IRI.

This guide gets you from zero to a working conversation, then walks the
three-minute demo. It assumes nothing about which FDP you target: the bridge
uses only the public FDP surface, so it works against FDPneo **and** the Java
reference implementation with no server-side changes.

- [1. One-command bring-up](#1-one-command-bring-up)
- [2. Connect an MCP client](#2-connect-an-mcp-client)
- [3. Forwarding an API key](#3-forwarding-an-api-key)
- [4. The tools](#4-the-tools)
- [5. The three-minute demo](#5-the-three-minute-demo)
- [6. Wiring it into an FDPneo deployment](#6-wiring-it-into-an-fdpneo-deployment)
- [7. Troubleshooting](#7-troubleshooting)

---

## 1. One-command bring-up

The only required setting is `FDP_BASE_URL` — the FDP you want to expose.

```bash
docker run --rm -p 8080:8000 \
  -e FDP_BASE_URL=https://your-fdp.example.org \
  ghcr.io/<org>/fdp-mcp:latest
```

The bridge serves the **streamable-HTTP** MCP transport at
`http://localhost:8080/mcp` and a liveness probe at `http://localhost:8080/healthz`.

Default network posture: the container binds `0.0.0.0` inside the container and
speaks **only** to `FDP_BASE_URL`'s origin — it never dereferences any other
host. It is read-only and adds no authorization of its own.

### From source (for development)

```bash
uv sync
FDP_BASE_URL=https://your-fdp.example.org uv run fdp-mcp
```

Set `FDP_MCP_TRANSPORT=stdio` to run over stdio instead (for desktop clients
that launch the server as a subprocess — see below).

---

## 2. Connect an MCP client

### Claude Desktop (stdio)

Claude Desktop launches MCP servers as local subprocesses over stdio. Add an
entry to its `claude_desktop_config.json`
(*Settings → Developer → Edit Config*):

```jsonc
{
  "mcpServers": {
    "fdp": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "FDP_BASE_URL=https://your-fdp.example.org",
        "-e", "FDP_MCP_TRANSPORT=stdio",
        "ghcr.io/<org>/fdp-mcp:latest"
      ]
    }
  }
}
```

`-i` keeps stdin open (stdio transport needs it); `FDP_MCP_TRANSPORT=stdio`
switches the bridge off the HTTP transport. Restart Claude Desktop; the FDP
tools appear in the tool menu.

Running from a source checkout instead of Docker:

```jsonc
{
  "mcpServers": {
    "fdp": {
      "command": "uv",
      "args": ["run", "fdp-mcp"],
      "env": {
        "FDP_BASE_URL": "https://your-fdp.example.org",
        "FDP_MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

### Generic MCP clients (streamable-HTTP)

Any client that speaks the streamable-HTTP transport connects to the URL from
step 1:

```
http://localhost:8080/mcp
```

### MCP Inspector (to poke at the tools directly)

```bash
npx @modelcontextprotocol/inspector
```

Point it at `http://localhost:8080/mcp` (streamable-HTTP), or launch the stdio
command above. Inspector lists the eight tools and lets you call them by hand — a
quick way to confirm a target FDP before wiring up a chat client.

---

## 3. Forwarding an API key

The bridge is **anonymous by default**: it calls the FDP with no credentials and
you see exactly what that FDP shows the public. To see restricted records, an
MCP client supplies your FDP API key as the session's bearer token; the bridge
forwards it verbatim to the FDP on that session's requests only. It is held in
memory for the session, and **never stored, cached, or logged**.

FDP API keys are bearer tokens (FDPneo mints them with an `fdpk_` prefix). How
you attach the bearer depends on the client — for streamable-HTTP clients it is
the `Authorization: Bearer <key>` header on the MCP session. The FDP's own
authorization (publication state, ODRL policy) then decides what you can see; the
bridge neither widens nor narrows it.

---

## 4. The tools

| Tool | Ask it… |
|---|---|
| `fdp_info` | "What is this repository, who runs it, and what kinds of records does it hold?" |
| `list_records` | "List the catalogs / datasets (optionally under a given parent)." |
| `get_record` | "Show the full metadata for this IRI." |
| `get_schema` | "What fields does a dataset here have, and what do they mean?" |
| `search` | "Find records about X." *(optional — degrades if the FDP has no search API)* |
| `sparql_query` | "Run this read-only SPARQL query." *(optional; update forms are refused)* |
| `get_access_conditions` | "May I use this dataset, under what licence, and whom do I contact?" |
| `list_data_services` | "What services (e.g. query endpoints) does this repository expose?" |

Every record-shaped result carries its `iri`, so the agent cites holdings
instead of inventing them. A tool the target FDP can't back returns a structured
`unsupported` result (with an `alternative`), never a fabricated answer.

---

## 5. The three-minute demo

The scripted golden path (from the
[agent-consumption vision](../../server/docs/architecture/agent-consumption-vision.md) §6).
Point the bridge at a live FDP, connect Claude (or any MCP client), and:

1. **n = 1 — converse with one repository.** Ask:
   > *"What datasets does this repository hold about &lt;topic&gt;? Which are
   > openly licensed? How would I get access to the restricted ones?"*

   The agent answers from `search` (or `list_records`), `get_record`, and
   `get_access_conditions` — with IRIs as citations and no hallucinated holdings.

2. **Structure — use the schema.** Ask a question that needs the shape:
   > *"Which registries here record age at diagnosis?"*

   The agent reads the SHACL shape via `get_schema`, then queries with
   `sparql_query`.

3. **Reach — re-point at a different FDP.** Stop the container and start it again
   with `FDP_BASE_URL` set to a **Java reference-implementation** FDP from the
   existing network:

   ```bash
   docker run --rm -p 8080:8000 \
     -e FDP_BASE_URL=https://a-different-fdp.example.org \
     ghcr.io/<org>/fdp-mcp:latest
   ```

   Have the same conversation. Zero code changes — the moment that shows this is
   an ecosystem capability, not one product's feature. Where the second FDP lacks
   a capability (e.g. no search API), the corresponding tool degrades explicitly
   and the agent routes around it.

4. **Network (act two, later).** The Index-level MCP — discovery across sources
   and query dispatch/aggregation over an FDP Index — is a later increment
   (vision §8, increment C). v1 is one FDP at a time.

---

## 6. Wiring it into an FDPneo deployment

So an FDPneo install comes up agent-ready by default (ADR-0018 §6), add the
bridge as a service in the deployment's compose profile, on the same network as
the FDP container:

```yaml
# add to the FDPneo deploy profile's compose file
services:
  fdp-mcp:
    image: ghcr.io/<org>/fdp-mcp:latest
    environment:
      # the FDP container's in-network URL
      FDP_BASE_URL: http://server:8000
    ports:
      - "8080:8000"
    depends_on:
      - server
    restart: unless-stopped
```

Operators of a non-FDPneo FDP run the same image pointed at their instance — one
`docker run` with `FDP_BASE_URL` (step 1).

> This snippet lives here as the reference; adopting it into the server repo's
> standard deploy profiles is the coordinating change tracked in server
> `TASKS.md` Phase 19.

---

## 7. Troubleshooting

- **A tool returns `{"unsupported": …}`.** The target FDP doesn't expose that
  capability (commonly `search-api` on the Java reference implementation, or
  `sparql`). Use the suggested `alternative`; the gap is expected, not an error.
- **`{"error": {"code": "not_found"}}` for a record you know exists.** A
  spec-compliant FDP returns 404 both for missing records and for ones hidden
  from you (drafts, policy). Supplying an API key (step 3) may reveal it.
- **`{"error": {"code": "invalid_argument"}}` on `get_record`.** The IRI is
  malformed or points outside the target FDP's origin — the bridge only fetches
  from `FDP_BASE_URL`.
- **`upstream_timeout` / `too_large`.** The FDP was slow or the response exceeded
  the size cap; tune `FDP_MCP_FDP_TIMEOUT_SECONDS` / `FDP_MCP_FDP_MAX_RESPONSE_BYTES`.
- **Health check:** `curl http://localhost:8080/healthz` should return
  `{"status":"ok"}`.
