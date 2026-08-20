import gc
import json
import logging
import weakref
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from openai import BadRequestError
from pydantic import BaseModel

from src.exceptions import ValidationException
from src.llm.backends.openai import (
    OpenAIBackend,
    _json_object_instruction,  # pyright: ignore[reportPrivateUsage]
)
from src.utils.representation import PromptRepresentation
from src.utils.schema_conversion import json_response_schema_to_pydantic


def _await_kwargs(mock_method: Any) -> dict[str, Any]:
    await_args = mock_method.await_args
    if await_args is None:
        raise AssertionError("Expected the mocked method to have been awaited")
    return await_args.kwargs


def _bad_request_error() -> BadRequestError:
    """A 400 like a provider that doesn't support json_schema would return."""
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(400, request=request)
    return BadRequestError(
        "response_format json_schema is not supported", response=response, body=None
    )


async def _empty_stream() -> AsyncIterator[Any]:
    chunks: list[Any] = []  # async generator that yields nothing
    for chunk in chunks:
        yield chunk


class _StructuredResponse(BaseModel):
    answer: str


def _structured_create_return(content: str, parsed: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content=content,
                    parsed=parsed,
                    tool_calls=[],
                    reasoning_details=[],
                    refusal=None,
                ),
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            prompt_tokens_details=None,
        ),
    )


@pytest.mark.asyncio
async def test_openai_backend_uses_gpt5_params_and_extracts_reasoning() -> None:
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="Hello from GPT-5",
                        tool_calls=[],
                        reasoning_details=[
                            SimpleNamespace(
                                content="reasoning summary",
                                model_dump=lambda: {
                                    "type": "reasoning",
                                    "content": "reasoning summary",
                                },
                            )
                        ],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=SimpleNamespace(cached_tokens=4),
            ),
        )
    )

    backend = OpenAIBackend(client)
    result = await backend.complete(
        model="gpt-5",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        extra_params={"verbosity": "low"},
    )

    assert result.thinking_content == "reasoning summary"
    assert result.reasoning_details == [
        {"type": "reasoning", "content": "reasoning summary"}
    ]
    assert result.cache_read_input_tokens == 4

    await_args = client.chat.completions.create.await_args
    if await_args is None:
        raise AssertionError("Expected OpenAI create call")
    call = await_args.kwargs
    assert call["max_completion_tokens"] == 100
    assert "max_tokens" not in call
    assert call["verbosity"] == "low"


@pytest.mark.asyncio
async def test_openai_backend_passes_thinking_effort_through_for_non_gpt5_models() -> (
    None
):
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="Hello from non-gpt5",
                        tool_calls=[],
                        reasoning_details=[],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=None,
            ),
        )
    )

    backend = OpenAIBackend(client)
    await backend.complete(
        model="claude-3-5-sonnet",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        thinking_effort="high",
    )

    await_args = client.chat.completions.create.await_args
    if await_args is None:
        raise AssertionError("Expected OpenAI create call")
    call = await_args.kwargs
    assert call["reasoning_effort"] == "high"
    assert call["max_tokens"] == 100
    assert "max_completion_tokens" not in call


@pytest.mark.asyncio
async def test_openai_backend_does_not_treat_proxy_models_with_gpt5_substring_as_gpt5() -> (
    None
):
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="Hello from proxy model",
                        tool_calls=[],
                        reasoning_details=[],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=None,
            ),
        )
    )

    backend = OpenAIBackend(client)
    await backend.complete(
        model="openrouter/some-gpt5-variant",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
    )

    await_args = client.chat.completions.create.await_args
    if await_args is None:
        raise AssertionError("Expected OpenAI create call")
    call = await_args.kwargs
    assert call["max_tokens"] == 100
    assert "max_completion_tokens" not in call


@pytest.mark.asyncio
async def test_openai_backend_passes_thinking_budget_via_extra_body() -> None:
    """thinking_budget_tokens is forwarded under extra_body.reasoning.max_tokens."""
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="ok",
                        tool_calls=[],
                        reasoning_details=[],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=None,
            ),
        )
    )

    backend = OpenAIBackend(client)
    await backend.complete(
        model="deepseek/deepseek-r1",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        thinking_budget_tokens=2048,
    )

    call = _await_kwargs(client.chat.completions.create)
    assert call["extra_body"] == {"reasoning": {"max_tokens": 2048}}


