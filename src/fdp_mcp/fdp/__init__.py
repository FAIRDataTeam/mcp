"""FDP client layer.

Async ``httpx``-based access to the *public* FDP surface only: content-negotiated
LDP GET (``ldp``), the ``/sparql`` endpoint (``sparql``), the search API
(``search``), and published SHACL shapes (``shapes``). A single shared client
pins outbound requests to ``FDP_BASE_URL``'s origin (strict egress, ADR-0018 §3);
nothing here ever dereferences an arbitrary IRI.

Modules are implemented across Phase 1 (tasks 1.2 and 1.3).
"""

from __future__ import annotations
