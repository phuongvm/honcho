# Design: Sync Upstream Structured Output Mode

> **Change**: `sync-upstream-structured-output-mode`
> **Date**: 2026-08-20
> **Author**: Designer

---

## Overview

This design specifies how to port upstream Honcho's `StructuredOutputMode` feature (#820 + #887) into this fork while preserving custom transport support, Nous authentication, Langfuse telemetry, and model fallback semantics.

## Design Decisions

### D1: Backend-Capability Validation (not Literal Transport Name)

**Decision**: Replace upstream's `transport == "openai"` guard with a set-based capability check against all `OpenAIBackend`-backed transports.

**Rationale**: This fork declares `ai-router`, `nous`, and `lmstudio` as distinct transport identifiers, all resolved to `OpenAIBackend` via `BackendRegistry`. The upstream literal check rejects all three. A set-based approach (`OPENAI_BACKEND_TRANSPORTS = {"openai", "ai-router", "nous", "lmstudio"}`) is explicit, auditable, and avoids runtime registry lookups during config validation.

**Location**: `src/config.py`, `_validate_structured_output_mode` validator on `ConfiguredModelSettings`.

### D2: Transport Capability Set as Module-Level Constant

**Decision**: Define `OPENAI_BACKEND_TRANSPORTS` as a module-level `frozenset` in `src/config.py`.

**Rationale**: Config validation runs at import/startup time, before `BackendRegistry` is initialized. A static set avoids circular imports and is deterministic. The set must be updated when new transports are added — this is an acceptable maintenance burden given transport additions are rare and spec-governed.

### D3: Preserve Existing `parse()` Path as Default

**Decision**: `structured_output_mode` defaults to `None` (equivalent to `json_schema` / current behavior). The `json_object` mode is opt-in via env var `DERIVER_MODEL_CONFIG__STRUCTURED_OUTPUT_MODE=json_object`.

**Rationale**: Backward compatibility. Existing deployments using native OpenAI with `parse()` continue unchanged. Only configurations routing through proxies that drop `response_format` need the `json_object` override.

### D4: Schema Instruction Injection Strategy

**Decision**: When `structured_output_mode == "json_object"`, inject the Pydantic model's JSON schema as a system message instruction, containing both `"JSON"` and lowercase `"json"` keywords.

**Rationale**: Upstream #820 injects schema; #887 adds lowercase `"json"` for providers enforcing case-sensitive JSON-object preconditions (e.g., some OpenAI-compatible proxies check for the substring `"json"` in messages). The dual-case approach covers the broadest provider set without side effects.

**Implementation**: `_json_object_instruction(response_format)` method on `OpenAIBackend`, cached per response_format class to avoid schema regeneration on every call.

### D5: Nous Auth Refresh Preserved in json_object Path

**Decision**: The `json_object` code branch uses the same `self._client` instance (which wraps auth refresh) as the existing `parse()` path. No separate `create()` call bypasses the auth wrapper.

**Rationale**: The fork's `OpenAIBackend.__init__` wraps the `AsyncOpenAI` client with proactive token refresh (`_ensure_nous_key`) and 401-retry (`_refresh_nous_key_for_retry`). Both `parse()` and `create()` flow through this wrapped client. The `json_object` branch calls `self._client.chat.completions.create()` — the same client instance — so auth refresh is automatically preserved.

**Verification**: Unit test asserting `json_object` mode uses `self._client` (not a raw `AsyncOpenAI` instance).

### D6: Fallback Config Propagation with UNSET Sentinel

**Decision**: `structured_output_mode` is added to `FallbackModelSettings`, `ModelConfig`, and `ResolvedFallbackConfig`. The `FallbackModelSettings` field uses a three-value type: `StructuredOutputMode | Literal["UNSET"] | None = "UNSET"`. Pydantic `env_nested_delimiter="__"` auto-maps `DERIVER_MODEL_CONFIG__FALLBACK__STRUCTURED_OUTPUT_MODE`.

**Rationale**: The QA audit (t_871eda7b) identified that a `None` default makes "not specified" (inherit from primary) indistinguishable from "explicitly cleared" (revert to default `parse()`). Using an `UNSET` sentinel resolves this:
- `UNSET` (default, field absent from env/config) → inherit from primary config
- `"json_object"` / `"json_schema"` → explicit override
- `""` (empty string from env, mapped to `None`) or explicit `None` → revert to default `parse()` behavior

