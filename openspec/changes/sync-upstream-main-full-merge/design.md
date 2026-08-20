## Context

The Honcho production fork (`origin/main`) diverged from `plastic-labs/honcho` (`upstream/main`) by 130 commits behind / 15 commits ahead. The fork adds 6 proprietary capabilities across 80 files: AI-Router/9Router transport, Nous auth auto-refresh, structured output mode (`json_object`), multi-tier model fallback (`AttemptPlan`), Langfuse observability metadata forwarding, and LMStudio transport. Upstream has evolved significantly: Scopes-based CRUD, Redis Cluster caching, agent-tool architecture refactors (Deriver/Dialectic/Dreamer with dedicated tool modules), Alembic migrations, SDK/CLI updates, and MCP extensions. A dry-run merge identifies exactly 14 conflict files. The 63-test fork preservation suite and the `scripts/compare_diagnostics.py` comparator (5 unit tests) serve as the regression baseline.

**Pinned SHAs**:
- `PREMERGE_MAIN_SHA`: `c00a2a876d28f17af632059876a33a23df349d15`
- `UPSTREAM_SHA`: `7bafee5de1b77a619f56c32ba59d9dcc0e115449`
- `MERGE_BASE_SHA`: `f37338b855d9fe1ab06e7e4b8e676e6fd01baa47`

## Goals / Non-Goals

**Goals:**
- G1: Merge all 130 upstream commits into `origin/main` via a single authentic `git merge` on a dedicated branch (`merge/upstream-sync`).
- G2: Resolve all 14 conflict files with zero regression to the 63-test fork preservation suite.
- G3: Preserve all 80 fork-only files intact (zero collateral loss).
- G4: Achieve zero new Ruff/BasedPyright errors compared to the pre-merge baseline (dual-worktree delta gate).
- G5: Pass the full 12-domain acceptance test matrix before fast-forward merging into `origin/main`.

**Non-Goals:**
- NG1: Backporting fork features upstream (this is a receive-only sync).
- NG2: Refactoring fork code to match upstream patterns beyond what conflict resolution requires.
- NG3: Running live/integration tests (`live_llm`, `requires_db`, `integration` markers) — those are excluded from the offline acceptance gate.
- NG4: Modifying the `sync-upstream-structured-output-mode` active change — it remains independent.

## Decisions

### D1: Single Merge Branch with Staged Resolution (not Phased Waves)
**Decision**: Use a single `merge/upstream-sync` branch with `git merge ${UPSTREAM_SHA}` (pinned object ID per D13), resolving conflicts in 3 sequential stages on that branch — not 3 separate wave PRs.
**Rationale**: A single merge commit preserves upstream's full commit graph for `git log --follow` and `git bisect`. Multi-wave cherry-pick loses provenance and creates artificial merge-base drift between waves. The 3 stages are resolution phases within a single merge, not independent changes.
**Alternatives rejected**: (A) 3-wave phased PRs — rejected by reviewer for circular dependencies and merge-base drift; (B) rebase — rewrites fork history, breaks deployed SHA references.

### D2: Stage Ordering — Foundations Before Engine
**Decision**: Stage 1 resolves non-LLM files (MCP, lockfiles, SDKs) first; Stage 2 tackles the LLM engine and test conflicts; Stage 3 does the verification sweep.
**Rationale**: MCP conflicts (`config.ts`, `bun.lock`) are isolated from the LLM subsystem. Resolving them first removes noise and allows `bun run tsc --noEmit` to validate early. The LLM engine files have cross-dependencies (config ↔ registry ↔ backend ↔ runtime ↔ api ↔ tests) that must be resolved together in Stage 2.

### D3: Conflict Resolution Strategy per File
**Decision**: Each of the 14 conflict files has a pre-determined resolution strategy documented in the exploration (Section 4). The strategy for each file follows "integrate upstream change while preserving fork invariant" — never "accept ours" or "accept theirs" wholesale.
**Rationale**: Wholesale accept-ours loses upstream improvements; wholesale accept-theirs loses fork capabilities. Manual reconciliation with post-resolution per-file test verification is the only safe approach.

