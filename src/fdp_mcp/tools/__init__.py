"""Tool handlers.

One module per v1 tool (``fdp_info``, ``list_records``, ``get_record``,
``get_schema``, ``search``, ``sparql_query``, ``get_access_conditions``,
``list_data_services``). Handlers are thin adapters over the ``fdp`` client
layer: they translate, paginate, and shape results per the contract in
``docs/mcp-tool-surface.md`` — no business logic, no caching beyond per-session
memoization.

Modules are implemented across Phase 2 (tasks 2.1 and 2.2).
"""

from __future__ import annotations