@pytest.mark.asyncio
async def test_openai_backend_skips_extra_body_when_thinking_budget_zero() -> None:
    """thinking_budget_tokens <= 0 does not inject extra_body."""
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="ok",
                        tool_calls=[],
                        reasoning_details=[],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=None,
            ),
        )
    )

    backend = OpenAIBackend(client)
    await backend.complete(
        model="gpt-4.1",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        thinking_budget_tokens=0,
    )

    call = _await_kwargs(client.chat.completions.create)
    assert "extra_body" not in call


@pytest.mark.asyncio
async def test_openai_backend_forwards_provider_params_extra_body() -> None:
    """extra_params.extra_body is forwarded straight to the OpenAI SDK."""
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="ok",
                        tool_calls=[],
                        reasoning_details=[],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=None,
            ),
        )
    )

    backend = OpenAIBackend(client)
    await backend.complete(
        model="openrouter/anthropic/claude-3.7-sonnet",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        extra_params={
            "extra_body": {
                "transforms": ["middle-out"],
                "route": "fallback",
            }
        },
    )

    call = _await_kwargs(client.chat.completions.create)
    assert call["extra_body"] == {
        "transforms": ["middle-out"],
        "route": "fallback",
    }


@pytest.mark.asyncio
async def test_openai_backend_forwards_provider_params_extra_headers_and_query() -> None:
    """extra_headers and extra_query passthroughs reach the OpenAI client."""
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="ok",
                        tool_calls=[],
                        reasoning_details=[],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=None,
            ),
        )
    )

    backend = OpenAIBackend(client)
    await backend.complete(
        model="gpt-4.1",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        extra_params={
            "extra_headers": {"X-Custom-Header": "custom-val"},
            "extra_query": {"custom_param": "1"},
        },
    )

    call = _await_kwargs(client.chat.completions.create)
    assert call["extra_headers"] == {"X-Custom-Header": "custom-val"}
    assert call["extra_query"] == {"custom_param": "1"}


@pytest.mark.asyncio
async def test_openai_backend_operator_extra_body_wins_over_auto_injection() -> None:
    """When the operator provides extra_body.reasoning, it overrides any
    auto-injected thinking_budget_tokens."""
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="ok",
                        tool_calls=[],
                        reasoning_details=[],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=None,
            ),
        )
    )

    backend = OpenAIBackend(client)
    await backend.complete(
        model="custom/model",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        thinking_budget_tokens=1000,
        extra_params={
            "extra_body": {
                "reasoning": {"effort": "custom-level"},
            }
        },
    )

    call = _await_kwargs(client.chat.completions.create)
    # Operator's reasoning object won completely
    assert call["extra_body"] == {"reasoning": {"effort": "custom-level"}}


@pytest.mark.asyncio
async def test_openai_backend_rejects_non_mapping_passthrough() -> None:
    """Non-mapping values in extra_body/extra_headers/extra_query raise ValidationException."""
    client = Mock()
    backend = OpenAIBackend(client)

    with pytest.raises(ValidationException, match="extra_body must be a mapping"):
        await backend.complete(
            model="gpt-4.1",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=100,
            extra_params={"extra_body": "not-a-dict"},
        )


