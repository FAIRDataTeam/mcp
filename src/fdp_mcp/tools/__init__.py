"""Tool handlers.

One module per v1 tool (``fdp_info``, ``list_records``, ``get_record``,
``get_schema``, ``search``, ``sparql_query``, ``get_access_conditions``,
``list_data_services``). Handlers are thin adapters over the ``fdp`` client
layer: they translate, paginate, and shape results per the contract in
``docs/mcp-tool-surface.md`` — no business logic, no caching beyond per-session
memoization.

The opt-in write tools (``create_record``, ``update_record``, ``delete_record``,
``set_record_state``; ADR-0024, contract §5.9-§5.12) follow the same pattern
and are registered only when ``FDP_MCP_ENABLE_WRITE`` is set.
"""

from __future__ import annotations
