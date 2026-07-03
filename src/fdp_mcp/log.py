"""Structured logging with hard credential redaction.

The bridge forwards a client's FDP API key per session; ADR-0018 §3 requires it
is **never logged**. This module is the enforcement point: ``configure_logging``
installs a structlog pipeline whose ``redact_credentials`` processor runs before
any renderer and strips bearer tokens, ``SecretStr`` values, and known-sensitive
keys from every event. Call it once at process start (``server.run``).

Two layers of defence, deliberately redundant:

* Credentials are held as ``pydantic.SecretStr`` everywhere, so their ``repr``
  and ``str`` already mask the value.
* ``redact_credentials`` catches anything that slips through — a raw
  ``Authorization`` header, a ``Bearer <token>`` substring in a free-text
  field, or a value logged under a sensitive key.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import structlog
from pydantic import SecretStr
from structlog.typing import EventDict, WrappedLogger

from fdp_mcp.config import LogLevel

REDACTED = "«redacted»"

# Keys whose value is a credential regardless of type; the value is dropped
# wholesale rather than pattern-matched.
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "credential",
        "credentials",
        "token",
        "access_token",
        "bearer",
        "api_key",
        "apikey",
        "password",
        "secret",
    }
)

# Matches an ``Authorization: Bearer <token>`` value anywhere in a string,
# keeping the scheme so the redaction is legible in logs.
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+[\w.\-~+/]+=*")

_LEVEL_TO_INT: dict[LogLevel, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def redact_credentials(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    """structlog processor: strip credentials from an event before rendering.

    Runs on every event. Redacts sensitive keys outright, masks ``SecretStr``
    values, and rewrites any ``Bearer <token>`` occurrence in string values.
    """
    for key, value in event_dict.items():
        if key.lower() in _SENSITIVE_KEYS or isinstance(value, SecretStr):
            event_dict[key] = REDACTED
        elif isinstance(value, str):
            event_dict[key] = _BEARER_RE.sub(rf"\1 {REDACTED}", value)
    return event_dict


def configure_logging(level: LogLevel = "info") -> None:
    """Install the structlog pipeline. Idempotent; call once at startup."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            redact_credentials,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # default=str so non-JSON values (e.g. a SessionContext, whose repr
            # already masks its SecretStr) serialise instead of raising.
            structlog.processors.JSONRenderer(default=str),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(_LEVEL_TO_INT[level]),
        logger_factory=structlog.PrintLoggerFactory(),
        # Not cached: reconfiguration (e.g. a different level) takes effect for
        # every logger, and tests can reset the pipeline between cases. The
        # bridge is I/O-bound, so the per-call cost is immaterial.
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> Any:
    """Return a bound structlog logger for ``name``."""
    return structlog.get_logger(name)