@pytest.mark.asyncio
async def test_openai_backend_converts_anthropic_style_tools() -> None:
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="ok",
                        tool_calls=[],
                        reasoning_details=[],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=None,
            ),
        )
    )

    backend = OpenAIBackend(client)
    await backend.complete(
        model="gpt-4.1",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        tools=[
            {
                "name": "get_weather",
                "description": "Lookup weather",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            }
        ],
        tool_choice="required",
    )

    await_args = client.chat.completions.create.await_args
    if await_args is None:
        raise AssertionError("Expected OpenAI create call")
    call = await_args.kwargs
    assert call["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Lookup weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    assert call["tool_choice"] == "required"


@pytest.mark.asyncio
async def test_openai_backend_translates_canonical_any_tool_choice_to_required() -> (
    None
):
    """Regression: a Gemini→OpenAI fallback passes canonical "any", which OpenAI
    rejects as an invalid param. The backend must translate it to "required"."""
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="ok",
                        tool_calls=[],
                        reasoning_details=[],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=None,
            ),
        )
    )

    backend = OpenAIBackend(client)
    await backend.complete(
        model="gpt-4.1",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        tools=[
            {
                "name": "get_weather",
                "description": "Lookup weather",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
        tool_choice="any",
    )

    assert _await_kwargs(client.chat.completions.create)["tool_choice"] == "required"


@pytest.mark.parametrize(
    ("canonical", "expected"),
    [
        ("any", "required"),
        ("required", "required"),
        ("auto", "auto"),
        ("none", "none"),
        (None, None),
        ("search", {"type": "function", "function": {"name": "search"}}),
        ({"name": "search"}, {"type": "function", "function": {"name": "search"}}),
        ({"type": "function"}, {"type": "function"}),
    ],
)
def test_openai_convert_tool_choice(canonical: Any, expected: Any) -> None:
    assert OpenAIBackend._convert_tool_choice(canonical) == expected  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_openai_backend_passes_timeout_to_completion_request() -> None:
    """OpenAI completion requests receive per-request provider timeout."""
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="ok",
                        tool_calls=[],
                        reasoning_details=[],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=None,
            ),
        )
    )

    backend = OpenAIBackend(client)
    await backend.complete(
        model="gpt-4.1",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        extra_params={"timeout": 12.5},
    )

    assert _await_kwargs(client.chat.completions.create)["timeout"] == 12.5


@pytest.mark.asyncio
async def test_openai_backend_passes_timeout_to_structured_parse_request() -> None:
    """OpenAI structured parse requests receive per-request provider timeout."""
    client = Mock()
    client.chat.completions.parse = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        parsed=_StructuredResponse(answer="ok"),
                        content='{"answer":"ok"}',
                        tool_calls=[],
                        refusal=None,
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=None,
            ),
        )
    )

    backend = OpenAIBackend(client)
    await backend.complete(
        model="gpt-4.1",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        response_format=_StructuredResponse,
        extra_params={"timeout": "30"},
    )

    assert _await_kwargs(client.chat.completions.parse)["timeout"] == 30.0


@pytest.mark.parametrize(
    "model",
    [
        "gpt-5",
        "gpt-5-turbo",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.5-preview",
        "o1",
        "o1-mini",
        "o3",
        "o3-mini",
        "o4-preview",
    ],
)
def test_openai_reasoning_models_use_max_completion_tokens(model: str) -> None:
    """Reasoning model families (gpt-5 incl. x.y versions, o1/o3/o4) must send
    max_completion_tokens, not max_tokens — OpenAI rejects max_tokens for them
    with 400 unsupported_parameter."""
    from src.llm.backends.openai import (
        _uses_max_completion_tokens,  # pyright: ignore[reportPrivateUsage]
    )

    assert _uses_max_completion_tokens(model) is True


@pytest.mark.parametrize(
    "model",
    [
        "gpt-4.1",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-3.5-turbo",
        "some-proxy-model",
    ],
)
def test_openai_classic_models_use_max_tokens(model: str) -> None:
    """Non-reasoning OpenAI and OpenAI-compatible proxy models stay on
    the classic max_tokens parameter."""
    from src.llm.backends.openai import (
        _uses_max_completion_tokens,  # pyright: ignore[reportPrivateUsage]
    )

    assert _uses_max_completion_tokens(model) is False


class SimpleSchema(BaseModel):
    name: str
    age: int


@pytest.mark.asyncio
async def test_openai_backend_json_object_mode_request_shape_and_injection() -> None:
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content='{"name": "Alice", "age": 30}',
                        tool_calls=[],
                        reasoning_details=[],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=None,
            ),
        )
    )

    backend = OpenAIBackend(client)
    input_messages = [{"role": "user", "content": "Extract Alice, age 30"}]
    result = await backend.complete(
        model="cb-gemini-flash-high",
        messages=input_messages,
        max_tokens=100,
        response_format=SimpleSchema,
        extra_params={"structured_output_mode": "json_object"},
    )

    # 1. Output content is parsed model
    assert isinstance(result.content, SimpleSchema)
    assert result.content.name == "Alice"
    assert result.content.age == 30

    # 2. Input messages were not mutated
    assert len(input_messages) == 1

    # 3. create() was called with response_format={"type": "json_object"}
    await_args = client.chat.completions.create.await_args
    assert await_args is not None
    call = await_args.kwargs
    assert call["response_format"] == {"type": "json_object"}

    # 4. Augmented messages include schema instruction containing both "JSON" and "json"
    sent_messages = call["messages"]
    assert len(sent_messages) == 2
    system_msg = sent_messages[0]
    assert system_msg["role"] == "system"
    assert "JSON" in system_msg["content"]
    assert "json" in system_msg["content"]


