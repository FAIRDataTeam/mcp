"""LDP access and root discovery (task 1.2).

Content-negotiated GET of records and containers (``text/turtle``,
``application/ld+json``), Link-header parsing (LDP types, ``constrainedBy``,
signposting relations), container paging, and root discovery that enumerates the
resource kinds a given FDP exposes (kinds are runtime-defined per FDP — never
hard-code the DCAT five). Hosts the strict-egress ``httpx.AsyncClient``.
"""

from __future__ import annotations
