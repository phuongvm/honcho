## 1. Prerequisites (on main, before merge branch)

- [ ] 1.1 Stage and commit ALL prerequisite tooling and change package files on `main` in a single atomic commit: `git add scripts/compare_diagnostics.py scripts/run_baseline_comparison.sh tests/scripts/test_compare_diagnostics.py openspec/workspace/explorations/2026-08-20-upstream-sync-full-merge-analysis.md openspec/changes/sync-upstream-main-full-merge/ && git commit -m "chore: stage sync-upstream-main-full-merge change package, comparator, wrapper, and tests"`
- [ ] 1.2 Verify all prerequisite tooling blobs exist at HEAD: `git cat-file -e HEAD:scripts/compare_diagnostics.py && git cat-file -e HEAD:scripts/run_baseline_comparison.sh && git cat-file -e HEAD:tests/scripts/test_compare_diagnostics.py` — all three must exit 0
- [ ] 1.3 Verify change package blobs exist at HEAD: `git cat-file -e HEAD:openspec/changes/sync-upstream-main-full-merge/proposal.md && git cat-file -e HEAD:openspec/changes/sync-upstream-main-full-merge/design.md && git cat-file -e HEAD:openspec/changes/sync-upstream-main-full-merge/tasks.md` — all three must exit 0
- [ ] 1.4 Record new PREMERGE_MAIN_SHA: `PREMERGE_MAIN_SHA=$(git rev-parse HEAD)` — this is the true pre-merge baseline including all prerequisite artifacts

## 2. Branch Setup & Merge Initiation

- [ ] 2.1 Verify upstream remote is configured: `git remote -v` must show `upstream` pointing to `plastic-labs/honcho`
- [ ] 2.2 Fetch latest upstream: `git fetch upstream`
- [ ] 2.3 Assert upstream/main resolves to pinned UPSTREAM_SHA: `[ "$(git rev-parse upstream/main)" = "7bafee5de1b77a619f56c32ba59d9dcc0e115449" ] || { echo "FATAL: upstream/main has moved past pinned SHA"; exit 1; }` — fail closed if ref has advanced
- [ ] 2.4 Create merge branch: `git checkout -b merge/upstream-sync`
- [ ] 2.5 Initiate merge using pinned object ID (not moving ref): `git merge 7bafee5de1b77a619f56c32ba59d9dcc0e115449` — confirm exactly 14 conflict files. Do NOT use `git merge upstream/main`.

## 3. Stage 1 — Foundations & SDK Resolution

- [ ] 3.1 Resolve `mcp/src/config.ts`: merge upstream workspace scope header extraction while preserving fork host/port configuration
- [ ] 3.2 Resolve `mcp/bun.lock`: regenerate lockfile via `cd mcp && bun install` after config.ts resolution
- [ ] 3.3 Verify MCP typecheck: `cd mcp && bun run tsc --noEmit` — must exit 0
- [ ] 3.4 Accept non-conflicted upstream additions: Scopes CRUD modules, Redis Cluster config, SDK updates, CLI changes, docs, CI configs
- [ ] 3.5 Run `uv sync` to install any new Python dependencies from upstream
- [ ] 3.6 Verify no unresolved conflicts remain in Stage 1 files: `git diff --diff-filter=U -- mcp/` must be empty

## 4. Stage 2 — Core Engine Reconciliation (src/config.py)

- [ ] 4.1 Resolve `src/config.py`: integrate upstream Scopes, Redis Cluster (`CACHE.CLUSTER`), and new telemetry settings while preserving `OPENAI_BACKEND_TRANSPORTS`, `FallbackModelSettings`, `ResolvedFallbackConfig`, `StructuredOutputMode`, `UNSET` sentinel, and all fork `LLMSettings` fields
- [ ] 4.2 Verify config reconciliation: `.venv/bin/pytest -q tests/llm/test_model_config.py` — all tests pass

## 5. Stage 2 — LLM Engine Reconciliation

