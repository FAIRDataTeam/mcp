"""Conformance: every tool result validates against the tool-surface schemas.

Runs each of the eight tools over the shared respx-mocked FDPneo surface and
validates the JSON against the schemas in ``schemas.py`` (the machine-readable
form of ``docs/mcp-tool-surface.md``). Also validates the error and unsupported
envelopes. Marked ``conformance``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
import respx
from jsonschema import validate

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import (
    AuthenticationRequiredError,
    FdpConflictError,
    FdpNotFoundError,
    FdpPreconditionError,
    FdpUnsupportedError,
    FdpUnsupportedMediaTypeError,
    FdpValidationError,
)
from fdp_mcp.shaping import result_from_error
from fdp_mcp.tools import (
    create_record,
    delete_record,
    fdp_info,
    get_access_conditions,
    get_record,
    get_schema,
    list_data_services,
    list_records,
    search,
    set_record_state,
    sparql_query,
    update_record,
)
from tests.conformance import schemas
from tests.conftest import NEW_DATASET, NEW_DATASET_TTL, WriteSurface

pytestmark = pytest.mark.conformance

BASE = "https://fdp.example.org"


async def test_fdp_info_conforms(
    fdp_settings: FdpMcpSettings, register_fdpneo: Callable[..., None]
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo(mock)
        async with FdpClient(fdp_settings) as client:
            result = await fdp_info.handle(client, fdp_settings)
    validate(result, schemas.FDP_INFO)


async def test_get_record_conforms(
    fdp_settings: FdpMcpSettings, register_fdpneo: Callable[..., None]
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo(mock)
        async with FdpClient(fdp_settings) as client:
            result = await get_record.handle(client, iri=f"{BASE}/dataset/1")
    validate(result, schemas.RECORD)


async def test_list_records_conforms(
    fdp_settings: FdpMcpSettings, register_fdpneo: Callable[..., None]
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo(mock)
        async with FdpClient(fdp_settings) as client:
            result = await list_records.handle(client, parent=f"{BASE}/catalog/1")
    validate(result, schemas.LIST_RECORDS)


async def test_get_schema_conforms(
    fdp_settings: FdpMcpSettings, register_fdpneo: Callable[..., None]
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo(mock)
        async with FdpClient(fdp_settings) as client:
            result = await get_schema.handle(client, kind="dataset")
    validate(result, schemas.GET_SCHEMA)


async def test_search_conforms(
    fdp_settings: FdpMcpSettings, register_fdpneo: Callable[..., None]
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo(mock)
        async with FdpClient(fdp_settings) as client:
            result = await search.handle(client, fdp_settings, query="dataset")
    validate(result, schemas.SEARCH)


@pytest.mark.parametrize(
    "query",
    ["SELECT * WHERE { ?s ?p ?o }", "ASK { ?s ?p ?o }"],
)
async def test_sparql_query_conforms(
    query: str, fdp_settings: FdpMcpSettings, register_fdpneo: Callable[..., None]
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo(mock)
        async with FdpClient(fdp_settings) as client:
            result = await sparql_query.handle(client, fdp_settings, query=query)
    validate(result, schemas.SPARQL)


async def test_get_access_conditions_conforms(
    fdp_settings: FdpMcpSettings, register_fdpneo: Callable[..., None]
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo(mock)
        async with FdpClient(fdp_settings) as client:
            result = await get_access_conditions.handle(client, iri=f"{BASE}/dataset/1")
    validate(result, schemas.ACCESS_CONDITIONS)


async def test_list_data_services_conforms(
    fdp_settings: FdpMcpSettings, register_fdpneo: Callable[..., None]
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo(mock)
        async with FdpClient(fdp_settings) as client:
            result = await list_data_services.handle(client)
    validate(result, schemas.LIST_DATA_SERVICES)
    # The DataService item carries the capability-profile `service` block.
    assert "service" in result["items"][0]


def test_error_and_unsupported_envelopes_conform() -> None:
    validate(result_from_error("get_record", FdpNotFoundError("x")), schemas.ERROR)
    validate(
        result_from_error("search", FdpUnsupportedError("search-api", "no")), schemas.UNSUPPORTED
    )


# --- write surface (contract 1.1, ADR-0024) ----------------------------------


async def test_write_tool_results_conform(
    fdp_settings: FdpMcpSettings,
    register_fdpneo: Callable[..., None],
    register_fdpneo_write: Callable[[respx.MockRouter], None],
    write_surface: WriteSurface,
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo(mock)
        register_fdpneo_write(mock)
        async with FdpClient(fdp_settings) as client:
            created = await create_record.handle(
                client, fdp_settings, parent_iri=f"{BASE}/catalog/1", body=NEW_DATASET_TTL
            )
            validate(created, schemas.CREATE_RECORD)
            updated = await update_record.handle(
                client,
                fdp_settings,
                iri=NEW_DATASET,
                if_match=created["etag"],
                body=NEW_DATASET_TTL,
            )
            validate(updated, schemas.UPDATE_RECORD)
            state = await set_record_state.handle(client, iri=NEW_DATASET, to="PUBLISHED")
            validate(state, schemas.SET_RECORD_STATE)
            deleted = await delete_record.handle(client, iri=NEW_DATASET, if_match=updated["etag"])
            validate(deleted, schemas.DELETE_RECORD)
    assert write_surface.exists is False


@pytest.mark.parametrize(
    "exc",
    [
        FdpPreconditionError("x"),
        FdpConflictError("x", details={"from": "DRAFT", "to": "ARCHIVED"}),
        FdpValidationError("x", details={"shape": "s", "violations": []}),
        FdpUnsupportedMediaTypeError("x"),
        AuthenticationRequiredError("x"),
    ],
)
def test_write_error_envelopes_conform(exc: Exception) -> None:
    from fdp_mcp.fdp.errors import FdpError

    assert isinstance(exc, FdpError)
    validate(result_from_error("update_record", exc), schemas.ERROR)
