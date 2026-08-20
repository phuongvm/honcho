## MODIFIED Requirements

### Requirement: System SHALL support configurable LLM model fallback per agent
The system SHALL allow operators to configure a fallback model for each agent (Deriver, Dialectic, Dreamer, Summary) independently. When the primary model fails, the system SHALL automatically switch to the configured fallback model. After upstream merge, `FallbackModelSettings` and `ResolvedFallbackConfig` SHALL remain functional within upstream's restructured runtime lifecycle.

#### Scenario: Fallback configured for Deriver (UNCHANGED)
- **WHEN** `DERIVER_MODEL_CONFIG__FALLBACK__TRANSPORT` and `DERIVER_MODEL_CONFIG__FALLBACK__MODEL` are set in environment
- **THEN** the Deriver agent SHALL use the configured fallback model when its primary model fails

#### Scenario: Fallback configured for Dialectic per reasoning level (UNCHANGED)
- **WHEN** `DIALECTIC_LEVELS__<level>__MODEL_CONFIG__FALLBACK__TRANSPORT` and `DIALECTIC_LEVELS__<level>__MODEL_CONFIG__FALLBACK__MODEL` are set in environment (where `<level>` is `minimal`, `low`, `medium`, `high`, or `max`)
- **THEN** the Dialectic agent SHALL use the configured fallback model for that reasoning level when its primary model fails

#### Scenario: Fallback configured for Dreamer Deduction specialist (UNCHANGED)
- **WHEN** `DREAM_DEDUCTION_MODEL_CONFIG__FALLBACK__TRANSPORT` and `DREAM_DEDUCTION_MODEL_CONFIG__FALLBACK__MODEL` are set in environment
- **THEN** the Dreamer Deduction specialist SHALL use the configured fallback model when its primary model fails

#### Scenario: Fallback configured for Dreamer Induction specialist (UNCHANGED)
- **WHEN** `DREAM_INDUCTION_MODEL_CONFIG__FALLBACK__TRANSPORT` and `DREAM_INDUCTION_MODEL_CONFIG__FALLBACK__MODEL` are set in environment
- **THEN** the Dreamer Induction specialist SHALL use the configured fallback model when its primary model fails

#### Scenario: Fallback configured for Summary (UNCHANGED)
- **WHEN** `SUMMARY_MODEL_CONFIG__FALLBACK__TRANSPORT` and `SUMMARY_MODEL_CONFIG__FALLBACK__MODEL` are set in environment
- **THEN** the Summary generator SHALL use the configured fallback model when its primary model fails

#### Scenario: Fallback config survives upstream runtime refactor (ADDED)
- **WHEN** upstream restructures `src/llm/runtime.py` with new lifecycle hooks and `src/llm/api.py` with modular tool loop separation
- **THEN** `FallbackModelSettings`, `ResolvedFallbackConfig`, and per-agent fallback env vars SHALL continue to resolve correctly

### Requirement: Fallback SHALL trigger on first model failure
The system SHALL switch to the fallback model on the **first** detected failure (rate limit, timeout, API error), not only on the final retry attempt. This reduces latency during provider outages. After upstream merge, `AttemptPlan` selection and `select_model_config_for_attempt()` SHALL remain the mechanism for fast failover.

#### Scenario: Primary model returns rate limit error (UNCHANGED)
- **WHEN** the primary model returns a 429 (Too Many Requests) error on the first attempt
- **THEN** the system SHALL immediately switch to the fallback model for the next attempt without exhausting all primary retries

#### Scenario: Primary model times out (UNCHANGED)
- **WHEN** the primary model exceeds the configured timeout on the first attempt
- **THEN** the system SHALL immediately switch to the fallback model for the next attempt

#### Scenario: Primary model returns server error (UNCHANGED)
- **WHEN** the primary model returns a 5xx error on the first attempt
- **THEN** the system SHALL immediately switch to the fallback model for the next attempt