- [ ] 5.1 Resolve `src/llm/registry.py`: adopt upstream lazy SDK loading while maintaining fork custom transport dispatch (`ai-router`, `nous`, `lmstudio`) and `NousAuthProvider` registration
- [ ] 5.2 Verify registry: `.venv/bin/pytest -q tests/llm/test_nous_registry.py` — pass
- [ ] 5.3 Resolve `src/llm/backends/openai.py`: integrate upstream async completion methods while preserving `_ensure_nous_key()`, `_refresh_nous_key_for_retry()`, `@lru_cache` schema injection, and D8 clean prose bypass
- [ ] 5.4 Verify backend: `.venv/bin/pytest -q tests/llm/test_backends/test_openai.py tests/llm/test_backends/test_nous_autorefresh.py` — pass
- [ ] 5.5 Resolve `src/llm/runtime.py`: reconcile upstream runtime lifecycle with fork's `AttemptPlan`, `select_model_config_for_attempt()`, and `update_current_langfuse_observation()`
- [ ] 5.6 Verify runtime: `.venv/bin/pytest -q tests/llm/test_model_config.py` — pass
- [ ] 5.7 Resolve `src/llm/api.py`: adapt provider selection loop and fallback retry mechanism to wrap upstream's `capture.py` and `tool_loop.py` refactors
- [ ] 5.8 Verify api: `.venv/bin/pytest -q tests/utils/test_clients.py` — pass
- [ ] 5.9 Resolve `src/llm/structured_output.py`: combine upstream Pydantic validation repairs with fork's safe `model_construct()` fallback
- [ ] 5.10 Resolve `src/llm/tool_loop.py`: adopt upstream modular tool loop; ensure `selected_config` and `extra_params` flow through tool executions

## 6. Stage 2 — Telemetry & Utility Reconciliation

- [ ] 6.1 Resolve `src/telemetry/logging.py`: adopt upstream `compact|rich` performance logging format while preserving fork's fallback WARNING hooks
- [ ] 6.2 Resolve `src/utils/summarizer.py`: merge upstream summary prompt refactor; maintain direct `track_name` passing to `honcho_llm_call`
- [ ] 6.3 Verify telemetry and utility: `.venv/bin/pytest -q tests/utils/test_clients.py` — pass

## 7. Stage 2 — Test Suite Reconciliation

- [ ] 7.1 Resolve `tests/llm/test_backends/test_openai.py`: combine upstream backend test fixtures with fork `json_object` and Nous retry assertions
- [ ] 7.2 Resolve `tests/llm/test_model_config.py`: retain fork fallback inheritance/override/env-empty tests alongside upstream matrix tests
- [ ] 7.3 Resolve `tests/utils/test_clients.py`: update assertions to test both upstream client factory behaviors and fork custom transport registries
- [ ] 7.4 Run full fork preservation suite (63 tests): `.venv/bin/pytest -q -n 0 tests/llm/test_model_config.py tests/llm/test_backends/test_openai.py tests/llm/test_backends/test_nous_autorefresh.py tests/llm/test_fallback_integration.py tests/llm/test_9router_translator_baseline.py` — all 63 pass
- [ ] 7.5 Confirm zero unmerged paths: `git diff --diff-filter=U` — must be empty

## 8. Stage 3 — Authentic Merge Commit

- [ ] 8.1 Create authentic merge commit: `git commit -m "merge(upstream): reconcile 130 commits from upstream/main"` with body listing 6 preserved capabilities and test counts — this is the single two-parent merge commit (prerequisite scripts are already on main)
- [ ] 8.2 Verify 80 fork-only files survived: check `git diff --name-status ${PREMERGE_MAIN_SHA}...HEAD` — none of the 80 paths should appear with `D` status

## 9. Stage 3 — Dual-Worktree Baseline-Delta Verification (Fail-Closed)

- [ ] 9.1 Execute the fail-closed orchestration wrapper: `bash scripts/run_baseline_comparison.sh ${PREMERGE_MAIN_SHA}` — must exit 0 (Ruff and BasedPyright comparators both report 0 new diagnostics)

## 10. Stage 3 — Full Acceptance Test Matrix (12 domains per D10)

