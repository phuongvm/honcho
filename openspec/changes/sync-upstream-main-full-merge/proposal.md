## Why

Our production fork (`origin/main`, SHA `c00a2a876d28f17af632059876a33a23df349d15`) is **130 commits behind** `upstream/main` (`plastic-labs/honcho`, SHA `7bafee5de1b77a619f56c32ba59d9dcc0e115449`). The upstream branch contains critical improvements: Scopes-based CRUD refactoring, Redis Cluster caching, agent-tool architecture refactors (Deriver/Dialectic/Dreamer), Alembic migration enhancements, SDK/CLI updates, and MCP server extensions. Delaying the merge increases the divergence cost and blocks adoption of upstream security patches and performance improvements.

The merge must guarantee **100% preservation of 6 proprietary fork capabilities** — any regression in AI-Router transport, Nous auth auto-refresh, structured output mode, multi-tier model fallback, Langfuse observability metadata, or LMStudio transport constitutes a blocking failure.

## What Changes

- **Staged monolithic merge** of 130 upstream commits into `origin/main` via a dedicated `merge/upstream-sync` branch, resolving 14 conflict files across 3 stages.
- **Stage 1 — Foundations & SDKs**: Resolve non-LLM conflicts (MCP `config.ts`, `bun.lock`), accept non-conflicted upstream additions (Scopes CRUD, Redis Cluster config, SDKs, CLI, docs, CI).
- **Stage 2 — System Reconcile & Preservation**: Reconcile the 12 core conflict files in `src/config.py`, `src/llm/*`, `src/telemetry/*`, `src/utils/summarizer.py`, and `tests/` — integrating upstream refactors while preserving all 6 fork capabilities and their 63 baseline tests.
- **Stage 3 — Dual-Worktree Verification**: Create authentic merge commit, materialize baseline worktree at pre-merge SHA, execute multiset static analysis via `scripts/run_baseline_comparison.sh` (orchestrating `scripts/compare_diagnostics.py`) across Python files in both worktrees, and run the full 12-domain acceptance test matrix. Manifest metrics (baseline paths, postmerge paths, renames, unique identities) are generated and asserted at merge time per D12, not assumed from the merge-base union estimate.
- **Fork invariants preserved**: `OPENAI_BACKEND_TRANSPORTS` set, `FallbackModelSettings`/`AttemptPlan` chain, Nous `_ensure_nous_key()`/`_refresh_nous_key_for_retry()`, `StructuredOutputMode` with `UNSET` sentinel, `@lru_cache` schema injection, D8 prose bypass, Langfuse metadata forwarding (`provider`, `namespace`, `is_fallback`, `structured_output_mode`), LMStudio transport registration.
- **Deterministic rollback**: If any acceptance gate fails, `git merge --abort` (pre-commit) or `git reset --hard PREMERGE_MAIN_SHA` (post-commit) restores the exact pre-merge state.

## Capabilities

### New Capabilities
- `upstream-merge-verification`: Dual-worktree baseline-delta static analysis policy using `scripts/compare_diagnostics.py` with rename mapping, multiset (`collections.Counter`) diagnostic comparison for Ruff and BasedPyright, and a 12-domain acceptance test matrix.

### Modified Capabilities
- `ai-router-transport`: Reconcile fork transport registration (`ai-router`, `nous`, `lmstudio`) with upstream's lazy SDK loading and refactored backend registry. Preserve `OPENAI_BACKEND_TRANSPORTS`, Nous auth lifecycle, and LMStudio env config.
- `llm-model-fallback`: Reconcile `AttemptPlan` and `FallbackModelSettings` with upstream's refactored `src/llm/runtime.py` lifecycle, `src/llm/api.py` provider selection loop, and modular `tool_loop.py`.
- `observability-langfuse`: Reconcile fork's Langfuse generation metadata forwarding (`provider`, `namespace`, `is_fallback`, `structured_output_mode`) with upstream's telemetry/exporter architecture and `compact|rich` logging format.

## Impact

- **Code**: 369 files changed (54,465 insertions, 11,730 deletions) across the entire repository; 14 files require manual conflict resolution; 80 fork-only files must survive intact.
- **APIs**: Upstream Scopes-based CRUD replaces legacy patterns; existing fork endpoints unaffected.
- **Dependencies**: Upstream may add or bump Python/TS dependencies; `uv sync` and `bun install` required post-merge.
- **Database**: New Alembic migrations from upstream; 25-test Alembic suite must pass.
- **Services**: `honcho-api`, `honcho-deriver`, `honcho-worker` containers must be rebuilt with merged code.
- **CI/CD**: MCP typecheck (`bun run tsc --noEmit`), Python SDK, TypeScript SDK, and Honcho CLI test suites must all pass.
- **Rollback**: Pre-commit abort via `git merge --abort`; post-commit rollback via `git reset --hard c00a2a876d28f17af632059876a33a23df349d15`.