#### Scenario: AttemptPlan preserved through upstream runtime restructure (ADDED)
- **WHEN** upstream refactors `src/llm/runtime.py` lifecycle and `src/llm/api.py` provider selection loop
- **THEN** `AttemptPlan` dataclass, `select_model_config_for_attempt()` function, and fast failover on 429/5xx SHALL remain operational with identical semantics

### Requirement: System SHALL log fallback events for observability
The system SHALL emit a log entry at WARNING level every time a fallback event occurs, including: agent name, primary provider/model, fallback provider/model, and failure reason. Logging SHALL be compatible with upstream's refactored `compact|rich` telemetry logging format.

#### Scenario: Fallback triggered for Deriver (UNCHANGED)
- **WHEN** the Deriver agent falls back from primary to fallback model
- **THEN** the system SHALL log a WARNING message containing: agent=deriver, primary=<provider>/<model>, fallback=<provider>/<model>, reason=<error>

#### Scenario: Fallback triggered for Dialectic (UNCHANGED)
- **WHEN** the Dialectic agent falls back from primary to fallback model
- **THEN** the system SHALL log a WARNING message containing: agent=dialectic, primary=<provider>/<model>, fallback=<provider>/<model>, reason=<error>

#### Scenario: Fallback logging integrates with upstream logging refactor (ADDED)
- **WHEN** upstream refactors `src/telemetry/logging.py` to `compact|rich` performance format
- **THEN** fallback WARNING log entries SHALL be emitted in the new format while preserving all existing fields (agent, primary, fallback, reason)

### Requirement: System SHALL fail only when all models in chain are exhausted
The system SHALL only return an error to the caller when both the primary model AND the fallback model have been tried and failed. If the fallback succeeds, the response SHALL be returned normally.

#### Scenario: Primary fails, fallback succeeds (UNCHANGED)
- **WHEN** the primary model fails and the fallback model succeeds
- **THEN** the system SHALL return the fallback model's response as if it were a normal response

#### Scenario: Both primary and fallback fail (UNCHANGED)
- **WHEN** both the primary model and the fallback model fail after exhausting their retry attempts
- **THEN** the system SHALL return an error indicating all models in the chain were exhausted

### Requirement: Fallback SHALL support cross-provider failover
The fallback model MAY use a different provider than the primary model (e.g., primary=openai, fallback=anthropic). The system SHALL handle cross-provider parameter mapping automatically, including any new transport types introduced by upstream.

#### Scenario: Cross-provider fallback from OpenAI to Anthropic (UNCHANGED)
- **WHEN** primary is `openai/gpt-4o` and fallback is `anthropic/claude-sonnet-4`
- **THEN** the system SHALL automatically map transport parameters (reasoning_effort, thinking_budget_tokens) to provider-appropriate values

#### Scenario: Cross-provider fallback from Nous to OpenAI (UNCHANGED)
- **WHEN** primary is `nous/model` and fallback is `openai/gpt-4o-mini`
- **THEN** the system SHALL automatically map transport parameters to provider-appropriate values

#### Scenario: Cross-provider fallback compatible with upstream transport additions (ADDED)
- **WHEN** upstream adds new transport types (e.g., `bedrock`, `vertex`)
- **THEN** the fallback mechanism SHALL gracefully handle cross-provider failover to/from these new transports using the same `AttemptPlan` selection logic

### Requirement: Fallback configuration SHALL be backward compatible
When no fallback is configured, the system SHALL behave exactly as before — using only the primary model with existing retry logic. Fallback is opt-in via configuration.

#### Scenario: No fallback configured (UNCHANGED)
- **WHEN** no `FALLBACK__TRANSPORT` / `FALLBACK__MODEL` environment variables are set
- **THEN** the system SHALL use only the primary model with existing retry behavior (no change from current behavior)

#### Scenario: Partial fallback config (only transport, no model) (UNCHANGED)
- **WHEN** `FALLBACK__TRANSPORT` is set but `FALLBACK__MODEL` is not set
- **THEN** the system SHALL ignore the incomplete fallback config and use only the primary model