- [ ] 10.1 **D10-Domain 1 — Full offline pytest**: `.venv/bin/pytest tests/ -q -m "not live_llm and not requires_db and not integration"` — exit 0
- [ ] 10.2 **D10-Domain 2 — Fork preservation suite** (63 tests): `.venv/bin/pytest -q -n 0 tests/llm/test_model_config.py tests/llm/test_backends/test_openai.py tests/llm/test_backends/test_nous_autorefresh.py tests/llm/test_fallback_integration.py tests/llm/test_9router_translator_baseline.py` — all 63 pass
- [ ] 10.3 **D10-Domain 3 — Alembic suite**: `.venv/bin/pytest tests/alembic/ -q -o addopts=""` — 25 tests pass
- [ ] 10.4 **D10-Domain 4 — Comparator unit tests**: `PYTHONPATH=. .venv/bin/python -m unittest tests/scripts/test_compare_diagnostics.py` — 5 tests pass
- [ ] 10.5 **D10-Domain 5 — Python SDK**: `.venv/bin/pytest tests/sdk/ -q` — exit 0
- [ ] 10.6 **D10-Domain 6 — TypeScript SDK**: `.venv/bin/pytest tests/ -k typescript` — exit 0
- [ ] 10.7 **D10-Domain 7 — Honcho CLI**: `.venv/bin/pytest honcho-cli/tests/ -q` — exit 0
- [ ] 10.8 **D10-Domain 8 — MCP typecheck**: `cd mcp && bun run tsc --noEmit` — exit 0
- [ ] 10.9 **D10-Domain 9 — OpenSpec self-change validation**: `openspec validate sync-upstream-main-full-merge` — exit 0, output "valid"
- [ ] 10.10 **D10-Domain 10 — OpenSpec self-change status**: `openspec status --change sync-upstream-main-full-merge --json` — `isComplete: true`, all artifacts "done"
- [ ] 10.11 **D10-Domain 11 — Ruff + BasedPyright delta**: Already verified by task 9.1 (`scripts/run_baseline_comparison.sh`) — record the zero-new-errors output as evidence
- [ ] 10.12 **D10-Domain 12 — OpenSpec coexisting change validation**: `openspec validate sync-upstream-structured-output-mode` — exit 0, output "valid"

## 11. Rollback Verification (isolated, non-shared-worktree)

- [ ] 11.1 **Pre-commit rollback verification**: On a throwaway test branch, initiate `git merge ${UPSTREAM_SHA}`, then execute `git merge --abort`. Assert: `git rev-parse HEAD` equals `PREMERGE_MAIN_SHA`, `git status --porcelain` is empty, `git diff HEAD` is empty — all three must pass to confirm byte-exact restoration.
- [ ] 11.2 **Post-commit rollback verification**: After creating a test merge commit on a throwaway branch, execute `git reset --hard ${PREMERGE_MAIN_SHA}`. Assert: `git rev-parse HEAD` equals `PREMERGE_MAIN_SHA`, `git diff-index --quiet HEAD --` exits 0 (clean index), `git status --porcelain` is empty — all three must pass.

## 12. Commander Approval Gate

**⛔ MANDATORY STOP — Coder SHALL halt here and present the full verification report to the Commander (Human Principal) for explicit authorization.**

- [ ] 12.1 Present comprehensive verification report: all 12 domain results, rollback verification evidence, manifest metrics, and `scripts/run_baseline_comparison.sh` output
- [ ] 12.2 Await explicit Commander "APPROVE" before proceeding to any tagging, merging, or remote push operations

## 13. Final Merge & Verification Tag (requires Commander approval from 12.2)

- [ ] 13.1 Tag verified state: `git tag merge/verified-upstream-sync`
- [ ] 13.2 **⛔ COMMANDER GATE**: Await explicit Commander authorization for main merge and push
- [ ] 13.3 Fast-forward merge into main: `git checkout main && git merge --ff-only merge/upstream-sync`
- [ ] 13.4 Push merged main: `git push origin main`
- [ ] 13.5 Push tag: `git push origin merge/verified-upstream-sync`