**Implementation**: In `resolve_model_config()`, when `fallback.structured_output_mode == "UNSET"`, copy primary's `structured_output_mode`; otherwise use fallback's explicit value (including `None` for revert-to-default).

### D7: Langfuse Metadata Attribution

**Decision**: Add `structured_output_mode` to the metadata dict passed to `update_current_langfuse_observation()`. No new Langfuse span; the field appears alongside existing `provider` and `namespace` metadata.

**Rationale**: Per `observability-langfuse/spec.md`, operational context metadata dimensions must be preserved. Adding `structured_output_mode` as a metadata field (not a span attribute) follows the existing pattern and enables dashboard filtering without trace pollution.

### D8: Empty/Malformed Response Handling

**Decision**: When `structured_output_mode == "json_object"` and the response content is empty, null, or unparseable, return an empty structured result (zero observations) without entering the repair path. Log at WARNING level.

**Rationale**: Upstream #820 introduces `_parse_or_repair_structured_content` with `empty_on_missing=True` for this case. The current repair path (`validate_and_repair_json`) is designed for responses that are "almost JSON" — it fails hard on empty/prose responses. The `json_object` mode should gracefully degrade to zero observations rather than logging misleading repair failures.

### D9: Request Builder Extra Params Forwarding

**Decision**: `structured_output_mode` is forwarded through `build_config_extra_params()` as an extra key, not as a direct API parameter. The backend reads it from extras and applies mode-specific behavior.

**Rationale**: The mode affects backend behavior (which SDK method to call, whether to inject schema instructions) rather than being a pass-through API parameter. Forwarding via extras keeps the request builder generic and puts mode-specific logic in the backend where it belongs.

### D10: 9Router Translator Compensation via Schema Injection

**Decision**: The `json_object` mode compensates for 9Router's `openai-to-gemini.js` translator dropping `response_format` by injecting the Pydantic schema instruction directly into the prompt messages. No changes to 9Router translator code are in scope.

**Rationale**: 9Router's translator strips both `json_schema` and `json_object` response format types — no `responseSchema` or `responseMimeType` is emitted in the Gemini `generationConfig`. The schema injection into messages is the primary mechanism: the downstream Gemini model uses the prompt instruction as formatting guidance to produce valid JSON, even though the API-level format constraint is lost in translation. A dedicated assertion test (task 4.6) documents this baseline behavior so future translator enhancements can be verified.

---

## Component Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                     Configuration Layer                              │
│                                                                      │
│  src/config.py                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │ StructuredOutputMode = Literal["json_schema", "json_object"]   │ │
│  │                                                                 │ │
│  │ OPENAI_BACKEND_TRANSPORTS = frozenset({                        │ │
│  │   "openai", "ai-router", "nous", "lmstudio"                   │ │
│  │ })                                                              │ │
│  │                                                                 │ │
│  │ ConfiguredModelSettings:                                        │ │
│  │   + structured_output_mode: StructuredOutputMode | None = None │ │
│  │   + @field_validator: reject if transport not in set            │ │
│  │                                                                 │ │
│  │ FallbackModelSettings:                                          │ │
│  │   + structured_output_mode: StructuredOutputMode | None = None │ │
│  │                                                                 │ │
│  │ ResolvedFallbackConfig:                                         │ │
│  │   + structured_output_mode: StructuredOutputMode | None = None │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                              │                                       │
├──────────────────────────────┼───────────────────────────────────────┤
│                     Runtime Layer                │                    │
│                                                  ▼                   │
│  src/llm/runtime.py                                                  │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ select_model_config_for_attempt():                           │    │
│  │   carries structured_output_mode from resolved config        │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                              │                                       │
│  src/llm/request_builder.py  │                                       │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ build_config_extra_params():                                  │    │
│  │   forwards structured_output_mode in extras dict              │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                              │                                       │
├──────────────────────────────┼───────────────────────────────────────┤
│                     Backend Layer                ▼                    │
│                                                                      │
│  src/llm/backends/openai.py                                          │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ complete(messages, response_format, **extras):                │    │
│  │                                                               │    │
│  │   if extras.get("structured_output_mode") == "json_object":  │    │
│  │     ┌─────────────────────────────────────────────────┐      │    │
│  │     │ 1. _json_object_instruction(response_format)    │      │    │
│  │     │    → inject schema + "JSON"/"json" into messages│      │    │
│  │     │ 2. self._client.chat.completions.create(        │      │    │
│  │     │      response_format={"type":"json_object"},    │      │    │
│  │     │      messages=augmented_messages)                │      │    │
│  │     │ 3. _parse_or_repair_structured_content(         │      │    │
│  │     │      content, response_format,                  │      │    │
│  │     │      empty_on_missing=True)                     │      │    │
│  │     └─────────────────────────────────────────────────┘      │    │
│  │   else:  # json_schema / None (default — current behavior)   │    │
│  │     ┌─────────────────────────────────────────────────┐      │    │
│  │     │ self._client.chat.completions.parse(            │      │    │
│  │     │   response_format=response_format)              │      │    │
│  │     │ → existing parse + repair path                  │      │    │
│  │     └─────────────────────────────────────────────────┘      │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                              │                                       │
├──────────────────────────────┼───────────────────────────────────────┤
│                  Observability Layer             ▼                    │
│                                                                      │
│  src/llm/runtime.py (Langfuse integration)                           │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ update_current_langfuse_observation(                          │    │
│  │   model=..., provider=..., namespace=...,                     │    │
│  │   structured_output_mode=...  ← NEW metadata field            │    │
│  │ )                                                              │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

