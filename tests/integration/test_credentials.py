"""Integration: forwarded-credential visibility + no-token-in-logs (task 3.1).

The bridge holds no authorization of its own: an anonymous session and one
carrying a forwarded API key see exactly what the FDP returns for each. Here the
mocked FDP returns 404 without a bearer and 200 with the right one — so results
differ purely by the credential the bridge forwards — while the bridge's logs
never contain the token. Marked ``integration``.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from pydantic import SecretStr

from fdp_mcp.config import FdpMcpSettings
from fdp_mcp.fdp.client import FdpClient
from fdp_mcp.fdp.errors import FdpNotFoundError
from fdp_mcp.log import configure_logging, get_logger
from fdp_mcp.tools import get_record

BASE = "https://fdp.example.org"
SECRET = "fdpk_super-secret-key"
RESTRICTED = f"{BASE}/dataset/restricted"

_RESTRICTED_TTL = f"""
@prefix dcat: <http://www.w3.org/ns/dcat#> .
<{RESTRICTED}> a dcat:Dataset .
"""


def _settings() -> FdpMcpSettings:
    return FdpMcpSettings(_env_file=None, FDP_BASE_URL=BASE)  # type: ignore[call-arg]


def _visibility_responder(request: httpx.Request) -> httpx.Response:
    """FDP-side visibility: the record is shown only to the right bearer."""
    if request.headers.get("authorization") == f"Bearer {SECRET}":
        return httpx.Response(200, text=_RESTRICTED_TTL, headers={"content-type": "text/turtle"})
    return httpx.Response(404)


async def test_credential_forwarding_changes_visibility() -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(RESTRICTED).mock(side_effect=_visibility_responder)

        async with FdpClient(_settings()) as anonymous:
            with pytest.raises(FdpNotFoundError):
                await get_record.handle(anonymous, iri=RESTRICTED)

        async with FdpClient(_settings(), credential=SecretStr(SECRET)) as authed:
            record = await get_record.handle(authed, iri=RESTRICTED)
    assert record["iri"] == RESTRICTED


async def test_forwarded_token_never_appears_in_logs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("debug")
    logger = get_logger("test.credentials")
    with respx.mock(assert_all_called=False) as mock:
        mock.get(RESTRICTED).mock(side_effect=_visibility_responder)
        async with FdpClient(_settings(), credential=SecretStr(SECRET)) as authed:
            await get_record.handle(authed, iri=RESTRICTED)
            # Even if a handler logs the session context or an auth header, the
            # structlog redaction processor must strip the secret.
            logger.info(
                "handled_request",
                authorization=f"Bearer {SECRET}",
                credential=SecretStr(SECRET),
            )
    out = capsys.readouterr().out
    assert SECRET not in out
    assert "redacted" in out
