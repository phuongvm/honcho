"""Public entry points for invoking LLMs across providers.

Exposes `honcho_llm_call`, the primary entry point for one-shot LLM
invocations with retry + fallback + tool loop support, and
`resolve_model_config` / `resolve_model_alias` for turning configuration-level
settings into concrete runtime ModelConfigs.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal, TypeVar, overload

from pydantic import BaseModel
from sentry_sdk.ai.monitoring import ai_track
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import ConfiguredModelSettings, ModelConfig, settings
from src.telemetry.logging import conditional_observe
from src.telemetry.reasoning_traces import log_reasoning_trace

from .executor import honcho_llm_call_inner
from .runtime import (
    AttemptPlan,
    current_attempt,
    effective_temperature,
    force_fallback,
    plan_attempt,
    resolve_runtime_model_config,
    start_langfuse_agent_run,
    update_current_langfuse_observation,
)
from .tool_loop import execute_tool_loop
from .types import (
    HonchoLLMCallResponse,
    HonchoLLMCallStreamChunk,
    IterationCallback,
    LLMTelemetryContext,
    ReasoningEffortType,
    StreamingResponseWithMetadata,
)

logger = logging.getLogger(__name__)


M = TypeVar("M", bound=BaseModel)


@overload
async def honcho_llm_call(
    *,
    model_config: ModelConfig | ConfiguredModelSettings,
    prompt: str = "",
    max_tokens: int = 1000,
    response_model: None = None,
    json_mode: bool = False,
    temperature: float | None = None,
    stop_seqs: list[str] | None = None,
    stream: Literal[False] = False,
    trace_name: str | None = None,
    reasoning_effort: ReasoningEffortType = None,
    verbosity: Literal["low", "medium", "high"] | None = None,
    thinking_budget_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
    max_tool_iterations: int = 20,
    messages: list[dict[str, Any]] | None = None,
    enable_retry: bool = True,
    retry_attempts: int = 3,
    max_input_tokens: int | None = None,
    track_name: str | None = None,
    stream_final_only: bool = False,
    iteration_callback: IterationCallback | None = None,
    telemetry: LLMTelemetryContext | None = None,
) -> HonchoLLMCallResponse[str]: ...


@overload
async def honcho_llm_call(
    *,
    model_config: ModelConfig | ConfiguredModelSettings,
    prompt: str = "",
    max_tokens: int = 1000,
    response_model: type[M],
    json_mode: bool = False,
    temperature: float | None = None,
    stop_seqs: list[str] | None = None,
    stream: Literal[False] = False,
    trace_name: str | None = None,
    reasoning_effort: ReasoningEffortType = None,
    verbosity: Literal["low", "medium", "high"] | None = None,
    thinking_budget_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
    max_tool_iterations: int = 20,
    messages: list[dict[str, Any]] | None = None,
    enable_retry: bool = True,
    retry_attempts: int = 3,
    max_input_tokens: int | None = None,
    track_name: str | None = None,
    stream_final_only: bool = False,
    iteration_callback: IterationCallback | None = None,
    telemetry: LLMTelemetryContext | None = None,
) -> HonchoLLMCallResponse[M]: ...


@overload
async def honcho_llm_call(
    *,
    model_config: ModelConfig | ConfiguredModelSettings,
    prompt: str = "",
    max_tokens: int = 1000,
    response_model: type[BaseModel] | None = None,
    json_mode: bool = False,
    temperature: float | None = None,
    stop_seqs: list[str] | None = None,
    stream: Literal[True],
    trace_name: str | None = None,
    reasoning_effort: ReasoningEffortType = None,
    verbosity: Literal["low", "medium", "high"] | None = None,
    thinking_budget_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
    max_tool_iterations: int = 20,
    messages: list[dict[str, Any]] | None = None,
    enable_retry: bool = True,
    retry_attempts: int = 3,
    max_input_tokens: int | None = None,
    track_name: str | None = None,
    stream_final_only: bool = False,
    iteration_callback: IterationCallback | None = None,
    telemetry: LLMTelemetryContext | None = None,
) -> AsyncIterator[HonchoLLMCallStreamChunk] | StreamingResponseWithMetadata: ...


@conditional_observe(name="LLM Call", as_type="generation")
async def honcho_llm_call(
    *,
    model_config: ModelConfig | ConfiguredModelSettings,
    prompt: str = "",
    max_tokens: int = 1000,
    response_model: type[BaseModel] | None = None,
    json_mode: bool = False,
    temperature: float | None = None,
    stop_seqs: list[str] | None = None,
    stream: bool = False,
    trace_name: str | None = None,
    reasoning_effort: ReasoningEffortType = None,
    verbosity: Literal["low", "medium", "high"] | None = None,
    thinking_budget_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
    max_tool_iterations: int = 20,
    messages: list[dict[str, Any]] | None = None,
    enable_retry: bool = True,
    retry_attempts: int = 3,
    max_input_tokens: int | None = None,
    track_name: str | None = None,
    stream_final_only: bool = False,
    iteration_callback: IterationCallback | None = None,
    telemetry: LLMTelemetryContext | None = None,
) -> (
    HonchoLLMCallResponse[Any]
    | AsyncIterator[HonchoLLMCallStreamChunk]
    | StreamingResponseWithMetadata
):
    """High-level LLM call entry point.

    Coordinates:
    - Runtime ModelConfig resolution from settings/alias inputs.
    - Retry attempt tracking via ContextVar `current_attempt`.
    - Fallback provider switching on the final retry attempt.
    - Optional tool calling loop when `tools` and `tool_executor` are supplied.
    - Sentry / Langfuse / telemetry tracing.
    """
    if track_name is not None:
        if telemetry is None:
            telemetry = LLMTelemetryContext(track_name=track_name)
        elif telemetry.track_name is None:
            telemetry.track_name = track_name

    runtime_model_config = resolve_runtime_model_config(model_config)

    # Reset retry state for this call tree.
    current_attempt.set(1)
    force_fallback.set(False)

    def _get_attempt_plan() -> AttemptPlan:
        plan = plan_attempt(
            runtime_model_config=runtime_model_config,
            attempt=current_attempt.get(),
            retry_attempts=retry_attempts,
            call_thinking_budget_tokens=thinking_budget_tokens,
            call_reasoning_effort=reasoning_effort,
            force_fallback=force_fallback.get(),
        )
        is_fallback = plan.selected_config is not runtime_model_config
        if track_name:
            update_current_langfuse_observation(
                plan.provider,
                plan.model,
                name=track_name,
                is_fallback=is_fallback,
                structured_output_mode=plan.selected_config.structured_output_mode,
            )
        return plan

    async def _call_with_provider_selection() -> (
        HonchoLLMCallResponse[Any]
        | AsyncIterator[HonchoLLMCallStreamChunk]
        | StreamingResponseWithMetadata
    ):
        plan = _get_attempt_plan()
        if stream:
            return await honcho_llm_call_inner(
                plan.provider,
                plan.model,
                prompt,
                max_tokens,
                response_model=response_model,
                json_mode=json_mode,
                temperature=effective_temperature(temperature),
                stop_seqs=stop_seqs,
                reasoning_effort=plan.reasoning_effort,
                verbosity=verbosity,
                thinking_budget_tokens=plan.thinking_budget_tokens,
                stream=True,
                client_override=plan.client,
                tools=tools,
                tool_choice=tool_choice,
                selected_config=plan.selected_config,
                plan=plan,
                telemetry=telemetry,
                messages=messages,
            )
        return await honcho_llm_call_inner(
            plan.provider,
            plan.model,
            prompt,
            max_tokens,
            response_model=response_model,
            json_mode=json_mode,
            temperature=effective_temperature(temperature),
            stop_seqs=stop_seqs,
            reasoning_effort=plan.reasoning_effort,
            verbosity=verbosity,
            thinking_budget_tokens=plan.thinking_budget_tokens,
            stream=False,
            client_override=plan.client,
            tools=tools,
            tool_choice=tool_choice,
            selected_config=plan.selected_config,
            plan=plan,
            telemetry=telemetry,
            messages=messages,
        )

    decorated = _call_with_provider_selection

    sentry_track_name = telemetry.track_name if telemetry is not None else None
    if sentry_track_name:
        decorated = ai_track(sentry_track_name)(decorated)

    def _is_retryable_error(exc: BaseException) -> bool:
        """Check if an error should trigger fast fallback to secondary model."""
        status = getattr(exc, "status_code", None)
        if status is not None:
            return status == 429 or (500 <= status < 600)
        if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            return True
        return type(exc).__name__ in (
            "APIConnectionError",
            "APITimeoutError",
            "InternalServerError",
            "ServiceUnavailableError",
            "RateLimitError",
        )

    def before_retry_callback(retry_state: Any) -> None:
        """Update attempt counter before each retry + log transient failures.

        When a fallback model is configured and the error is retryable (429/5xx/timeout),
        force_fallback is set to True so the very next attempt switches to the fallback
        model immediately instead of waiting for the final retry attempt.
        """
        attempt = retry_state.attempt_number + 1
        current_attempt.set(attempt)

        exc = retry_state.outcome.exception() if retry_state.outcome else None
        if exc is not None:
            if (
                runtime_model_config.fallback is not None
                and _is_retryable_error(exc)
                and not force_fallback.get()
            ):
                logger.warning(
                    "Retryable error detected on primary model (%s: %s). "
                    "Activating immediate fast fallback for next attempt.",
                    type(exc).__name__,
                    exc,
                )
                force_fallback.set(True)

            logger.warning(
                "LLM call attempt %d/%d failed with %s: %s. Retrying...",
                retry_state.attempt_number,
                retry_attempts,
                type(exc).__name__,
                exc,
            )

    if enable_retry:
        decorated = retry(
            stop=stop_after_attempt(retry_attempts),
            wait=wait_exponential(multiplier=1, min=4, max=10),
            before_sleep=before_retry_callback,
        )(decorated)

    if not tools or not tool_executor:
        toolless_hit_input_token_cap = False
        toolless_messages = messages
        if max_input_tokens is not None:
            from .conversation import count_message_tokens, truncate_messages_to_fit

            base_messages = messages or [{"role": "user", "content": prompt}]
            toolless_hit_input_token_cap = (
                count_message_tokens(base_messages) > max_input_tokens
            )
            toolless_messages = truncate_messages_to_fit(
                base_messages, max_input_tokens
            )

        if toolless_messages is not None:
            captured_messages = toolless_messages

            async def _toolless_call() -> (
                HonchoLLMCallResponse[Any] | AsyncIterator[HonchoLLMCallStreamChunk]
            ):
                plan = _get_attempt_plan()
                if stream:
                    return await honcho_llm_call_inner(
                        plan.provider,
                        plan.model,
                        prompt,
                        max_tokens,
                        response_model=response_model,
                        json_mode=json_mode,
                        temperature=effective_temperature(temperature),
                        stop_seqs=stop_seqs,
                        reasoning_effort=plan.reasoning_effort,
                        verbosity=verbosity,
                        thinking_budget_tokens=plan.thinking_budget_tokens,
                        stream=True,
                        client_override=plan.client,
                        tools=tools,
                        tool_choice=tool_choice,
                        selected_config=plan.selected_config,
                        plan=plan,
                        telemetry=telemetry,
                        messages=captured_messages,
                    )
                return await honcho_llm_call_inner(
                    plan.provider,
                    plan.model,
                    prompt,
                    max_tokens,
                    response_model=response_model,
                    json_mode=json_mode,
                    temperature=effective_temperature(temperature),
                    stop_seqs=stop_seqs,
                    reasoning_effort=plan.reasoning_effort,
                    verbosity=verbosity,
                    thinking_budget_tokens=plan.thinking_budget_tokens,
                    stream=False,
                    client_override=plan.client,
                    tools=tools,
                    tool_choice=tool_choice,
                    selected_config=plan.selected_config,
                    plan=plan,
                    telemetry=telemetry,
                    messages=captured_messages,
                )

            wrapped = _toolless_call
            if sentry_track_name:
                wrapped = ai_track(sentry_track_name)(wrapped)
            if enable_retry:
                wrapped = retry(
                    stop=stop_after_attempt(retry_attempts),
                    wait=wait_exponential(multiplier=1, min=4, max=10),
                    before_sleep=before_retry_callback,
                )(wrapped)
            result: (
                HonchoLLMCallResponse[Any]
                | AsyncIterator[HonchoLLMCallStreamChunk]
                | StreamingResponseWithMetadata
            ) = await wrapped()
        else:
            result = await decorated()

        if toolless_hit_input_token_cap and isinstance(result, HonchoLLMCallResponse):
            result.hit_input_token_cap = True

        if isinstance(result, HonchoLLMCallResponse) and settings.langfuse_inline_enabled:
            try:
                from langfuse import get_client

                usage: dict[str, Any] = {}
                if result.input_tokens is not None:
                    usage["input"] = result.input_tokens
                if result.output_tokens is not None:
                    usage["output"] = result.output_tokens
                if usage:
                    get_client().update_current_generation(usage_details=usage)
            except Exception as exc:
                logger.debug("Failed to update Langfuse usage: %s", exc)

        if trace_name and isinstance(result, HonchoLLMCallResponse):
            log_reasoning_trace(
                task_type=trace_name,
                model_config=runtime_model_config,
                prompt=prompt,
                response=result,
                max_tokens=max_tokens,
                stop_seqs=stop_seqs,
                messages=messages or [{"role": "user", "content": prompt}],
            )
        return result

    run_label = (telemetry.track_name if telemetry else None) or "Agent"
    run_handle = start_langfuse_agent_run(run_label, telemetry)
    if run_handle is not None:
        run_handle.update(
            input=messages if messages else [{"role": "user", "content": prompt}]
        )
    try:
        result = await execute_tool_loop(
            prompt=prompt,
            max_tokens=max_tokens,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            tool_executor=tool_executor,
            max_tool_iterations=max_tool_iterations,
            response_model=response_model,
            json_mode=json_mode,
            temperature=temperature,
            stop_seqs=stop_seqs,
            verbosity=verbosity,
            enable_retry=enable_retry,
            retry_attempts=retry_attempts,
            max_input_tokens=max_input_tokens,
            get_attempt_plan=_get_attempt_plan,
            before_retry_callback=before_retry_callback,
            stream_final=stream_final_only,
            iteration_callback=iteration_callback,
            telemetry=telemetry,
            langfuse_run_handle=run_handle,
        )
    except BaseException:
        if run_handle is not None:
            run_handle.end()
        raise

    if run_handle is not None and isinstance(result, HonchoLLMCallResponse):
        run_handle.end(output=result.content)

    if isinstance(result, HonchoLLMCallResponse) and settings.langfuse_inline_enabled:
        try:
            from langfuse import get_client

            usage = {}
            if result.input_tokens is not None:
                usage["input"] = result.input_tokens
            if result.output_tokens is not None:
                usage["output"] = result.output_tokens
            if usage:
                get_client().update_current_generation(usage_details=usage)
        except Exception as exc:
            logger.debug("Failed to update Langfuse usage: %s", exc)

    if trace_name and isinstance(result, HonchoLLMCallResponse):
        log_reasoning_trace(
            task_type=trace_name,
            model_config=runtime_model_config,
            prompt=prompt,
            response=result,
            max_tokens=max_tokens,
            stop_seqs=stop_seqs,
            messages=messages or [{"role": "user", "content": prompt}],
        )
    return result
