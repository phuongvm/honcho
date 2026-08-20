## 1. Configuration Layer & Transport Validation

- [ ] 1.1 Add `StructuredOutputMode = Literal["json_schema", "json_object"]` and `OPENAI_BACKEND_TRANSPORTS = frozenset({"openai", "ai-router", "nous", "lmstudio"})` in `src/config.py`
- [ ] 1.2 Add `structured_output_mode: StructuredOutputMode | None = None` to `ConfiguredModelSettings`, `FallbackModelSettings`, `ResolvedFallbackConfig`, and `ModelConfig` in `src/config.py`
- [ ] 1.3 Add field validator on `ConfiguredModelSettings` and `FallbackModelSettings` in `src/config.py` enforcing that `structured_output_mode` is permitted only on transports in `OPENAI_BACKEND_TRANSPORTS` (allow `ai-router`, `nous`, `lmstudio`, `openai`; reject `anthropic`, `gemini`)
- [ ] 1.4 Update `resolve_model_config()` in `src/config.py` to propagate `structured_output_mode` from `ConfiguredModelSettings` into `ModelConfig` and its nested `ResolvedFallbackConfig`

## 2. Request Assembly & Runtime Propagation

- [ ] 2.1 Update `build_config_extra_params()` in `src/llm/request_builder.py` to include `structured_output_mode` in `extra_params` when configured on `ModelConfig`
- [ ] 2.2 Update `select_model_config_for_attempt()` in `src/llm/runtime.py` to ensure `structured_output_mode` is preserved during primary and fallback selection
- [ ] 2.3 Update `update_current_langfuse_observation()` in `src/llm/runtime.py` to accept and record `structured_output_mode` in Langfuse generation metadata

## 3. OpenAI Backend & Structured Output Engine

- [ ] 3.1 Implement `_json_object_instruction(response_format)` helper in `src/llm/backends/openai.py` with caching and dual-case `"JSON"` and `"json"` schema instruction prompt injection per upstream #820 + #887
- [ ] 3.2 Implement `_parse_or_repair_structured_content()` in `src/llm/backends/openai.py` with `empty_on_missing=True` graceful fallback (returns empty model instance on empty/unparseable prose without throwing repair exceptions)
- [ ] 3.3 Add `structured_output_mode == "json_object"` execution branch to `OpenAIBackend.complete()` in `src/llm/backends/openai.py` using `self._client.chat.completions.create(response_format={"type": "json_object"}, ...)` and preserving Nous auth proactive refresh (`_ensure_nous_key`) and 401 retry (`_refresh_nous_key_for_retry`)
- [ ] 3.4 Preserve default `json_schema` / `parse()` path in `OpenAIBackend.complete()` when `structured_output_mode` is None or `"json_schema"`

## 4. Unit & Regression Testing

- [ ] 4.1 Add config validation tests in `tests/llm/test_model_config.py` verifying `structured_output_mode="json_object"` succeeds for `ai-router`, `nous`, `lmstudio`, `openai` and raises `ValidationError` for `anthropic` and `gemini`
- [ ] 4.2 Add fallback inheritance and override tests in `tests/llm/test_model_config.py` verifying fallback models inherit or override `structured_output_mode`
- [ ] 4.3 Add backend unit tests in `tests/llm/test_backends/test_openai.py` verifying `json_object` mode request shape: calls `create()` with `{"type": "json_object"}`, injects schema instructions with `"JSON"`/`"json"`, and does not mutate input caller messages
- [ ] 4.4 Add empty and malformed response tests in `tests/llm/test_backends/test_openai.py` verifying zero observations returned gracefully with WARNING log and no `❌ Repair failed` exception
- [ ] 4.5 Add Nous auth preservation test in `tests/llm/test_backends/test_nous_autorefresh.py` verifying `json_object` mode utilizes the auth-wrapped `self._client` and retries on 401
- [ ] 4.6 Run full focused test suite: `uv run pytest tests/llm/` and verify all tests pass

## 5. Live E2E Verification & Audit Gate

- [ ] 5.1 Configure `DERIVER_MODEL_CONFIG__STRUCTURED_OUTPUT_MODE=json_object` in test/staging environment with `ai-router` transport
- [ ] 5.2 Ingest test message payload and trigger Deriver queue processing
- [ ] 5.3 Verify Deriver extracts observations successfully (`Observation Count > 0`) without `❌ Repair failed` in logs
- [ ] 5.4 Verify Langfuse telemetry spans record `structured_output_mode: "json_object"` in generation metadata
