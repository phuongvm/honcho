"""Tests for Nous registry wiring with shared auth.json."""

from typing import Any
from unittest.mock import Mock

import pytest

from src.config import ModelConfig, settings
from src.llm import registry


def test_nous_client_can_bootstrap_from_auth_provider_without_static_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOUS_AUTH_JSON_PATH should make static LLM_NOUS_API_KEY optional."""
    monkeypatch.setattr(settings.LLM, "NOUS_API_KEY", None)
    monkeypatch.setattr(registry, "_nous_auth", Mock())

    created_clients: list[dict[str, str | None]] = []

    class FakeOpenAI:
        def __init__(
            self,
            *,
            api_key: str | None,
            base_url: str | None = None,
            timeout: float | None = None,
            default_headers: dict[str, str] | None = None,
            **kwargs: Any,
        ) -> None:
            created_clients.append(
                {"api_key": api_key, "base_url": base_url, "timeout": str(timeout)}
            )

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeOpenAI)
    registry.get_openai_override_client.cache_clear()

    client = registry.client_for_model_config(
        "nous",
        ModelConfig(model="nous-model", transport="nous"),
    )

    assert isinstance(client, FakeOpenAI)
    assert created_clients[0]["api_key"] == "nous-auth-provider-placeholder"
