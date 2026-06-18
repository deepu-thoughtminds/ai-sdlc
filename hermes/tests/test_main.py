"""Unit tests for hermes.__main__ startup self-test."""
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_self_test_logs_passed_on_success(caplog):
    """_llm_self_test logs 'passed' when chat() returns a response."""
    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value="pong")

    with caplog.at_level(logging.INFO, logger="hermes"):
        from hermes.__main__ import _llm_self_test
        await _llm_self_test(mock_client)

    assert any("passed" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_self_test_logs_failed_on_exception(caplog):
    """_llm_self_test logs 'failed' and does NOT re-raise on exception."""
    mock_client = MagicMock()
    mock_client.chat = AsyncMock(side_effect=ConnectionError("freellmapi down"))

    with caplog.at_level(logging.WARNING, logger="hermes"):
        from hermes.__main__ import _llm_self_test
        await _llm_self_test(mock_client)  # must not raise

    assert any("failed" in record.message for record in caplog.records)
