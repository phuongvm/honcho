"""Integration tests for Nous auto-refresh in OpenAIBackend."""

import base64
import json
import time
from collections.abc import Mapping
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from openai import AuthenticationError

from src.llm.backends.openai import OpenAIBackend
from src.llm.nous_auth import NousAuthProvider


def make_jwt(*, ttl: int = 900, scope: str = "inference:invoke") -> str:
    header: dict[str, Any] = {"alg": "none", "typ": "JWT"}
    payload: dict[str, Any] = {"exp": int(time.time()) + ttl, "scope": scope}

    def encode(part: Mapping[str, Any]) -> str:
        raw = json.dumps(part, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{encode(header)}.{encode(payload)}."


@pytest.mark.asyncio
async def test_nous_backend_auto_refresh_on_401_json_object_mode() -> None:
    """Nous auth refresh is preserved in json_object structured_output_mode."""
    from src.utils.representation import PromptRepresentation

    mock_client = Mock()
    mock_client.api_key = "old_key"

    mock_success_response = Mock()
    mock_success_response.choices = [
        Mock(
            message=Mock(
                content='{"explicit": [{"content": "Fact 1"}]}',
                tool_calls=[],
                refusal=None,
                parsed=None,
            )
        )
    ]
    mock_success_response.usage = Mock(completion_tokens=15)

    mock_client.chat.completions.create = AsyncMock(
        side_effect=[
            AuthenticationError(
                message="401 Unauthorized",
                response=Mock(status_code=401, request=Mock()),
                body={"error": "invalid_api_key"},
            ),
            mock_success_response,
        ]
    )

    provider = Mock()
    provider.get_api_key = AsyncMock(side_effect=["old_key", "new_refreshed_key"])

    backend = OpenAIBackend(mock_client, is_nous=True, nous_auth=provider)

    result = await backend.complete(
        model="nous-model",
        messages=[{"role": "user", "content": "Extract"}],
        max_tokens=100,
        response_format=PromptRepresentation,
        extra_params={"structured_output_mode": "json_object"},
    )

    assert mock_client.api_key == "new_refreshed_key"
    assert mock_client.chat.completions.create.call_count == 2
    assert isinstance(result.content, PromptRepresentation)
    assert len(result.content.explicit) == 1
    assert result.content.explicit[0].content == "Fact 1"


@pytest.mark.asyncio
async def test_openai_backend_no_refresh_on_401() -> None:
    """Non-Nous backends should not intercept 401; error bubbles up."""
    mock_client = Mock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=AuthenticationError(
        message="401",
        response=Mock(status_code=401, request=Mock()),
        body={"error": "invalid_api_key"},
    )
    )

    backend = OpenAIBackend(mock_client, is_nous=False)

    with pytest.raises(AuthenticationError):
        await backend.complete(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=10,
        )

    # Should call create exactly once (no retry)
    assert mock_client.chat.completions.create.call_count == 1


@pytest.mark.asyncio
async def test_nous_backend_refresh_fails_propagates_error() -> None:
    """If NousAuthProvider cannot refresh on 401, the original 401 is raised."""
    mock_client = Mock()
    mock_client.api_key = "old_key"
    mock_client.chat.completions.create = AsyncMock(
        side_effect=AuthenticationError(
        message="401",
        response=Mock(status_code=401, request=Mock()),
        body={"error": "invalid_api_key"},
    )
    )

    provider = Mock()
    provider.get_api_key = AsyncMock(side_effect=RuntimeError("refresh failed"))
    backend = OpenAIBackend(mock_client, is_nous=True, nous_auth=provider)

    with (
        patch(
            "src.llm.nous_refresh.refresh_nous_credentials",
            new=AsyncMock(side_effect=AssertionError("legacy refresh called")),
        ),
        pytest.raises(AuthenticationError),
    ):
        await backend.complete(
            model="nous-model",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5,
        )

    # Still only one call because refresh failed before retry
    assert mock_client.chat.completions.create.call_count == 1


@pytest.mark.asyncio
async def test_nous_backend_stream_auto_refresh() -> None:
    """Stream path also refreshes through NousAuthProvider on 401."""

    class FakeAsyncIterator:
        """Simple async iterator yielding predetermined chunks."""
        def __init__(self, chunks: list[Any]):
            self.chunks = chunks
            self.idx = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.idx >= len(self.chunks):
                raise StopAsyncIteration
            chunk = self.chunks[self.idx]
            self.idx += 1
            return chunk

    mock_client = Mock()
    mock_client.api_key = "old_key"

    call_count = 0

    async def create_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise AuthenticationError(
                message="401",
                response=Mock(status_code=401, request=Mock()),
                body={"error": "invalid_api_key"},
            )
        # Return an async iterator simulating a stream
        return FakeAsyncIterator(
            [Mock(choices=[Mock(delta=Mock(content="Hello"))], usage=Mock(completion_tokens=1))]
        )

    mock_client.chat.completions.create = AsyncMock(side_effect=create_side_effect)

    provider = Mock()
    provider.get_api_key = AsyncMock(side_effect=["old_key", "new_key"])
    backend = OpenAIBackend(mock_client, is_nous=True, nous_auth=provider)

    with patch(
        "src.llm.nous_refresh.refresh_nous_credentials",
        new=AsyncMock(side_effect=AssertionError("legacy refresh called")),
    ):
        chunks = []
        async for chunk in backend.stream(
            model="nous-model",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=10,
        ):
            chunks.append(chunk)

    assert mock_client.api_key == "new_key"
    assert call_count == 2
    # Stream yields one content chunk and one final done chunk
    assert len(chunks) == 2
    assert chunks[0].content == "Hello"
    assert chunks[1].is_done is True
    assert chunks[1].output_tokens == 1


@pytest.mark.asyncio
async def test_nous_auth_provider_falls_back_to_env_when_auth_file_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing shared auth.json should use LLM_NOUS_API_KEY instead of failing."""
    monkeypatch.setenv("LLM_NOUS_API_KEY", "static-fallback-key")

    provider = NousAuthProvider(tmp_path / "missing-auth.json")

    assert await provider.get_api_key() == "static-fallback-key"


@pytest.mark.asyncio
async def test_nous_auth_provider_reads_flat_shared_access_token(tmp_path) -> None:
    """Hermes shared/nous_auth.json uses a flat root access_token layout."""
    token = make_jwt(ttl=900)
    auth_path = tmp_path / "nous_auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "_schema": "hermes.nous_auth.v1",
                "access_token": token,
                "refresh_token": "rt_flat",
                "expires_at": "2099-01-01T00:00:00+00:00",
            }
        )
    )

    provider = NousAuthProvider(auth_path)

    assert await provider.get_api_key() == token


@pytest.mark.asyncio
async def test_nous_auth_provider_refresh_preserves_flat_shared_layout(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refreshing flat shared credentials should not rewrite into providers.nous."""
    expired = make_jwt(ttl=-10)
    refreshed = make_jwt(ttl=900)
    auth_path = tmp_path / "nous_auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "_schema": "hermes.nous_auth.v1",
                "access_token": expired,
                "refresh_token": "rt_old",
                "client_id": "hermes-cli",
            }
        )
    )

    monkeypatch.setattr(
        "src.llm.nous_auth._refresh_access_token",
        lambda refresh_token: (refreshed, "rt_new"),
    )

    provider = NousAuthProvider(auth_path)

    assert await provider.get_api_key() == refreshed

    written = json.loads(auth_path.read_text())
    assert "providers" not in written
    assert written["access_token"] == refreshed
    assert written["agent_key"] == refreshed
    assert written["refresh_token"] == "rt_new"
