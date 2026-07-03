"""SPARQL access (task 1.3).

POSTs to the public ``/sparql`` endpoint. **Read-only query forms only** —
update forms are parsed and rejected client-side before any network call
(CLAUDE.md ground rule, ADR-0018 §5). Result handling for SELECT (JSON) and
CONSTRUCT/DESCRIBE (graph).
"""

from __future__ import annotations
