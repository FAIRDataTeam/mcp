"""Scaffold smoke test (task 0.1).

Confirms the two things a fresh checkout must get right before any real work:
settings load from the environment (with ``FDP_BASE_URL`` as the sole required
one), and the package's modules import cleanly.
"""

from __future__ import annotations

import importlib

import pytest

from fdp_mcp.config import FdpMcpSettings


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``FDP_BASE_URL`` is read from the environment; other knobs default."""
    monkeypatch.setenv("FDP_BASE_URL", "https://fdp.example.org")
    settings = FdpMcpSettings()  # type: ignore[call-arg]  # filled from env

    assert str(settings.fdp_base_url).rstrip("/") == "https://fdp.example.org"
    assert settings.transport == "streamable-http"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.log_level == "info"


def test_fdp_base_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no ``FDP_BASE_URL`` and no ``.env``, construction fails loudly."""
    monkeypatch.delenv("FDP_BASE_URL", raising=False)
    with pytest.raises(ValueError):
        FdpMcpSettings(_env_file=None)  # type: ignore[call-arg]  # required field missing


def test_fdp_origin_is_the_egress_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """The egress origin is derived scheme+host+port only — no path."""
    monkeypatch.setenv("FDP_BASE_URL", "https://fdp.example.org:8443/repository/")
    settings = FdpMcpSettings()  # type: ignore[call-arg]  # filled from env
    assert settings.fdp_origin == "https://fdp.example.org:8443"


@pytest.mark.parametrize(
    "module",
    [
        "fdp_mcp",
        "fdp_mcp.config",
        "fdp_mcp.server",
        "fdp_mcp.shaping",
        "fdp_mcp.fdp",
        "fdp_mcp.fdp.ldp",
        "fdp_mcp.fdp.sparql",
        "fdp_mcp.fdp.search",
        "fdp_mcp.fdp.shapes",
        "fdp_mcp.tools",
    ],
)
def test_modules_import_cleanly(module: str) -> None:
    """Every scaffolded module imports without side effects."""
    assert importlib.import_module(module) is not None
