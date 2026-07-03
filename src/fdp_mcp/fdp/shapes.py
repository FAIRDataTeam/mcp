"""SHACL shape retrieval (task 1.3).

Retrieves the published SHACL shape for a resource kind via ``constrainedBy``
links / published shape endpoints, so ``get_schema`` can tell an agent what a
kind's fields mean and what to expect.
"""

from __future__ import annotations