@pytest.mark.asyncio
async def test_openai_backend_json_object_mode_instruction_caching() -> None:
    from src.llm.backends.openai import _json_object_instruction_cache

    _json_object_instruction_cache.clear()
    assert SimpleSchema not in _json_object_instruction_cache

    inst1 = _json_object_instruction(SimpleSchema)
    assert SimpleSchema in _json_object_instruction_cache

    inst2 = _json_object_instruction(SimpleSchema)
    assert inst1 == inst2


@pytest.mark.asyncio
async def test_openai_backend_json_object_mode_empty_or_null_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="",
                        tool_calls=[],
                        reasoning_details=[],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=0,
                prompt_tokens_details=None,
            ),
        )
    )

    backend = OpenAIBackend(client)
    with caplog.at_level(logging.WARNING):
        result = await backend.complete(
            model="cb-gemini-flash-high",
            messages=[{"role": "user", "content": "Extract"}],
            max_tokens=100,
            response_format=PromptRepresentation,
            extra_params={"structured_output_mode": "json_object"},
        )

    assert isinstance(result.content, PromptRepresentation)
    assert result.content.explicit == []
    assert not any("❌ Repair failed" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_openai_backend_json_object_mode_prose_or_malformed_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="Here is some unstructured conversational prose text.",
                        tool_calls=[],
                        reasoning_details=[],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=None,
            ),
        )
    )

    backend = OpenAIBackend(client)
    with caplog.at_level(logging.WARNING):
        result = await backend.complete(
            model="cb-gemini-flash-high",
            messages=[{"role": "user", "content": "Extract"}],
            max_tokens=100,
            response_format=PromptRepresentation,
            extra_params={"structured_output_mode": "json_object"},
        )

    assert isinstance(result.content, PromptRepresentation)
    assert result.content.explicit == []
    assert not any("❌ Repair failed" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_structured_output_parsed_none_with_raw_content_repairs() -> None:
    """parse() returning parsed=None but with raw content repairs that content."""
    client = Mock()
    client.chat.completions.parse = AsyncMock(
        return_value=_structured_create_return('{"answer": "ok"}', parsed=None)
    )

    backend = OpenAIBackend(client)
    result = await backend.complete(
        model="gpt-4.1",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        response_format=_StructuredResponse,
    )

    assert isinstance(result.content, _StructuredResponse)
    assert result.content.answer == "ok"


@pytest.mark.asyncio
async def test_structured_output_parsed_none_returns_refusal() -> None:
    """parse() returning parsed=None with no content surfaces the refusal."""
    client = Mock()
    response = _structured_create_return("", parsed=None)
    response.choices[0].message.refusal = "I can't help with that"
    client.chat.completions.parse = AsyncMock(return_value=response)

    backend = OpenAIBackend(client)
    result = await backend.complete(
        model="gpt-4.1",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        response_format=_StructuredResponse,
    )

    assert result.content == "I can't help with that"


@pytest.mark.asyncio
async def test_structured_output_parsed_none_no_content_raises() -> None:
    """json_schema with no parsed model, content, or refusal raises so the
    retry/fallback chain engages — it must NOT silently empty like json_object."""
    from src.exceptions import ValidationException

    client = Mock()
    client.chat.completions.parse = AsyncMock(
        return_value=_structured_create_return("", parsed=None)
    )

    backend = OpenAIBackend(client)
    with pytest.raises(ValidationException):
        await backend.complete(
            model="gpt-4.1",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=100,
            response_format=_StructuredResponse,
        )


@pytest.mark.asyncio
async def test_structured_output_default_mode_uses_parse() -> None:
    """Default json_schema mode uses parse(), not the json_object path."""
    client = Mock()
    client.chat.completions.parse = AsyncMock(
        return_value=_structured_create_return(
            '{"answer": "ok"}', parsed=_StructuredResponse(answer="ok")
        )
    )
    client.chat.completions.create = AsyncMock()

    backend = OpenAIBackend(client)
    result = await backend.complete(
        model="gpt-4.1",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        response_format=_StructuredResponse,
    )

    assert client.chat.completions.parse.await_count == 1
    assert client.chat.completions.create.await_count == 0
    parse_call = _await_kwargs(client.chat.completions.parse)
    assert parse_call["response_format"] is _StructuredResponse
    assert isinstance(result.content, _StructuredResponse)


@pytest.mark.asyncio
async def test_structured_output_json_schema_rejected_returns_empty_without_second_request() -> (
    None
):
    """A provider that rejects json_schema (400) returns empty, no second request.

    Retrying or re-requesting the same shape is pointless (#797), so a
    BadRequestError is swallowed to an empty representation rather than erroring.
    """
    client = Mock()
    client.chat.completions.parse = AsyncMock(side_effect=_bad_request_error())
    client.chat.completions.create = AsyncMock()

    backend = OpenAIBackend(client)
    result = await backend.complete(
        model="glm-4.6",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        response_format=PromptRepresentation,
    )

    assert client.chat.completions.parse.await_count == 1
    assert client.chat.completions.create.await_count == 0  # no second request
    assert isinstance(result.content, PromptRepresentation)
    assert result.content.explicit == []


@pytest.mark.asyncio
async def test_structured_output_json_schema_rejected_with_required_fields_does_not_raise() -> (
    None
):
    """A json_schema rejection must not raise even when the response model has
    required fields (empty_structured_output() can't build an empty instance) —
    it falls back to empty content instead of escaping the handler."""
    client = Mock()
    client.chat.completions.parse = AsyncMock(side_effect=_bad_request_error())
    client.chat.completions.create = AsyncMock()

    backend = OpenAIBackend(client)
    result = await backend.complete(
        model="glm-4.6",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        response_format=_StructuredResponse,  # has a required field
    )

    assert client.chat.completions.parse.await_count == 1
    assert client.chat.completions.create.await_count == 0  # no second request
    assert result.content == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        json.JSONDecodeError("Expecting value", "not json", 0),
        ValueError("transient parse glitch"),
    ],
)
async def test_structured_output_transient_parse_error_propagates_for_retry(
    exc: Exception,
) -> None:
    """Non-400 parse failures propagate so the retry/fallback chain can engage.

    Only a 400 (json_schema rejection) is treated as terminal-empty; a transient
    decode/validation glitch must re-raise so tenacity retries and the fallback
    model gets a chance — not be silently swallowed to empty on the first try.
    """
    client = Mock()
    client.chat.completions.parse = AsyncMock(side_effect=exc)
    client.chat.completions.create = AsyncMock()

    backend = OpenAIBackend(client)
    with pytest.raises(type(exc)):
        await backend.complete(
            model="glm-4.6",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=100,
            response_format=PromptRepresentation,
        )

    assert client.chat.completions.create.await_count == 0  # no second request


