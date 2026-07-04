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
from fdp_mcp.fdp.errors import FdpNotFoundError, FdpUnsupportedError
from fdp_mcp.shaping import result_from_error
from fdp_mcp.tools import (
    fdp_info,
    get_access_conditions,
    get_record,
    get_schema,
    list_data_services,
    list_records,
    search,
    sparql_query,
)
from tests.conformance import schemas

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