### D4: Dual-Worktree Baseline-Delta Static Analysis
**Decision**: Use `git worktree add -d` to materialize a temporary worktree at `PREMERGE_MAIN_SHA`, capture Ruff/BasedPyright diagnostics on both trees, and compare with the checked-in `scripts/compare_diagnostics.py` using multiset subtraction with rename mapping.
**Rationale**: A simple "run linter, expect 0" is too strict — the baseline may already have warnings. Delta comparison ensures the merge introduces zero *new* diagnostics while tolerating pre-existing ones. Rename mapping (`git diff --name-status -M`) handles upstream file renames without false positives.
**Alternatives rejected**: (A) Absolute zero-warning gate — would require fixing pre-existing upstream warnings unrelated to this merge; (B) Diff-only linting — misses new errors in files not touched by the merge.

### D5: Fork-Only File Preservation via Manifest Verification
**Decision**: The 80-file fork-only manifest (Section 2 of the exploration) is verified by checking `git diff --name-status PREMERGE_MAIN_SHA...HEAD` — none of the 80 fork-only paths should appear with `D` (deleted) status.
**Rationale**: These files have no upstream counterpart, so there is no conflict. The risk is accidental deletion during conflict resolution. A manifest check is cheap and deterministic.

### D6: Merge Commit Message Convention
**Decision**: Use `merge(upstream): reconcile 130 commits from upstream/main` as the merge commit message, with a body listing the 6 preserved fork capabilities and the test results.
**Rationale**: Consistent with the project's commit message conventions. The body provides a quick audit trail for future developers.

### D7: Rollback at Every Stage
**Decision**: Stage 1 and Stage 2 are uncommitted resolution work — `git merge --abort` restores the pre-merge state. After the merge commit (Stage 3), `git reset --hard PREMERGE_MAIN_SHA` is the rollback. Both are deterministic and tested.
**Rationale**: A merge that cannot be rolled back is not production-grade. The pinned `PREMERGE_MAIN_SHA` ensures byte-exact restoration.

### D8: Comparator Script as Prerequisite Commit (on main, Before Merge Branch)
**Decision**: `scripts/compare_diagnostics.py`, its unit tests (`tests/scripts/test_compare_diagnostics.py`), and the orchestration wrapper `scripts/run_baseline_comparison.sh` SHALL be committed on `main` BEFORE the merge branch is created (tasks 1.1–1.4). Task 1.4 records the resulting HEAD as `PREMERGE_MAIN_SHA` — the true pre-merge baseline in which all comparator artifacts exist at a committed SHA. The merge branch is then created from this baseline, ensuring the prerequisite commit is NOT part of the merge commit itself and cannot conflict with `MERGE_HEAD` semantics.
**Rationale**: The reviewer proved that committing prerequisite artifacts while `MERGE_HEAD` is active (i.e., after `git merge` but before the merge commit) creates the two-parent merge commit itself, leaving no room for a separate authentic merge commit. Moving the prerequisite commit before merge branch creation eliminates this lifecycle conflict entirely.

### D9: OpenSpec Active Change Coexistence
**Decision**: The existing active change `sync-upstream-structured-output-mode` (18/22 tasks complete) SHALL NOT be modified by this merge. Its delta specs and reviews remain independent.
**Rationale**: The structured output mode change is a fork-only behavioral change. The upstream merge is an integration change. They touch overlapping files but have different governance lifecycles. Merging their OpenSpec artifacts would violate the single-responsibility principle for changes.

### D10: Acceptance Test Matrix Scope
**Decision**: The acceptance matrix covers 12 test domains (Section 7 of exploration): full offline pytest, 63-test preservation suite, Alembic, comparator unit tests, Python SDK, TypeScript SDK, Honcho CLI, MCP typecheck, OpenSpec self-change validation, OpenSpec self-change status, OpenSpec coexisting change validation, and Ruff+BasedPyright delta (via `scripts/run_baseline_comparison.sh`). Tests marked `live_llm`, `requires_db`, or `integration` are excluded.
**Rationale**: Offline tests run deterministically in CI without external dependencies. Live tests require running services and credentials, making them unsuitable for a merge gate that must be reproducible. Self-change validation ensures the merge does not corrupt its own OpenSpec artifacts.

