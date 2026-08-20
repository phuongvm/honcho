## MODIFIED Requirements

### Requirement: AI Router transport declaration
The system SHALL support declaration of `"ai-router"` in `ModelTransport` AND maintain its presence in the `OPENAI_BACKEND_TRANSPORTS` set through upstream's refactored lazy SDK loading and registry architecture.

#### Scenario: User sets model transport to ai-router (UNCHANGED)
- **WHEN** a dialectic/model config uses `TRANSPORT=ai-router`
- **THEN** the system confirms the configuration is valid (validation success)

#### Scenario: AI-Router transport survives upstream registry refactor (ADDED)
- **WHEN** upstream refactors `BackendRegistry` to use lazy SDK loading with `_get_openai_client()` factory
- **THEN** the registry SHALL dispatch `transport="ai-router"` through the OpenAI-compatible backend path using `OPENAI_BACKEND_TRANSPORTS` membership check

#### Scenario: AI-Router included in OPENAI_BACKEND_TRANSPORTS after merge (ADDED)
- **WHEN** `src/config.py` integrates upstream's new settings sections (Redis Cluster, Scopes)
- **THEN** `OPENAI_BACKEND_TRANSPORTS` SHALL still contain `{"openai", "ai-router", "nous", "lmstudio"}` with identical semantics

### Requirement: Client resolution for AI Router
The system SHALL use global configuration when initializing the Backend Client for `ai-router` if model-level `base_url` override is absent, compatible with upstream's new client factory pattern.

#### Scenario: Default client resolution (UNCHANGED)
- **WHEN** model config uses `transport="ai-router"` without `base_url` override
- **THEN** BackendRegistry uses `settings.LLM.AI_ROUTER_BASE_URL` and `settings.LLM.AI_ROUTER_API_KEY` to initialize `AsyncOpenAI` client

#### Scenario: Override client resolution (UNCHANGED)
- **WHEN** model config uses `transport="ai-router"` with a specific `base_url` override
- **THEN** BackendRegistry prioritizes the override `base_url` combined with the global API key (or override API key if present)

#### Scenario: Default client resolution through refactored registry (ADDED)
- **WHEN** model config uses `transport="ai-router"` without `base_url` override AND upstream's `_get_openai_client()` factory is the new entry point
- **THEN** the factory SHALL use `settings.LLM.AI_ROUTER_BASE_URL` and `settings.LLM.AI_ROUTER_API_KEY` to initialize `AsyncOpenAI` client

#### Scenario: LMStudio transport coexists with AI-Router (ADDED)
- **WHEN** `ModelTransport` includes both `"ai-router"` and `"lmstudio"` after merge
- **THEN** each transport SHALL resolve to its own `base_url`/`api_key` pair independently via `settings.LLM.LMSTUDIO_BASE_URL` and `settings.LLM.AI_ROUTER_BASE_URL` respectively

### Requirement: Global configuration for AI Router
The system SHALL preserve `LLM_AI_ROUTER_API_KEY` and `LLM_AI_ROUTER_BASE_URL` environment variable bindings in `LLMSettings` after integrating upstream's expanded configuration schema (Redis Cluster, Scopes, telemetry).

#### Scenario: User provides global AI Router environment variables (UNCHANGED)
- **WHEN** file `.env` has `LLM_AI_ROUTER_API_KEY` and `LLM_AI_ROUTER_BASE_URL` set
- **THEN** `LLMSettings` automatically loads these variables into `AI_ROUTER_API_KEY` and `AI_ROUTER_BASE_URL`

#### Scenario: AI Router env vars coexist with upstream config additions (ADDED)
- **WHEN** `src/config.py` is merged with upstream's `CACHE.CLUSTER`, `SCOPES`, and telemetry settings
- **THEN** `LLMSettings` SHALL still load `AI_ROUTER_API_KEY` and `AI_ROUTER_BASE_URL` from environment variables with identical Pydantic field definitions
