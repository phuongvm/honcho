# Proposal: Sync Upstream Structured Output Mode

> **Change Name**: `sync-upstream-structured-output-mode`
> **Date**: 2026-08-20
> **Author**: Designer
> **Status**: Draft
> **Type**: Code-Implement

---

## Problem Statement

The Honcho Deriver agent fails to extract observations when routed through 9Router/Antigravity to Gemini-class models. The failure chain:

1. `OpenAIBackend.complete()` calls `chat.completions.parse()` with a Pydantic `PromptRepresentation` response model.
2. 9Router's `openai-to-gemini.js` translator drops `response_format` (both `json_schema` and `json_object` variants) — no `responseSchema` or `responseMimeType` is emitted in the Gemini generationConfig.
3. Without schema constraints, the model returns conversational Markdown prose.
4. Pydantic parse fails, `validate_and_repair_json()` fails on prose text → `❌ Repair failed: Expecting value: line 1 column 1` → zero observations.

**Evidence**: `honcho-deriver-1` logs (2026-08-20 01:50:57) show this exact failure path for messages 16549:16573 in `hermes_agent4070/hermes-agent`.

## Upstream Context

Upstream `plastic-labs/honcho` addressed this class of issue for loose OpenAI-compatible proxies (Z.AI GLM, Ollama, vLLM) in:

- **PR #820** (commit `a0cc938f`): Adds `StructuredOutputMode` config, `json_object` mode that skips `parse()`, injects Pydantic schema into prompt messages, calls `create(response_format={"type":"json_object"})`.
- **PR #887** (commit `de1b4101`): Adds lowercase `"json"` to injected instructions — required by providers enforcing case-sensitive JSON-object preconditions.

## Fork Incompatibilities (from Reviewer Audit t_5995129a)

Unmodified upstream #820 is **not directly applicable** to this fork:

1. **Transport Capability Gating**: Upstream validates `transport != "openai"` as error. This fork declares `ai-router`, `nous`, and `lmstudio` as distinct transports, all backed by `OpenAIBackend`. Unmodified cherry-pick raises `ValidationError` on `transport="ai-router"`.
2. **Nous Auth Refresh**: The `json_object` code path calls `chat.completions.create()` directly — must preserve the fork's proactive & 401 token refresh wrappers (`_ensure_nous_key`, `_refresh_nous_key_for_retry`).
3. **Langfuse Telemetry**: Attempt attribution and `structured_output_mode` metadata must flow through existing Langfuse generation spans without regressing trace quality.
4. **Fallback Propagation**: `structured_output_mode` must propagate to `ResolvedFallbackConfig` so secondary models in fallback chains inherit the mode.
5. **Merge Blast Radius**: Local branch is 14 ahead / 130 behind upstream. Full merge introduces Scopes SDK, Redis, Dialectic schema changes — disproportionate for this narrow fix.

## Proposed Solution

**Targeted port of #820 + #887**, adapted for this fork's custom transports:

1. Port `StructuredOutputMode` type and config propagation from #820.
2. Adapt transport validation to use backend-capability lookup rather than literal `transport == "openai"` — allow `{"openai", "ai-router", "nous", "lmstudio"}`, reject native `{"anthropic", "gemini"}`.
3. Port `json_object` mode branch in `OpenAIBackend.complete()` from #820 + lowercase `"json"` injection from #887.
4. Preserve Nous auth refresh wrapping around the new `create()` call path.
5. Forward `structured_output_mode` through `build_config_extra_params()` and `select_model_config_for_attempt()`.
6. Add `structured_output_mode` to Langfuse generation metadata.
7. Add fork-specific tests: config validation for `ai-router`, backend request shape, fallback inheritance (UNSET sentinel), and a dedicated 9Router translator assertion test (task 4.6) documenting that `response_format` is currently dropped — establishing a baseline so future translator enhancements can be verified.

## Scope

### In Scope
- `src/config.py`: `StructuredOutputMode`, `ConfiguredModelSettings`, `FallbackModelSettings`, `ModelConfig`, `ResolvedFallbackConfig`, transport validation
- `src/llm/backends/openai.py`: `json_object` mode branch, schema instruction injection, `_parse_or_repair_structured_content`
- `src/llm/request_builder.py`: Forward `structured_output_mode` in extras
- `src/llm/runtime.py`: Carry mode in attempt selection
- `tests/llm/test_model_config.py`: Config validation tests
- `tests/llm/test_backends/test_openai.py`: Backend behavior tests
- Delta spec: `openspec/specs/ai-router-transport/spec.md`

### Out of Scope
- Full upstream merge (130 commits)
- Upstream Scopes SDK, Redis, Dialectic structured outputs, combined tools+structured output
- 9Router translator enhancement (documenting current behavior only)
- `anthropic` and `gemini` native transport structured output support

## Acceptance Criteria

1. `ConfiguredModelSettings(model="cb-gemini-flash-high", transport="ai-router", structured_output_mode="json_object")` validates without error.
2. All baseline focused tests pass + new fork-specific structured output tests pass.
3. `OpenAIBackend.complete()` in `json_object` mode: skips `parse()`, calls `create()` with `response_format={"type":"json_object"}`, injects schema instructions containing both `"JSON"` and `"json"`.
4. Nous auth refresh is preserved in `json_object` code path.
5. Langfuse generation metadata includes `structured_output_mode` field.
6. `structured_output_mode` propagates through fallback config resolution.
7. Live E2E: Deriver processes queue via 9Router/Antigravity with `json_object` mode → observations saved, zero `❌ Repair failed` errors.

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| 9Router still drops `response_format` in `json_object` mode | Schema injection into prompt compensates; Gemini uses prompt as formatting guide | Document 9Router limitation in test; verify live E2E output is valid JSON |
| `json_object` mode on providers that don't support it | Config validation error on startup | Transport capability gating rejects unsupported transports at config time |
| Nous auth bypass in new code path | 401 failures on token expiry | Explicit test that `json_object` path uses the same auth-wrapped client |
| Fallback model without `structured_output_mode` | Fallback reverts to `parse()` path silently | Propagation to `ResolvedFallbackConfig` ensures fallback inherits mode |

## Affected Specs

- `openspec/specs/ai-router-transport/spec.md` — MODIFIED (delta spec with 7 ADDED requirements, 2 MODIFIED requirements with scenario-level `(UNCHANGED)` / `(ADDED)` tags preserving all base scenarios)
- `openspec/specs/llm-model-fallback/spec.md` — REFERENCED, no delta required. **Cross-capability rationale**: The ai-router delta spec's "Fallback config inherits structured_output_mode" requirement explicitly defines the inheritance and override behavior at the consumer boundary. Although `llm-model-fallback` defines independent model fallback configs, `structured_output_mode` adopts the `UNSET` sentinel pattern (design D6) to allow seamless inheritance from primary settings unless explicitly cleared or overridden.
- `openspec/specs/observability-langfuse/spec.md` — REFERENCED, no delta required. **Cross-capability rationale**: The `structured_output_mode` attribute is added directly to generation metadata via `update_current_langfuse_observation()`. This extends operational metadata alongside `provider` and `namespace` without altering core observation semantics.
