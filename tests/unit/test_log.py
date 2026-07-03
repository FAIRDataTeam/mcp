"""Unit tests for credential redaction in logging (task 0.2).

ADR-0018 §3: the forwarded credential is never logged. These tests assert it at
both layers — the processor in isolation and the fully configured pipeline.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from fdp_mcp.log import REDACTED, configure_logging, get_logger, redact_credentials


def test_processor_redacts_sensitive_keys() -> None:
    event = redact_credentials(
        None,
        "info",
        {
            "event": "session_request",
            "authorization": "Bearer tok-123",
            "api_key": "k-456",
            "token": "t-789",
            "session_id": "s1",
        },
    )
    assert event["authorization"] == REDACTED
    assert event["api_key"] == REDACTED
    assert event["token"] == REDACTED
    # Non-sensitive keys are untouched.
    assert event["session_id"] == "s1"


def test_processor_masks_secretstr_values() -> None:
    event = redact_credentials(None, "info", {"credential_value": SecretStr("hunter2")})
    assert event["credential_value"] == REDACTED


def test_processor_rewrites_bearer_substring_in_free_text() -> None:
    event = redact_credentials(
        None, "info", {"detail": "upstream sent Authorization: Bearer abc.DEF-123 to /mcp"}
    )
    assert "abc.DEF-123" not in event["detail"]
    assert "Bearer" in event["detail"]  # scheme kept for legibility


def test_configured_pipeline_never_emits_the_token(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("info")
    log = get_logger("test")

    log.info(
        "session_request",
        authorization="Bearer top-secret-token",
        detail="prefix Bearer top-secret-token suffix",
        credential=SecretStr("top-secret-token"),
        session_id="s1",
        authenticated=True,
    )

    out = capsys.readouterr().out
    assert "top-secret-token" not in out
    assert "redacted" in out  # the marker survives JSON escaping of the guillemets
    assert "session_request" in out
