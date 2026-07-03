"""Bridge configuration.

Settings are layered: built-in defaults, then a ``.env`` file (if present), then
environment variables (which override the file). ``FDP_BASE_URL`` is the only
required setting — the single target FDP this bridge instance speaks to
(ADR-0018 §1). Everything else has a safe default.

Two deliberate omissions, per the ground rules in ``CLAUDE.md``:

* There is **no credential setting.** A client-supplied FDP API key is forwarded
  per session and lives in memory only; it is never read from configuration,
  stored, or logged (ADR-0018 §3).
* There is **no egress allow-list setting.** Outbound HTTP is pinned to
  ``fdp_base_url``'s origin in code (the FDP client layer, task 1.2); it is not
  operator-widenable.

Settings are immutable once loaded. Tests build their own ``FdpMcpSettings``
instances rather than mutating the global one.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

Transport = Literal["streamable-http", "stdio"]
LogLevel = Literal["debug", "info", "warning", "error", "critical"]


class FdpMcpSettings(BaseSettings):
    """Top-level settings for the ``fdp-mcp`` bridge.

    ``FDP_BASE_URL`` keeps its bare, un-prefixed name because it is the one
    setting every operator sets and the documented one-liner bring-up relies on
    it (``docker run -e FDP_BASE_URL=...``). The remaining knobs are namespaced
    under ``FDP_MCP_`` so they cannot collide with unrelated environment
    variables (e.g. a generic ``PORT``).
    """

    model_config = SettingsConfigDict(
        env_prefix="FDP_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # The single target FDP. Un-prefixed by design (see class docstring); the
    # explicit alias overrides the ``FDP_MCP_`` prefix for this field only.
    fdp_base_url: HttpUrl = Field(
        validation_alias="FDP_BASE_URL",
        description="Base URL of the spec-compliant FDP this bridge exposes. Required.",
    )

    # Transport. Streamable-HTTP is the default (a long-lived network sidecar,
    # ADR-0018 §2); stdio is for running the bridge as a local subprocess of a
    # desktop MCP client.
    transport: Transport = "streamable-http"

    # Bind address for the streamable-HTTP (ASGI) transport. Defaults to
    # loopback so a bare `fdp-mcp` run is not exposed on all interfaces; the
    # container image sets FDP_MCP_HOST=0.0.0.0 explicitly to publish the port.
    host: str = "127.0.0.1"
    port: int = 8000

    log_level: LogLevel = "info"

    @property
    def fdp_origin(self) -> str:
        """The FDP's ``scheme://host[:port]`` origin — the egress allow-list.

        The FDP client layer pins every outbound request to this origin; no
        other host is ever contacted (ADR-0018 §3, strict egress).
        """
        url = self.fdp_base_url
        host = url.host or ""
        origin = f"{url.scheme}://{host}"
        if url.port is not None:
            origin = f"{origin}:{url.port}"
        return origin


@lru_cache(maxsize=1)
def get_settings() -> FdpMcpSettings:
    """Return the singleton ``FdpMcpSettings`` instance.

    Cached for the lifetime of the process. Tests should clear the cache
    (``get_settings.cache_clear()``) or build their own ``FdpMcpSettings``
    instance and pass it explicitly.
    """
    return FdpMcpSettings()  # type: ignore[call-arg]  # pydantic-settings fills from env
