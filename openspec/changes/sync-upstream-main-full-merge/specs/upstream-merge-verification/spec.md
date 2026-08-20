## ADDED Requirements

### Requirement: Fail-closed baseline-comparison orchestration
The dual-worktree baseline-delta verification SHALL be orchestrated by a checked-in shell script (`scripts/run_baseline_comparison.sh`) that enforces fail-closed semantics: any analyzer crash, invalid report, or comparator failure SHALL abort the entire pipeline and propagate the original error exit code.

#### Scenario: Script uses strict shell options
- **WHEN** `scripts/run_baseline_comparison.sh` is invoked
- **THEN** the script SHALL execute with `set -Eeuo pipefail` to abort on any uncaught error, undefined variable, or pipeline failure

#### Scenario: Analyzer exit >1 aborts pipeline
- **WHEN** Ruff or BasedPyright exits with code >1 (crash/internal error, as opposed to exit 1 which indicates lint findings)
- **THEN** the script SHALL abort immediately and exit with the analyzer's original exit code

#### Scenario: Analyzer exit 127 aborts pipeline
- **WHEN** Ruff or BasedPyright binary is not found (exit 127)
- **THEN** the script SHALL abort immediately and exit 127

#### Scenario: Comparator exit nonzero aborts pipeline
- **WHEN** `scripts/compare_diagnostics.py` exits with code 1 (new errors found) or code 2 (invalid report/schema error)
- **THEN** the script SHALL abort immediately and propagate the comparator's exit code

#### Scenario: Cleanup trap preserves exit code
- **WHEN** the script exits (success or failure) and a baseline worktree exists
- **THEN** the cleanup trap SHALL remove the baseline worktree via `git worktree remove --force` while preserving the original exit code

#### Scenario: JSON report validation before comparison
- **WHEN** analyzer capture completes with exit code 0 or 1
- **THEN** the script SHALL validate that each JSON report file exists and is non-empty before passing it to the comparator

#### Scenario: Successful pipeline end-to-end
- **WHEN** both analyzers produce valid reports and both comparators report 0 new errors
- **THEN** the script SHALL exit 0

### Requirement: Dual-worktree baseline-delta static analysis
The system SHALL provide a deterministic static analysis verification mechanism that compares diagnostic output (Ruff lint errors, BasedPyright type errors) between a pre-merge baseline worktree and the post-merge tree, using multiset comparison (`collections.Counter`) with rename mapping.

#### Scenario: Baseline worktree materialization
- **WHEN** the merge commit is created on `merge/upstream-sync`
- **THEN** a temporary baseline worktree SHALL be materialized at the pre-merge SHA (`PREMERGE_MAIN_SHA`) using `git worktree add -d`

#### Scenario: Manifest generation with rename tracking
- **WHEN** `git diff --name-status -M PREMERGE_MAIN_SHA...HEAD` is executed
- **THEN** separate baseline and post-merge Python file manifests SHALL be generated, with renamed files (`R` status) tracked in a `rename_map.json` for path normalization

#### Scenario: Zero new errors gate for Ruff
- **WHEN** `scripts/compare_diagnostics.py --mode=ruff` is executed with baseline and post-merge JSON outputs
- **THEN** the comparator SHALL report 0 new Ruff errors (new errors = post-merge multiset minus baseline multiset, with paths normalized via rename map)

#### Scenario: Zero new errors gate for BasedPyright
- **WHEN** `scripts/compare_diagnostics.py --mode=pyright` is executed with baseline and post-merge JSON outputs
- **THEN** the comparator SHALL report 0 new BasedPyright errors (new errors = post-merge multiset minus baseline multiset, with paths normalized via rename map)

### Requirement: 12-domain acceptance test matrix
The merge SHALL pass a comprehensive acceptance test matrix covering 12 domains before the merge branch is fast-forward merged into `origin/main`.

#### Scenario: Full offline pytest suite passes
- **WHEN** `.venv/bin/pytest tests/ -q -m "not live_llm and not requires_db and not integration"` is executed on the post-merge tree
- **THEN** all tests SHALL pass with exit code 0

#### Scenario: 63-test fork preservation suite passes
- **WHEN** the 5 fork-specific test modules (`test_model_config.py`, `test_openai.py`, `test_nous_autorefresh.py`, `test_fallback_integration.py`, `test_9router_translator_baseline.py`) are executed
- **THEN** all 63 tests SHALL pass with exit code 0

#### Scenario: Alembic migration suite passes
- **WHEN** `.venv/bin/pytest tests/alembic/ -q -o addopts=""` is executed
- **THEN** all 25 Alembic migration tests SHALL pass with exit code 0

