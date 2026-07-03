# Integration tests

Tests that exercise the bridge against a **live FDP** launched with
`testcontainers` (an FDPneo instance; a Java reference-implementation target
where feasible). The full golden-path session — initialize → list tools →
search → get_record → get_access_conditions → get_schema → sparql_query — and
the anonymous-vs-forwarded-API-key visibility comparison live here.

Populated in task 3.1. Marked `@pytest.mark.integration`.