@pytest.mark.asyncio
async def test_structured_output_json_object_mode_request_shape() -> None:
    """json_object mode skips parse(), requests json_object, injects the schema."""
    client = Mock()
    client.chat.completions.parse = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_structured_create_return('{"answer": "ok"}')
    )

    backend = OpenAIBackend(client)
    result = await backend.complete(
        model="glm-4.6",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        response_format=_StructuredResponse,
        extra_params={"structured_output_mode": "json_object"},
    )

    assert client.chat.completions.parse.await_count == 0
    assert client.chat.completions.create.await_count == 1
    call = _await_kwargs(client.chat.completions.create)
    assert call["response_format"] == {"type": "json_object"}

    system_messages = [m for m in call["messages"] if m["role"] == "system"]
    assert system_messages, "expected a system message carrying the schema"
    system_content = system_messages[0]["content"]
    assert "JSON" in system_content
    assert "json" in system_content
    assert "answer" in system_content  # schema property serialized in
    assert isinstance(result.content, _StructuredResponse)
    assert result.content.answer == "ok"


@pytest.mark.asyncio
async def test_structured_output_json_object_mode_repairs_markdown() -> None:
    """A provider that ignores json_object and returns prose must not crash —
    PromptRepresentation repairs to an empty representation, not an exception."""
    client = Mock()
    client.chat.completions.parse = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_structured_create_return(
            "Sure! Here are the facts:\n- the user likes coffee"
        )
    )

    backend = OpenAIBackend(client)
    result = await backend.complete(
        model="glm-4.6",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        response_format=PromptRepresentation,
        extra_params={"structured_output_mode": "json_object"},
    )

    assert isinstance(result.content, PromptRepresentation)