**12-Domain → Task Traceability Map:**
| # | Domain | Task | Command | Pass Criterion |
|:-:|:-------|:-----|:--------|:---------------|
| 1 | Full offline pytest | 10.1 | `.venv/bin/pytest tests/ -q -m "not live_llm and not requires_db and not integration"` | exit 0 |
| 2 | Fork preservation (63) | 10.2 | `.venv/bin/pytest -q -n 0 tests/llm/test_model_config.py tests/llm/test_backends/test_openai.py tests/llm/test_backends/test_nous_autorefresh.py tests/llm/test_fallback_integration.py tests/llm/test_9router_translator_baseline.py` | 63 pass |
| 3 | Alembic | 10.3 | `.venv/bin/pytest tests/alembic/ -q -o addopts=""` | 25 pass |
| 4 | Comparator unit tests | 10.4 | `PYTHONPATH=. .venv/bin/python -m unittest tests/scripts/test_compare_diagnostics.py` | 5 pass |
| 5 | Python SDK | 10.5 | `.venv/bin/pytest tests/sdk/ -q` | exit 0 |
| 6 | TypeScript SDK | 10.6 | `.venv/bin/pytest tests/ -k typescript` | exit 0 |
| 7 | Honcho CLI | 10.7 | `.venv/bin/pytest honcho-cli/tests/ -q` | exit 0 |
| 8 | MCP typecheck | 10.8 | `cd mcp && bun run tsc --noEmit` | exit 0 |
| 9 | OpenSpec self-change validation | 10.9 | `openspec validate sync-upstream-main-full-merge` | exit 0, "valid" |
| 10 | OpenSpec self-change status | 10.10 | `openspec status --change sync-upstream-main-full-merge --json` | `isComplete: true` |
| 11 | Ruff + BasedPyright delta | 9.1 | `bash scripts/run_baseline_comparison.sh ${PREMERGE_MAIN_SHA}` | exit 0, 0 new errors |
| 12 | OpenSpec coexisting change | 10.12 | `openspec validate sync-upstream-structured-output-mode` | exit 0, "valid" |

### D11: Fail-Closed Orchestration Wrapper
**Decision**: The dual-worktree baseline-delta verification SHALL be orchestrated by a checked-in shell script `scripts/run_baseline_comparison.sh` with `set -Eeuo pipefail`, a cleanup trap that preserves exit code, strict analyzer exit validation (>1 aborts), and comparator exit propagation (nonzero aborts).
**Rationale**: The reviewer demonstrated that without an executable wrapper, analyzer crashes (exit >1) and comparator schema errors (exit 2) can silently pass with protocol final status 0. A fail-closed shell script with trap-based cleanup is the simplest reliable mechanism — it requires no new dependencies and is testable via synthetic exit-code injection.
**Alternatives rejected**: (A) Inline tasks.md prose steps — reviewer proved these are fail-open; (B) Python orchestrator — over-engineered for a sequential capture-compare-cleanup pipeline.

### D12: Mixed-Scope Analysis with Dynamic Rename Tracking
**Decision**: The wrapper `scripts/run_baseline_comparison.sh` uses two different analyzer scopes: **Ruff runs manifest-scoped** (only files listed in `baseline_manifest.txt` / `postmerge_manifest.txt`) and **BasedPyright runs project-scoped** (the full project via `basedpyright --outputjson` from the worktree root, covering `src`, `tests`, and SDK directories). The manifests are dynamically generated from `git diff --name-status -M PREMERGE_MAIN_SHA...HEAD` and serve as (a) Ruff's file scope, (b) rename tracking input to the comparator (`--rename-map-json`), and (c) self-documenting evidence of the changed-file scope (summary line: `baseline=N files, postmerge=M files, renames=R`). The comparator uses `--baseline-dir` and `--postmerge-dir` to relativize absolute diagnostic paths and performs multiset subtraction to isolate new diagnostics. No static file count is hardcoded. Ruff is invoked via bash array expansion (`mapfile -t` + `"${files[@]}"`) rather than `xargs` so that Ruff's native exit 1 (findings present) is preserved — `xargs` remaps exit 1 to 123, which the fail-closed validator would treat as a crash.
**Rationale**: Ruff is manifest-scoped because it accepts explicit file arguments and scoping to changed files keeps the JSON report focused. BasedPyright is project-scoped because it resolves imports and type stubs from `pyrightconfig.json` and its project-level analysis catches transitive import breakage in files not directly in the diff. The comparator's multiset subtraction then filters both reports to surface only *new* diagnostics introduced by the merge.

