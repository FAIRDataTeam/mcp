"""Search access (task 1.3).

The FDP search API where available. Support is capability-probed on first use;
when the target FDP lacks a search endpoint (e.g. some Java reference-impl
deployments) the tool degrades explicitly to the contract's ``unsupported``
result and the gap is recorded in ``docs/fdp-api-gaps.md`` — never a fake answer.
"""

from __future__ import annotations
