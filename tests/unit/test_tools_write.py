"""Unit tests for the write tools (task 5.3) over the stateful mocked FDPneo surface."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
import respx

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import (
    FdpError,
    FdpNotFoundError,
    FdpUnauthorizedError,
    InvalidArgumentError,
)
from fdp_mcp.shaping import result_from_error
from fdp_mcp.tools import create_record, delete_record, set_record_state, update_record
from tests.conftest import BASE, NEW_DATASET, NEW_DATASET_TTL, WriteSurface

Register = Callable[[respx.MockRouter], None]


def _settings() -> FdpMcpSettings:
    return FdpMcpSettings(_env_file=None, FDP_BASE_URL=BASE, enable_write=True)  # type: ignore[call-arg]


async def test_create_record_returns_iri_etag_state_and_record(
    register_fdpneo_write: Register, write_surface: WriteSurface
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo_write(mock)
        async with FdpClient(_settings()) as client:
            result = await create_record.handle(
                client, _settings(), parent_iri=f"{BASE}/catalog/1", body=NEW_DATASET_TTL
            )
    assert result["iri"] == NEW_DATASET
    assert result["etag"] == write_surface.etag
    assert result["state"] == "DRAFT"
    assert result["record"]["kind"] == "dataset"
    assert result["record"]["etag"] == write_surface.etag


async def test_create_record_validates_body_before_network(
    register_fdpneo_write: Register, write_surface: WriteSurface
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo_write(mock)
        async with FdpClient(_settings()) as client:
            with pytest.raises(InvalidArgumentError):
                await create_record.handle(
                    client, _settings(), parent_iri=f"{BASE}/catalog/1", body="not rdf"
                )
    assert write_surface.requests == []


async def test_create_record_shacl_violation_is_validation_failed_with_details(
    register_fdpneo_write: Register,
) -> None:
    body = NEW_DATASET_TTL.replace("Dataset Two", "INVALID")
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo_write(mock)
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpError) as info:
                await create_record.handle(
                    client, _settings(), parent_iri=f"{BASE}/catalog/1", body=body
                )
    result = result_from_error("create_record", info.value)
    assert result["error"]["code"] == "validation_failed"
    assert result["error"]["details"]["violations"][0]["result_path"].endswith("title")


async def test_update_record_requires_exactly_one_of_body_or_patch() -> None:
    async with FdpClient(_settings()) as client:
        with pytest.raises(InvalidArgumentError, match="exactly one"):
            await update_record.handle(client, _settings(), iri=NEW_DATASET, if_match='"v1"')
        with pytest.raises(InvalidArgumentError, match="exactly one"):
            await update_record.handle(
                client, _settings(), iri=NEW_DATASET, if_match='"v1"', body="x", patch="y"
            )
        with pytest.raises(InvalidArgumentError, match="if_match"):
            await update_record.handle(client, _settings(), iri=NEW_DATASET, if_match="", body="x")


async def test_update_record_replace_then_patch(
    register_fdpneo_write: Register, write_surface: WriteSurface
) -> None:
    write_surface.exists = True
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo_write(mock)
        async with FdpClient(_settings()) as client:
            replaced = await update_record.handle(
                client, _settings(), iri=NEW_DATASET, if_match='"v0"', body=NEW_DATASET_TTL
            )
            assert replaced["mode"] == "replace"
            assert replaced["etag"] == '"v1"'
            patched = await update_record.handle(
                client,
                _settings(),
                iri=NEW_DATASET,
                if_match=replaced["etag"],
                patch="INSERT DATA { <https://fdp.example.org/dataset/2> "
                "<http://purl.org/dc/terms/description> 'd' }",
            )
    assert patched["mode"] == "patch"
    assert patched["etag"] == '"v2"'


async def test_update_record_stale_etag_is_precondition_failed(
    register_fdpneo_write: Register, write_surface: WriteSurface
) -> None:
    write_surface.exists = True
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo_write(mock)
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpError) as info:
                await update_record.handle(
                    client, _settings(), iri=NEW_DATASET, if_match='"old"', body=NEW_DATASET_TTL
                )
    assert result_from_error("update_record", info.value)["error"]["code"] == "precondition_failed"


async def test_update_record_patch_rejects_load_before_network(
    register_fdpneo_write: Register, write_surface: WriteSurface
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo_write(mock)
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpError) as info:
                await update_record.handle(
                    client,
                    _settings(),
                    iri=NEW_DATASET,
                    if_match='"v0"',
                    patch="LOAD <http://evil.example/> INTO GRAPH <https://fdp.example.org/g>",
                )
    assert result_from_error("update_record", info.value)["error"]["code"] == "invalid_argument"
    assert write_surface.requests == []


async def test_update_record_patch_unsupported_degrades() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.patch(NEW_DATASET).mock(return_value=httpx.Response(405))
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpError) as info:
                await update_record.handle(
                    client,
                    _settings(),
                    iri=NEW_DATASET,
                    if_match='"v0"',
                    patch="INSERT DATA { <a:b> <a:c> 'd' }",
                )
    result = result_from_error("update_record", info.value)
    assert result["unsupported"]["capability"] == "ldp_patch"


async def test_delete_record(register_fdpneo_write: Register, write_surface: WriteSurface) -> None:
    write_surface.exists = True
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo_write(mock)
        async with FdpClient(_settings()) as client:
            result = await delete_record.handle(client, iri=NEW_DATASET, if_match='"v0"')
    assert result == {"iri": NEW_DATASET, "deleted": True}
    assert write_surface.exists is False


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "upstream_unauthorized"),
        (403, "upstream_unauthorized"),
        (404, "not_found"),
        (409, "conflict"),
        (428, "precondition_failed"),
    ],
)
async def test_delete_record_maps_fdp_statuses(status: int, code: str) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.delete(NEW_DATASET).mock(return_value=httpx.Response(status))
        async with FdpClient(_settings()) as client:
            with pytest.raises((FdpUnauthorizedError, FdpNotFoundError, FdpError)) as info:
                await delete_record.handle(client, iri=NEW_DATASET, if_match='"v0"')
    assert result_from_error("delete_record", info.value)["error"]["code"] == code


async def test_set_record_state_publishes(
    register_fdpneo_write: Register, write_surface: WriteSurface
) -> None:
    write_surface.exists = True
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo_write(mock)
        async with FdpClient(_settings()) as client:
            result = await set_record_state.handle(client, iri=NEW_DATASET, to="PUBLISHED")
    assert result["from_state"] == "DRAFT"
    assert result["to_state"] == "PUBLISHED"
    assert result["record"]["iri"] == NEW_DATASET


async def test_set_record_state_conflict_carries_hints(
    register_fdpneo_write: Register, write_surface: WriteSurface
) -> None:
    write_surface.exists = True
    with respx.mock(assert_all_called=False) as mock:
        register_fdpneo_write(mock)
        async with FdpClient(_settings()) as client:
            with pytest.raises(FdpError) as info:
                await set_record_state.handle(client, iri=NEW_DATASET, to="ARCHIVED")
    result = result_from_error("set_record_state", info.value)
    assert result["error"]["code"] == "conflict"
    assert result["error"]["details"]["allowed_transitions"] == ["PUBLISHED"]