#### Scenario: Comparator unit test suite passes
- **WHEN** `PYTHONPATH=. .venv/bin/python -m unittest tests/scripts/test_compare_diagnostics.py` is executed
- **THEN** all 5 tests SHALL pass with exit code 0

#### Scenario: Python SDK suite passes
- **WHEN** `.venv/bin/pytest tests/sdk/ -q` is executed
- **THEN** all tests SHALL pass with exit code 0

#### Scenario: TypeScript SDK suite passes
- **WHEN** `.venv/bin/pytest tests/ -k typescript` is executed from the monorepo root
- **THEN** all tests SHALL pass with exit code 0

#### Scenario: Honcho CLI suite passes
- **WHEN** `.venv/bin/pytest honcho-cli/tests/ -q` is executed
- **THEN** all tests SHALL pass with exit code 0

#### Scenario: MCP server typecheck passes
- **WHEN** `cd mcp && bun run tsc --noEmit` is executed
- **THEN** TypeScript compilation SHALL produce 0 errors with exit code 0

#### Scenario: OpenSpec self-change validation passes
- **WHEN** `openspec validate sync-upstream-main-full-merge` is executed on the post-merge tree
- **THEN** the command SHALL exit 0 with output "valid"

#### Scenario: OpenSpec self-change status completeness passes
- **WHEN** `openspec status --change sync-upstream-main-full-merge --json` is executed on the post-merge tree
- **THEN** `isComplete` SHALL be `true` and all artifact statuses SHALL be `"done"`

#### Scenario: OpenSpec coexisting change validation passes
- **WHEN** `openspec validate sync-upstream-structured-output-mode` is executed on the post-merge tree
- **THEN** the command SHALL exit 0 with output "valid"

### Requirement: Deterministic rollback capability
The merge process SHALL provide deterministic rollback at every stage, ensuring the fork can be restored to its exact pre-merge state. Each rollback mechanism SHALL be independently verified with evidence (HEAD equality, clean index, clean worktree).

#### Scenario: Pre-commit rollback
- **WHEN** conflict resolution fails or acceptance tests fail before the merge commit
- **THEN** `git merge --abort` SHALL restore the working tree to the exact `PREMERGE_MAIN_SHA` state

#### Scenario: Pre-commit rollback verification
- **WHEN** `git merge --abort` is executed on a test branch
- **THEN** all three assertions SHALL pass: `git rev-parse HEAD == PREMERGE_MAIN_SHA`, `git status --porcelain` is empty, `git diff HEAD` is empty

#### Scenario: Post-commit rollback
- **WHEN** any acceptance gate fails after the merge commit is created
- **THEN** `git reset --hard PREMERGE_MAIN_SHA` SHALL restore the branch to the exact pre-merge state

#### Scenario: Post-commit rollback verification
- **WHEN** `git reset --hard PREMERGE_MAIN_SHA` is executed after a test merge commit
- **THEN** all three assertions SHALL pass: `git rev-parse HEAD == PREMERGE_MAIN_SHA`, `git diff-index --quiet HEAD --` exits 0, `git status --porcelain` is empty

### Requirement: Pinned object merge semantics
The merge command SHALL use the pinned `UPSTREAM_SHA` object ID, not the `upstream/main` moving ref. The system SHALL assert ref equality before proceeding.

#### Scenario: Upstream ref matches pinned SHA
- **WHEN** `git rev-parse upstream/main` is executed after fetch
- **THEN** the result SHALL equal the pinned `UPSTREAM_SHA`; if not, the merge SHALL abort immediately

#### Scenario: Merge uses pinned SHA
- **WHEN** the merge is initiated
- **THEN** the command SHALL be `git merge ${UPSTREAM_SHA}`, not `git merge upstream/main`

### Requirement: Commander approval gate before remote mutations
The merge process SHALL NOT tag, fast-forward merge into `main`, or push to any remote without explicit Commander (Human Principal) authorization. Apply workers MUST stop and await approval after all verification passes.

#### Scenario: Commander gate before tagging
- **WHEN** all 12 acceptance domains pass and the merge commit is verified
- **THEN** the Coder SHALL STOP and present the full verification report to the Commander, awaiting explicit "approve" before executing `git tag`

#### Scenario: Commander gate before main merge and push
- **WHEN** the Commander approves tagging
- **THEN** the Coder SHALL present the tag confirmation and await explicit Commander authorization before executing `git merge --ff-only` into `main` and any `git push` command
