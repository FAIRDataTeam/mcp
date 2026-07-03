"""Result shaping: JSON-LD framing, pagination, and the error envelope.

Turns RDF and FDP HTTP responses into the JSON shapes the tool-surface contract
(``docs/mcp-tool-surface.md``) specifies: framed JSON-LD by default with raw
serialisations on request, page envelopes, the structured error/``unsupported``
envelope, and IRIs always present so agents can cite.

Implemented from task 1.1 onward (once the contract is written); this module is
a placeholder for the scaffold.
"""

from __future__ import annotations
