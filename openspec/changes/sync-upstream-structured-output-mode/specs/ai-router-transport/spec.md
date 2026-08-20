## ADDED Requirements

### Requirement: Structured output mode configuration for OpenAI-backend transports
The system SHALL support a `structured_output_mode` configuration parameter on any transport backed by `OpenAIBackend`. When set to `"json_object"`, the backend SHALL skip the SDK `parse()` method and use `create()` with `response_format={"type":"json_object"}` instead, injecting the Pydantic schema as a prompt instruction.

#### Scenario: ai-router transport with json_object mode validates successfully
- **WHEN** `ConfiguredModelSettings` is constructed with `transport="ai-router"` and `structured_output_mode="json_object"`
- **THEN** Pydantic validation succeeds without error

#### Scenario: nous transport with json_object mode validates successfully
- **WHEN** `ConfiguredModelSettings` is constructed with `transport="nous"` and `structured_output_mode="json_object"`
- **THEN** Pydantic validation succeeds without error

#### Scenario: lmstudio transport with json_object mode validates successfully
- **WHEN** `ConfiguredModelSettings` is constructed with `transport="lmstudio"` and `structured_output_mode="json_object"`
- **THEN** Pydantic validation succeeds without error

#### Scenario: Native anthropic transport rejects structured_output_mode
- **WHEN** `ConfiguredModelSettings` is constructed with `transport="anthropic"` and `structured_output_mode="json_object"`
- **THEN** Pydantic validation raises `ValidationError` indicating structured_output_mode is not supported on native anthropic transport

#### Scenario: Native gemini transport rejects structured_output_mode
- **WHEN** `ConfiguredModelSettings` is constructed with `transport="gemini"` and `structured_output_mode="json_object"`
- **THEN** Pydantic validation raises `ValidationError` indicating structured_output_mode is not supported on native gemini transport

### Requirement: Schema instruction injection in json_object mode
When `structured_output_mode == "json_object"`, the `OpenAIBackend` SHALL inject a system message containing the Pydantic response model's JSON schema into the messages array. The instruction SHALL contain both uppercase `"JSON"` and lowercase `"json"` keywords.

#### Scenario: Schema instruction injected for Deriver PromptRepresentation
- **WHEN** `OpenAIBackend.complete()` is called with `structured_output_mode="json_object"` and `response_format=PromptRepresentation`
- **THEN** the messages sent to the API include a system message containing the JSON schema of `PromptRepresentation`, with both `"JSON"` and `"json"` in the instruction text

#### Scenario: Original caller messages are not mutated
- **WHEN** `OpenAIBackend.complete()` injects schema instructions in `json_object` mode
- **THEN** the original `messages` list passed by the caller is not modified; a copy is used for injection

### Requirement: json_object mode uses create() instead of parse()
When `structured_output_mode == "json_object"`, the `OpenAIBackend` SHALL call `chat.completions.create()` with `response_format={"type":"json_object"}` instead of `chat.completions.parse()`.

#### Scenario: create() called with response_format type json_object
- **WHEN** `OpenAIBackend.complete()` is called with `structured_output_mode="json_object"`
- **THEN** the backend calls `self._client.chat.completions.create()` with `response_format={"type":"json_object"}` and does NOT call `self._client.beta.chat.completions.parse()`

### Requirement: Graceful empty/malformed response handling in json_object mode
When `structured_output_mode == "json_object"` and the response content is empty, null, or unparseable JSON, the backend SHALL return an empty structured result (zero observations) rather than entering the JSON repair path. The event SHALL be logged at WARNING level.

#### Scenario: Empty response returns zero observations
- **WHEN** `OpenAIBackend.complete()` receives an empty content response in `json_object` mode
- **THEN** the method returns an empty/default instance of the response_format model without raising an exception and without logging `❌ Repair failed`

#### Scenario: Prose response returns zero observations
- **WHEN** `OpenAIBackend.complete()` receives prose text (non-JSON) in `json_object` mode
- **THEN** the method returns an empty/default instance of the response_format model and logs a WARNING about unparseable content

### Requirement: Nous auth refresh preserved in json_object path
The `json_object` mode code path SHALL use the same auth-wrapped `self._client` instance as the `parse()` path, ensuring Nous proactive token refresh and 401 retry behavior are preserved.

