"""Unit tests for HermesLLMClient — all mocked, no live API calls."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_openai():
    """Patch AsyncOpenAI so no real HTTP calls are made."""
    with patch("hermes.llm_client.AsyncOpenAI") as MockClass:
        mock_instance = MagicMock()
        MockClass.return_value = mock_instance
        # chat.completions.create is async
        mock_create = AsyncMock()
        mock_instance.chat.completions.create = mock_create
        # close() is also async
        mock_instance.close = AsyncMock()
        yield mock_instance, mock_create


@pytest.mark.asyncio
async def test_chat_returns_content(mock_openai):
    """chat() returns the content string from the first choice."""
    _, mock_create = mock_openai
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hello from freellmapi"
    mock_create.return_value = mock_response

    from hermes.llm_client import HermesLLMClient
    client = HermesLLMClient(base_url="http://fake:3001/v1", api_key="test-key")
    result = await client.chat([{"role": "user", "content": "hi"}])
    assert result == "hello from freellmapi"


@pytest.mark.asyncio
async def test_chat_passes_model(mock_openai):
    """chat() forwards the model parameter to AsyncOpenAI."""
    _, mock_create = mock_openai
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "ok"
    mock_create.return_value = mock_response

    from hermes.llm_client import HermesLLMClient
    client = HermesLLMClient(base_url="http://fake:3001/v1", api_key="test-key")
    await client.chat([{"role": "user", "content": "hi"}], model="gemini-2.5-flash")
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs.get("model") == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_chat_passes_messages(mock_openai):
    """chat() forwards the messages list unchanged to AsyncOpenAI."""
    _, mock_create = mock_openai
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "ok"
    mock_create.return_value = mock_response

    from hermes.llm_client import HermesLLMClient
    client = HermesLLMClient(base_url="http://fake:3001/v1", api_key="test-key")
    msgs = [{"role": "user", "content": "test message"}]
    await client.chat(msgs)
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs.get("messages") == msgs


@pytest.mark.asyncio
async def test_chat_raises_on_api_error(mock_openai):
    """chat() does NOT swallow exceptions — they propagate to the caller."""
    _, mock_create = mock_openai
    mock_create.side_effect = RuntimeError("connection refused")

    from hermes.llm_client import HermesLLMClient
    client = HermesLLMClient(base_url="http://fake:3001/v1", api_key="test-key")
    with pytest.raises(RuntimeError, match="connection refused"):
        await client.chat([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_client_uses_env_base_url(monkeypatch):
    """HermesLLMClient reads FREELLMAPI_BASE_URL from env."""
    monkeypatch.setenv("FREELLMAPI_BASE_URL", "http://custom-host:9999/v1")
    monkeypatch.setenv("FREELLMAPI_API_KEY", "env-key")

    with patch("hermes.llm_client.AsyncOpenAI") as MockClass:
        MockClass.return_value = MagicMock()
        # Re-import to pick up new env values
        import importlib
        import hermes.llm_client as mod
        importlib.reload(mod)
        mod.HermesLLMClient()
        call_kwargs = MockClass.call_args.kwargs
        assert call_kwargs.get("base_url") == "http://custom-host:9999/v1"