@pytest.mark.asyncio
async def test_structured_output_json_object_mode_with_dynamic_model() -> None:
    """json_object mode composes with a caller-supplied schema converted at
    request time (the dialectic's response_format path): the generated class's
    schema — unions included — is injected into the prompt and the JSON body
    parses back through the class."""
    response_model = json_response_schema_to_pydantic(
        {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "years": {"type": ["integer", "null"]},
            },
            "required": ["answer", "years"],
        }
    )
    client = Mock()
    client.chat.completions.parse = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_structured_create_return('{"answer": "ok", "years": 3}')
    )

    backend = OpenAIBackend(client)
    result = await backend.complete(
        model="glm-4.6",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        response_format=response_model,
        extra_params={"structured_output_mode": "json_object"},
    )

    assert client.chat.completions.parse.await_count == 0
    call = _await_kwargs(client.chat.completions.create)
    assert call["response_format"] == {"type": "json_object"}
    system_messages = [m for m in call["messages"] if m["role"] == "system"]
    assert system_messages, "expected a system message carrying the schema"
    # The dynamic model's schema (union field included) made it into the prompt.
    assert "years" in system_messages[0]["content"]
    assert "anyOf" in system_messages[0]["content"]

    assert isinstance(result.content, response_model)
    # The model class is dynamic, so field access is untyped by construction.
    content: Any = result.content
    assert content.answer == "ok"
    assert content.years == 3


def test_json_object_instruction_does_not_pin_dynamic_models() -> None:
    """The instruction cache must hold its model-class keys weakly: the
    dialectic creates a fresh response_format class per request (see
    src/utils/schema_conversion.py), and a strong-keyed cache would grow by
    one pinned class per structured chat call."""
    model = json_response_schema_to_pydantic(
        {"type": "object", "properties": {"answer": {"type": "string"}}}
    )
    first = _json_object_instruction(model)
    assert _json_object_instruction(model) is first  # cached while alive

    ref = weakref.ref(model)
    del model
    gc.collect()
    assert ref() is None, "instruction cache must not keep dynamic classes alive"


@pytest.mark.asyncio
async def test_structured_output_json_object_empty_content_returns_empty() -> None:
    """An empty body with no refusal must produce a graceful empty result, not
    raise — matching the json_schema path's behavior on a contentless response.
    """
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=_structured_create_return("")
    )

    backend = OpenAIBackend(client)
    result = await backend.complete(
        model="glm-4.6",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        response_format=PromptRepresentation,
        extra_params={"structured_output_mode": "json_object"},
    )

    assert isinstance(result.content, PromptRepresentation)
    assert result.content.explicit == []
    # Usage from the (empty) response is preserved, not zeroed.
    assert result.input_tokens == 10


@pytest.mark.asyncio
async def test_structured_output_json_object_empty_content_required_fields() -> None:
    """Empty content for a required-field model falls back to empty string content
    instead of raising (empty_structured_output can't build the instance)."""
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=_structured_create_return("")
    )

    backend = OpenAIBackend(client)
    result = await backend.complete(
        model="glm-4.6",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        response_format=_StructuredResponse,  # has a required field
        extra_params={"structured_output_mode": "json_object"},
    )

    assert result.content == ""


@pytest.mark.asyncio
async def test_structured_output_json_object_mode_does_not_mutate_messages() -> None:
    """The schema-injection helper must copy, never mutate the caller's list."""
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=_structured_create_return('{"answer": "ok"}')
    )

    backend = OpenAIBackend(client)
    original_messages = [{"role": "user", "content": "Hello"}]
    await backend.complete(
        model="glm-4.6",
        messages=original_messages,
        max_tokens=100,
        response_format=_StructuredResponse,
        extra_params={"structured_output_mode": "json_object"},
    )

    assert original_messages == [{"role": "user", "content": "Hello"}]