## Data Flow: json_object Mode

```
ENV: DERIVER_MODEL_CONFIG__STRUCTURED_OUTPUT_MODE=json_object
                    │
                    ▼
    ┌─────────────────────────┐
    │ ConfiguredModelSettings │
    │ .structured_output_mode │──── Pydantic validator:
    │ = "json_object"         │     transport ∈ OPENAI_BACKEND_TRANSPORTS? ✓
    └────────────┬────────────┘
                 │
                 ▼
    ┌─────────────────────────┐
    │ FallbackModelSettings   │
    │ .structured_output_mode │──── UNSET: inherit from primary
    │ = "UNSET" (default)     │     Explicit value: override
    └────────────┬────────────┘     None: revert to parse()
                 │
                 ▼
    ┌─────────────────────────┐
    │ ResolvedFallbackConfig  │
    │ inherits mode from      │
    │ primary if UNSET        │
    └────────────┬────────────┘
                 │
                 ▼
    ┌─────────────────────────┐
    │ request_builder         │
    │ extras["structured_     │
    │ output_mode"]="json_obj"│
    └────────────┬────────────┘
                 │
                 ▼
    ┌─────────────────────────┐
    │ OpenAIBackend.complete()│
    │                         │
    │ 1. Build schema instr.  │──→ "Respond in valid JSON/json format
    │ 2. Inject into messages │    matching this schema: {schema}"
    │ 3. create() w/ json_obj │
    │ 4. Parse content        │──→ Success: return parsed model
    │ 5. Empty? → zero result │──→ Failure: WARNING log, empty result
    └────────────┬────────────┘
                 │
                 ▼
    ┌─────────────────────────┐
    │ Langfuse metadata       │
    │ structured_output_mode  │
    │ = "json_object"         │
    └─────────────────────────┘
```

## File Change Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `src/config.py` | MODIFIED | Add `StructuredOutputMode`, `OPENAI_BACKEND_TRANSPORTS`, field + validator on `ConfiguredModelSettings`, `FallbackModelSettings`, `ResolvedFallbackConfig` |
| `src/llm/backends/openai.py` | MODIFIED | Add `_json_object_instruction()`, `_parse_or_repair_structured_content()`, `json_object` branch in `complete()` |
| `src/llm/request_builder.py` | MODIFIED | Forward `structured_output_mode` in `build_config_extra_params()` |
| `src/llm/runtime.py` | MODIFIED | Carry `structured_output_mode` in `select_model_config_for_attempt()`, add to Langfuse metadata |
| `tests/llm/test_model_config.py` | MODIFIED | Add transport validation tests for `ai-router` + rejection tests for `anthropic`/`gemini` |
| `tests/llm/test_backends/test_openai.py` | MODIFIED | Add `json_object` mode backend tests: request shape, schema injection, empty handling, auth client usage |
| `tests/llm/test_backends/test_nous_autorefresh.py` | MODIFIED | Add Nous auth preservation test for `json_object` mode |
| `tests/` (9Router assertion) | ADDED | Baseline test documenting 9Router translator drops `response_format` |

## Constraints

1. No changes to `anthropic` or `gemini` backend implementations.
2. No changes to 9Router translator code (document current behavior only).
3. `json_schema` mode (current default) behavior must remain identical.
4. All existing 46 focused baseline tests must continue to pass.
5. No new Python dependencies.