### D13: Pinned Object Merge (not Moving Ref)
**Decision**: The merge command SHALL use `git merge ${UPSTREAM_SHA}` (the pinned object ID) instead of `git merge upstream/main`. Task 2.3 asserts `upstream/main == UPSTREAM_SHA` before merge; if the ref has advanced, the merge aborts.
**Rationale**: `upstream/main` is a moving ref that may advance between fetch and merge. Merging the pinned SHA ensures reproducibility and matches the exploration's ground truth.

## Risks / Trade-offs

- **[R1: Upstream dependency changes break venv]** → Mitigation: Run `uv sync` after merge; if new deps conflict with fork deps, resolve in Stage 1 before touching LLM code.
- **[R2: Alembic regression]** → Mitigation: The 25-test Alembic suite is in the acceptance matrix (domain 3). Pinned `git diff --name-only main...upstream/main -- '*migration*' '*migrations*' '*alembic*'` returns count 0 — upstream adds no new migrations in this range. The regression suite is retained as a safety net, not because upstream introduces migration conflicts.
- **[R3: Test count drift]** → Mitigation: If upstream adds tests that conflict with fork test modules (files 12-14 in the conflict list), reconcile by combining test fixtures and assertions, then verify total count >= 63 for the preservation suite.
- **[R4: Merge conflict complexity in `src/config.py`]** → Mitigation: `src/config.py` is the highest-risk file (upstream adds Scopes + Redis Cluster config, fork adds `OPENAI_BACKEND_TRANSPORTS` + `FallbackModelSettings` + `StructuredOutputMode`). Resolution order: accept upstream's new sections first, then re-apply fork additions, then run `test_model_config.py` immediately.
- **[R5: MCP TypeScript conflicts cascade]** → Mitigation: Resolve `config.ts` first, then regenerate `bun.lock` via `bun install`, then typecheck. If `package.json` upstream version differs, accept upstream's version.

## Migration Plan

1. **Prerequisite commit on main**: Stage and commit `scripts/compare_diagnostics.py`, `scripts/run_baseline_comparison.sh`, `tests/scripts/test_compare_diagnostics.py`, `openspec/workspace/explorations/2026-08-20-upstream-sync-full-merge-analysis.md`, and `openspec/changes/sync-upstream-main-full-merge/` on `main` in a single atomic commit. Verify all prerequisite blobs exist at HEAD via `git cat-file -e`. Record `PREMERGE_MAIN_SHA=$(git rev-parse HEAD)`.
2. **Branch creation**: `git checkout -b merge/upstream-sync` from `main` (post-prerequisite).
3. **Merge initiation**: Assert `upstream/main == UPSTREAM_SHA`, then `git merge ${UPSTREAM_SHA}` (pinned object ID, not moving ref) — produces 14 conflicts.
4. **Stage 1 resolution**: Resolve `mcp/src/config.ts`, `mcp/bun.lock`; accept non-conflicted upstream changes. Verify: `cd mcp && bun run tsc --noEmit`.
5. **Stage 2 resolution**: Reconcile the 12 core conflict files in dependency order (`config.py` → `registry.py` → `backends/openai.py` → `runtime.py` → `api.py` → `tool_loop.py` → `structured_output.py` → `telemetry/logging.py` → `utils/summarizer.py` → test files). Verify after each: per-file test command from exploration Section 4.
6. **Stage 3 verification**: Create merge commit, materialize baseline worktree at `PREMERGE_MAIN_SHA`, run dual-worktree comparator, run full 12-domain acceptance matrix.
7. **Tag**: `git tag merge/verified-upstream-sync`.
8. **Fast-forward merge**: `git checkout main && git merge --ff-only merge/upstream-sync`.
9. **Rollback**: Pre-commit: `git merge --abort`. Post-commit: `git reset --hard ${PREMERGE_MAIN_SHA}`.

## Open Questions

- None. All architectural decisions were resolved during the exploration review cycle (t_35bd3eb4, v1-v10).
