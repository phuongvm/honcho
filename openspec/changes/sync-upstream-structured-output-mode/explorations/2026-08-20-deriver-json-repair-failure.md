# Exploration: Honcho Deriver JSON Repair Failure on 9Router/Antigravity Models

> **Date**: 2026-08-20  
> **Status**: Revised & Validated (Post-Reviewer Audit)  
> **Target System**: `honcho` (`src/config.py`, `src/deriver/`, `src/llm/backends/openai.py`, `src/llm/request_builder.py`, `src/llm/runtime.py`) & `9router`  

---

## 1. Problem Statement & Root Cause

In `honcho-deriver-1` logs:
```text
2026-08-20 01:50:57,368 - src.utils.json_parser - ERROR - ❌ Repair failed: Expecting value: line 1 column 1 (char 0)
2026-08-20 01:50:57,369 - src.deriver.deriver - WARNING - Deriver generated zero observations for messages 16549:16573 in hermes_agent4070/hermes-agent!
```

### Verified Root Cause Mechanics
1. **Local Honcho Deriver Call**:
   Honcho's Deriver calls `OpenAIBackend.complete()` with `response_format=PromptRepresentation` using the OpenAI SDK's `chat.completions.parse()` (`src/llm/backends/openai.py:196-220`).
2. **9Router Translator Dropping Response Format**:
   When routing to `ag/gemini-3.7-flash-high`, 9Router's `openai-to-gemini.js` translator strips/drops `response_format` (both `json_schema` and `json_object`), emitting no `responseSchema` or `responseMimeType` in Google CloudCode generationConfig.
3. **Gemini Output & JSON Parse Breakdown**:
   Because the schema is omitted, Gemini generates conversational Markdown prose (`Here is a structured analysis of the statement...`). Pydantic parse fails, catches the error, and delegates to `validate_and_repair_json()`. The repair parser fails on pure prose text, logging `❌ Repair failed`, and safely defaults to 0 observations.

---

## 2. Upstream Audit & Fork Compatibility Analysis

### A. Upstream PR #820 (commit `a0cc938f`) & Follow-up PR #887 (commit `de1b4101`)
Upstream addressed this class of issue for loose/custom OpenAI-compatible proxies (Z.AI GLM, Ollama, vLLM) via:
* `DERIVER_MODEL_CONFIG__STRUCTURED_OUTPUT_MODE=json_object` in `src/config.py`.
* In `OpenAIBackend.complete()`: Skips `parse()`, injects the Pydantic schema instruction directly into the prompt messages (including lowercase `"json"` per #887), and calls `create(response_format={"type": "json_object"})`.
* Graceful empty fallback handling in `_parse_or_repair_structured_content` so loose providers do not raise repair exceptions.

### B. Blocking Fork Incompatibilities Identified in Review Audit
1. **Transport Capability Gating in `src/config.py`**:
   Unmodified upstream #820 strictly enforces `if transport != "openai": raise ValueError(...)`. In our local fork, custom transports (`ai-router`, `nous`, `lmstudio`) all utilize `OpenAIBackend`. Unmodified upstream code causes a Pydantic `ValidationError` on startup if `transport="ai-router"`.
   * **Fix**: Adapt `_validate_structured_output_mode` to allow all `OpenAIBackend`-backed transports (`"openai"`, `"ai-router"`, `"nous"`, `"lmstudio"`).
2. **Preservation of Fork Extensions**:
   * **Nous Auth Refresh**: Local `OpenAIBackend` implements proactive & 401 token refresh (`_ensure_nous_key`, `_refresh_nous_key_for_retry`). The new `json_object` branch must preserve this wrapper.
   * **Langfuse Telemetry**: Telemetry attribution and attempt tracking in `src/llm/runtime.py` and `src/llm/api.py` must carry `structured_output_mode` without regressing spans.
   * **Model Fallback**: Propagation of `structured_output_mode` to `ResolvedFallbackConfig` must remain intact so secondary models in fallback chains inherit the mode.
3. **Merge Scope Risk (130 commits behind)**:
   A full merge of `upstream/main` introduces 130 commits (Scopes SDK, Redis clusters, Dialectic schema changes) with excessive blast radius. A **targeted port of #820 + #887** is the safe, disciplined path.

---

## 3. Targeted Technical Design

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                      TARGETED FORK PORT ARCHITECTURE                            │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  1. `src/config.py`                                                             │
│     • Add `StructuredOutputMode = Literal["json_schema", "json_object"]`.       │
│     • Add `structured_output_mode` to `ConfiguredModelSettings`,                │
│       `FallbackModelSettings`, `ModelConfig`, `ResolvedFallbackConfig`.         │
│     • Validate: Allow `{"openai", "ai-router", "nous", "lmstudio"}`.            │
│       Reject native `{"anthropic", "gemini"}`.                                  │
│                                                                                 │
│  2. `src/llm/backends/openai.py`                                                │
│     • Add cached `_json_object_instruction(response_format)` with lowercase     │
│       `"json"` and `"JSON"` matching upstream #820 + #887.                     │
│     • In `complete()`: If `structured_output_mode == "json_object"`, call       │
│       `_apply_json_object_mode()` and `_client.chat.completions.create()`.      │
│     • Preserve Nous auth auto-refresh wrapping on `create()`.                   │
│     • Add `_parse_or_repair_structured_content(empty_on_missing=True)`.        │
│                                                                                 │
│  3. `src/llm/runtime.py` & `src/llm/request_builder.py`                         │
│     • Forward `structured_output_mode` in `build_config_extra_params()`.        │
│     • Carry `structured_output_mode` in `select_model_config_for_attempt()`.    │
│                                                                                 │
│  4. Verification & Testing                                                      │
│     • Unit tests in `tests/llm/test_model_config.py` for `ai-router` transport. │
│     • Backend unit tests in `tests/llm/test_backends/test_openai.py`.           │
│     • Live integration test: Deriver batch against 9Router `cb-gemini-flash-high`│
│       yielding valid parsed observations without repair errors.                 │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Acceptance Criteria & Verification Plan
1. **Configuration Acceptance**: `ConfiguredModelSettings(model="cb-gemini-flash-high", transport="ai-router", structured_output_mode="json_object")` validates with 0 errors.
2. **Unit Test Coverage**: All 46 baseline tests + new `ai-router` transport structured output tests pass.
3. **Live E2E Verification**:
   * Set `DERIVER_MODEL_CONFIG__STRUCTURED_OUTPUT_MODE=json_object` in `docker-compose/honcho/.env`.
   * Ingest test conversation messages into Honcho.
   * Verify `honcho-deriver-1` processes the queue and successfully saves observations (`Observation Count > 0`) with zero `❌ Repair failed` log entries.