#### Scenario: json_object mode uses auth-wrapped client
- **WHEN** `OpenAIBackend.complete()` executes the `json_object` branch with `transport="nous"`
- **THEN** the `create()` call flows through the same `self._client` that has `_ensure_nous_key` and `_refresh_nous_key_for_retry` wrappers

### Requirement: Fallback config inherits structured_output_mode
The `structured_output_mode` setting SHALL propagate from `ConfiguredModelSettings` through `FallbackModelSettings` and `ResolvedFallbackConfig`, so fallback models in a chain inherit the mode unless explicitly overridden. The `FallbackModelSettings.structured_output_mode` field SHALL use a three-value sentinel (`UNSET` / `"json_schema"` / `"json_object"`) to distinguish "not specified" (inherit from primary) from "explicitly cleared" (`None` → revert to `parse()` default).

#### Scenario: Fallback inherits json_object from primary (field UNSET)
- **WHEN** primary config has `structured_output_mode="json_object"` and fallback config's `structured_output_mode` is `UNSET` (field absent from env/config)
- **THEN** the resolved fallback config carries `structured_output_mode="json_object"`

#### Scenario: Fallback explicitly overrides mode to json_schema
- **WHEN** primary config has `structured_output_mode="json_object"` and fallback explicitly sets `structured_output_mode="json_schema"`
- **THEN** the resolved fallback config uses `structured_output_mode="json_schema"` (reverts to `parse()` behavior)

#### Scenario: Fallback explicitly clears mode to None
- **WHEN** primary config has `structured_output_mode="json_object"` and fallback explicitly sets `FALLBACK__STRUCTURED_OUTPUT_MODE=""` (empty string, mapped to `None`)
- **THEN** the resolved fallback config uses `structured_output_mode=None` (reverts to default `parse()` behavior, does NOT inherit from primary)

### Requirement: Structured output mode forwarded through 9Router transport
When `structured_output_mode == "json_object"` is set on an `ai-router` transport config, the `OpenAIBackend` SHALL inject the Pydantic schema instruction into the prompt (compensating for 9Router translator dropping `response_format`) and call `create()` with `response_format={"type":"json_object"}`. The 9Router translator's current behavior of dropping `response_format` is a known limitation; the schema injection into messages is the primary mechanism ensuring the downstream model produces valid JSON.

#### Scenario: 9Router drops response_format but schema injection compensates
- **WHEN** `OpenAIBackend.complete()` is called with `transport="ai-router"` and `structured_output_mode="json_object"` routed through 9Router to Gemini
- **THEN** the injected schema instruction in the messages causes the downstream model to return valid JSON, even though 9Router drops the `response_format` parameter

## MODIFIED Requirements

### Requirement: AI Router transport declaration (MODIFIED)
The system SHALL support declaring `"ai-router"` within `ModelTransport`, **including optional `structured_output_mode` configuration** when the transport is backed by `OpenAIBackend`.

#### Scenario: User sets model transport to ai-router (UNCHANGED)
- **WHEN** a model config uses `transport="ai-router"`
- **THEN** the system validates the configuration successfully

#### Scenario: User sets model transport to ai-router with structured_output_mode (ADDED)
- **WHEN** a model config uses `transport="ai-router"` and `structured_output_mode="json_object"`
- **THEN** the system validates both fields successfully and routes structured output through the `json_object` code path

### Requirement: Client resolution for AI Router (MODIFIED)
The system SHALL use global configuration when initializing the Backend Client for `ai-router` if specific `base_url` configuration is omitted on the model, **and SHALL carry `structured_output_mode` from config into the backend's `complete()` extras** if set.

#### Scenario: Default client resolution (UNCHANGED)
- **WHEN** model config uses `transport="ai-router"` without `base_url` override
- **THEN** BackendRegistry uses `settings.LLM.AI_ROUTER_BASE_URL` and `settings.LLM.AI_ROUTER_API_KEY` to initialize the `AsyncOpenAI` client

#### Scenario: Override client resolution (UNCHANGED)
- **WHEN** model config uses `transport="ai-router"` with an explicit `base_url` override
- **THEN** BackendRegistry prioritizes the override `base_url` with the global API key (or override API key if provided)

#### Scenario: ai-router client carries structured_output_mode in extras (ADDED)
- **WHEN** model config uses `transport="ai-router"` with `structured_output_mode="json_object"`
- **THEN** `build_config_extra_params()` includes `structured_output_mode="json_object"` in the extras dict passed to `OpenAIBackend.complete()`
