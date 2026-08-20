## MODIFIED Requirements

### Requirement: LLM calls are traced as Langfuse generations
When Langfuse tracing is enabled, each `honcho_llm_call` invocation MUST be recorded as a Langfuse observation with generation semantics. After upstream merge, the `@conditional_observe(name="LLM Call", as_type="generation")` decorator MUST remain functional within upstream's refactored tool loop and capture infrastructure.

#### Scenario: Generation observation type is used (UNCHANGED)
- **WHEN** `LANGFUSE_PUBLIC_KEY` is configured and application code executes `honcho_llm_call`
- **THEN** the active Langfuse observation for that call is created with `as_type="generation"`

#### Scenario: Generation observation survives upstream tool_loop refactor (ADDED)
- **WHEN** upstream separates `tool_loop.py` as a standalone module and introduces `capture.py` for response capture
- **THEN** the `@conditional_observe` decorator on `honcho_llm_call` SHALL continue to create Langfuse generation observations with `as_type="generation"`

### Requirement: Generation model is attributed from attempt planning
The implementation MUST set the generation `model` field from the resolved model for the active attempt. `update_current_langfuse_observation()` MUST remain the mechanism for updating generation metadata after `plan_attempt` resolution.

#### Scenario: Model field follows selected attempt model (UNCHANGED)
- **WHEN** `plan_attempt` resolves provider/model (including final-attempt fallback)
- **THEN** `update_current_langfuse_observation` updates the active generation via `update_current_generation(model=<resolved-model>)`

#### Scenario: Model field follows selected attempt model through refactored runtime (ADDED)
- **WHEN** `plan_attempt` resolves provider/model (including final-attempt fallback) within upstream's restructured `runtime.py` lifecycle
- **THEN** `update_current_langfuse_observation` SHALL update the active generation via `update_current_generation(model=<resolved-model>)` with the same call semantics

#### Scenario: Langfuse metadata forwarding through upstream API refactor (ADDED)
- **WHEN** upstream refactors `src/llm/api.py` provider selection loop
- **THEN** `update_current_langfuse_observation()` SHALL still receive and forward `provider`, `namespace`, `is_fallback`, and `structured_output_mode` metadata fields

### Requirement: Provider and namespace remain in metadata
Langfuse generation updates MUST include operational context metadata for provider and namespace. After upstream merge, these metadata dimensions MUST be preserved through any upstream exporter or telemetry infrastructure changes.

#### Scenario: Metadata dimensions are preserved (UNCHANGED)
- **WHEN** generation data is updated for an LLM call
- **THEN** metadata includes `provider` and `namespace` values used by Honcho routing context

#### Scenario: Metadata dimensions preserved through upstream telemetry changes (ADDED)
- **WHEN** upstream modifies telemetry/exporter infrastructure in `src/telemetry/logging.py` or related modules
- **THEN** Langfuse generation metadata SHALL still include `provider` and `namespace` values used by Honcho routing context

#### Scenario: is_fallback metadata survives merge (ADDED)
- **WHEN** a fallback event occurs and `update_current_langfuse_observation(is_fallback=True)` is called
- **THEN** the Langfuse generation metadata SHALL include `is_fallback: true` to distinguish fallback processing from normal processing

### Requirement: Langfuse Observability Tracing
Summarization tracing MUST create top-level `GENERATION` observations without nested `SPAN` wrappers. The direct `track_name` passing to `honcho_llm_call` in `src/utils/summarizer.py` MUST be preserved through upstream's summary prompt refactor.

#### Scenario: Summarization Tracing (UNCHANGED)
- **WHEN** a background task or explicit request triggers `create_short_summary` or `create_long_summary`
- **THEN** the system MUST trace it as a top-level `GENERATION` observation without nested `SPAN` wrappers to ensure accurate model and token attribution in the Langfuse UI

#### Scenario: Summarization tracing through upstream summarizer refactor (ADDED)
- **WHEN** upstream refactors summary prompts in `src/utils/summarizer.py`
- **THEN** the system SHALL maintain direct `track_name` passing to `honcho_llm_call` and trace as top-level `GENERATION` observation without nested `SPAN` wrappers