@pytest.mark.asyncio
async def test_stream_structured_output_default_mode_uses_json_schema() -> None:
    """Streaming in default mode converts the model to a json_schema dict."""
    client = Mock()
    client.chat.completions.create = AsyncMock(return_value=_empty_stream())

    backend = OpenAIBackend(client)
    async for _ in backend.stream(
        model="gpt-4.1",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        response_format=_StructuredResponse,
    ):
        pass

    call = _await_kwargs(client.chat.completions.create)
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["name"] == "_StructuredResponse"


@pytest.mark.asyncio
async def test_stream_structured_output_json_object_mode() -> None:
    """Streaming in json_object mode requests json_object + injects the schema."""
    client = Mock()
    client.chat.completions.create = AsyncMock(return_value=_empty_stream())

    backend = OpenAIBackend(client)
    async for _ in backend.stream(
        model="glm-4.6",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        response_format=_StructuredResponse,
        extra_params={"structured_output_mode": "json_object"},
    ):
        pass

    call = _await_kwargs(client.chat.completions.create)
    assert call["response_format"] == {"type": "json_object"}
    system_messages = [m for m in call["messages"] if m["role"] == "system"]
    assert system_messages
    assert "JSON" in system_messages[0]["content"]
    assert "json" in system_messages[0]["content"]


AGENT_TOOL = {
    "name": "search",
    "description": "Search for information",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
    },
}


@pytest.mark.asyncio
async def test_openai_backend_structured_with_tools_uses_create_not_parse() -> None:
    """With tools + response_format, complete() must route through create()
    with an explicit json_schema response_format: parse() raises client-side
    on non-strict function tools, and our agent tools are deliberately
    non-strict (see _convert_tools)."""
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=_structured_create_return('{"answer":"ok"}')
    )
    client.chat.completions.parse = AsyncMock(
        side_effect=AssertionError("parse() must not be called with tools")
    )

    backend = OpenAIBackend(client)
    result = await backend.complete(
        model="gpt-5.4-mini",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        tools=[AGENT_TOOL],
        response_format=_StructuredResponse,
    )

    assert isinstance(result.content, _StructuredResponse)
    assert result.content.answer == "ok"
    client.chat.completions.parse.assert_not_awaited()
    call = _await_kwargs(client.chat.completions.create)
    assert call["response_format"]["type"] == "json_schema"
    assert (
        call["response_format"]["json_schema"]["schema"]
        == _StructuredResponse.model_json_schema()
    )
    # Tools stay non-strict; strictness was the whole reason to avoid parse().
    assert "strict" not in call["tools"][0]["function"]


@pytest.mark.asyncio
async def test_openai_backend_structured_with_tools_skips_parsing_tool_call_turn() -> (
    None
):
    """A tool-call turn under tools + response_format must not attempt JSON
    parsing (its content is empty and _parse_or_repair raises on that)."""
    client = Mock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="tool_1",
                                function=SimpleNamespace(
                                    name="search",
                                    arguments='{"query": "honcho"}',
                                ),
                            )
                        ],
                        reasoning_details=[],
                        refusal=None,
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                prompt_tokens_details=None,
            ),
        )
    )

    backend = OpenAIBackend(client)
    result = await backend.complete(
        model="gpt-5.4-mini",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        tools=[AGENT_TOOL],
        response_format=_StructuredResponse,
    )

    assert result.content == ""  # raw empty text, not a parsed model
    assert result.tool_calls[0].name == "search"
    assert result.tool_calls[0].input == {"query": "honcho"}


@pytest.mark.asyncio
async def test_openai_backend_structured_without_tools_still_uses_parse() -> None:
    """Tool-less structured calls (deriver, final synthesis) keep parse()."""
    parsed = _StructuredResponse(answer="ok")
    client = Mock()
    client.chat.completions.parse = AsyncMock(
        return_value=_structured_create_return('{"answer":"ok"}', parsed=parsed)
    )
    client.chat.completions.create = AsyncMock(
        side_effect=AssertionError("create() must not be called without tools")
    )

    backend = OpenAIBackend(client)
    result = await backend.complete(
        model="gpt-5.4-mini",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=100,
        response_format=_StructuredResponse,
    )

    assert result.content is parsed
    client.chat.completions.create.assert_not_awaited()
