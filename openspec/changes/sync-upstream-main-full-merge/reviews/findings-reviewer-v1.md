# Reviewer Findings v1 — sync-upstream-main-full-merge

## Verdict

**REJECTED / REVISE**

The package is structurally valid and maps all 14 known conflict files, but it is not implementation-ready. Seven CRITICAL contract/executability defects remain: unsafe MODIFIED deltas drop baseline scenarios, fallback environment keys contradict the current configuration architecture, the required comparator artifacts are not present in the pinned clean branch, rollback requirements have no executable tasks, the dual-worktree gate remains fail-open/incompletely scoped, D10 is not traceable end to end, and destructive/remote transitions lack a Commander gate.

## Summary

| Severity | Count | Disposition |
|---|---:|---|
| CRITICAL | 7 | Must be remediated before Apply |
| WARNING | 5 | Correct for truthful traceability |
| INFO | 1 | Passing evidence |

## Scope

Reviewed:

- `proposal.md`
- `design.md`
- `tasks.md`
- `specs/ai-router-transport/spec.md`
- `specs/llm-model-fallback/spec.md`
- `specs/observability-langfuse/spec.md`
- `specs/upstream-merge-verification/spec.md`
- `explorations/2026-08-20-upstream-sync-full-merge-analysis.md`
- Main capability specs for AI-Router, fallback, and Langfuse observability
- Architecture/context: `CLAUDE.md`, `docs/v3/documentation/core-concepts/architecture.mdx`
- Relevant current source/test context: `src/config.py`, `src/llm/runtime.py`, `src/llm/registry.py`, `tests/llm/test_model_config.py`
- Git graph pins, divergence, blast radius, changed-Python union, and merge-tree conflict output
- OpenSpec structure and focused preservation/comparator tests

SDLC layers reviewed: Specs, Architecture/Design, Source Context, Tests, DevOps/Merge Procedure.

## Not Reviewed

- The actual 369-file merged implementation: it does not exist yet.
- Runtime service/container behavior and live LLM integrations: explicitly outside this planning review.
- Every unaffected source file: this is a planning-package review, not a post-merge implementation review.
- External push/production deployment: no state-changing merge or push was executed.

## Findings

### CRITICAL C1 — MODIFIED deltas silently remove baseline scenarios

**Spec reference:** OpenSpec pre-merge safety for MODIFIED requirements; `code-review-mandate` completeness requirement.

**Evidence:**

- Main `openspec/specs/ai-router-transport/spec.md:24-26` requires model-level `base_url` override precedence. The replacement delta `specs/ai-router-transport/spec.md:14-23` omits that scenario and substitutes LMStudio coexistence.
- Main `openspec/specs/llm-model-fallback/spec.md:32-34` requires timeout-triggered first-failure fallback. The replacement delta `specs/llm-model-fallback/spec.md:26-39` omits timeout.
- Main fallback spec `:43-49` has Deriver- and Dialectic-specific WARNING scenarios. Delta `:41-46` replaces both with one generic logging-refactor scenario.
- Main fallback spec `:69-71` requires Nous→OpenAI cross-provider fallback. Delta `:59-68` omits it and substitutes hypothetical future transports.
- None of these scenario changes is marked with scenario-level modification tags.

**Impact:** Archiving the change could weaken shipped behavioral contracts even if implementation preserves them.

**Required resolution:** Restore every baseline scenario in each MODIFIED requirement, or explicitly mark and justify each scenario modification/removal. Add task coverage for every restored scenario.

### CRITICAL C2 — Fallback environment-variable contracts use non-existent configuration paths

**Spec reference:** `specs/llm-model-fallback/spec.md`, requirement “configurable LLM model fallback per agent.”

**Evidence:**

- Delta `specs/llm-model-fallback/spec.md:8,15-20` specifies `DIALECTIC_MODEL_CONFIG__FALLBACK__*` and `DREAM_MODEL_CONFIG__FALLBACK__*`.
- Current architecture uses `DIALECTIC_LEVELS__<level>__MODEL_CONFIG__*` (`src/config.py:909-915`; test/template assertion `tests/llm/test_model_config.py:357-360`).
- Dreamer has two independent settings: `DREAM_DEDUCTION_MODEL_CONFIG__*` and `DREAM_INDUCTION_MODEL_CONFIG__*` (`src/config.py:1126-1166`; test/template assertion `tests/llm/test_model_config.py:362`).

**Impact:** The proposed scenarios cannot be satisfied by the documented/current settings model and collapse two Dreamer agents into one invalid key.

**Required resolution:** Rewrite Dialectic scenarios per reasoning level and split Dreamer scenarios into deduction and induction paths. Add explicit env-resolution tests/tasks for Deriver, every supported Dialectic level, Summary, Dream Deduction, and Dream Induction.

### CRITICAL C3 — Required comparator artifacts are not checked into the pinned implementation baseline

**Spec reference:** Design D8 (`design.md:57-59`), comparator requirement (`specs/upstream-merge-verification/spec.md:3-20`).

**Evidence:**

- D8 states `scripts/compare_diagnostics.py` and `tests/scripts/test_compare_diagnostics.py` are “already checked in.”
- `git cat-file -e c00a2a876d28f17af632059876a33a23df349d15:scripts/compare_diagnostics.py` exits 128: path absent.
- The same command for `tests/scripts/test_compare_diagnostics.py` exits 128.
- Current Git status reports both paths as staged additions (`A`), not committed files.
- Tasks invoke them at `tasks.md:63-64,71`, but no task ensures they are committed before creating the merge branch/merge commit.

**Impact:** The documented procedure is not reproducible from the pinned clean branch; a clean worker cannot run required gates.

**Required resolution:** Make comparator + tests an explicit prerequisite commit/task with verified blob SHAs, or include an explicit task that stages and commits them before merge initiation. Correct D8’s truth claim.

### CRITICAL C4 — Deterministic rollback requirements have no implementation or verification tasks

**Spec reference:** `specs/upstream-merge-verification/spec.md:57-66`; Design D7 `design.md:53-55`.

**Evidence:**

- The spec requires pre-commit `git merge --abort` and post-commit restoration to exact `PREMERGE_MAIN_SHA`.
- Design claims both rollback paths are deterministic and tested.
- `tasks.md:1-83` contains no rollback exercise, byte/tree equality check, or recovery verification task.

**Impact:** A mandatory safety requirement can be declared complete without ever being exercised.

**Required resolution:** Add isolated-worktree rollback tests for both lifecycle states. Verify `HEAD`, index/worktree cleanliness, and tree identity against `PREMERGE_MAIN_SHA`; do not test destructive reset in the shared working tree.

### CRITICAL C5 — Static-analysis gate remains fail-open and does not implement its stated 254-file scope

**Spec reference:** `specs/upstream-merge-verification/spec.md:3-20`; Design D4 `design.md:40-43`; exploration Section 6 `:201-258`.

**Evidence:**

- Exploration capture commands `:241-247` use four `analyzer || [ $? -eq 1 ]` guards, but there is no `set -e`, `pipefail`, trap, or explicit status propagation in any reviewed change artifact.
- The two comparator commands at `:256-257` are sequential with no aggregation/preserved exit status; cleanup can also overwrite earlier failures.
- Tasks `8.3-8.8` (`tasks.md:59-64`) say “capture/run” but specify no fail-closed lifecycle, so the known defect is not corrected by the package.
- Independent Git calculation confirms 254 Python paths in the merge-base union. The documented manifests are derived from `PREMERGE_MAIN_SHA...HEAD`, which is a premerge-to-postmerge diff and therefore does not inherently include unchanged fork-only Python paths. This contradicts D4’s rejection of diff-only linting and the 254-file claim.

**Impact:** Analyzer crashes, malformed captures, or comparator failures can produce a final successful shell status; fork-only code broken by upstream interface changes can fall outside analysis.

**Required resolution:** Define one checked-in fail-closed orchestration script/test that validates analyzer exit codes and JSON schemas, preserves both comparator statuses, always cleans up via trap, and returns nonzero on any failure. Generate baseline/postmerge manifests from the full merge-base union (including old/new rename identities) and prove the expected scope with a manifest-count test.

### CRITICAL C6 — D10's 12-domain contract is not traceable end to end

**Spec reference:** Design D10 `design.md:65-67`; `specs/upstream-merge-verification/spec.md:22-55`; `tasks.md:67-76`.

**Evidence:**

- D10 names 12 domains including OpenSpec validation and OpenSpec status.
- The verification spec defines eight acceptance-test scenarios plus Ruff/Pyright comparator scenarios, but no scenario validates/status-checks `sync-upstream-main-full-merge` itself.
- `tasks.md:76` validates only `sync-upstream-structured-output-mode`; no final task validates or checks status of the merge change.

**Impact:** Design → requirement → task → pass-criterion traceability is incomplete, and the package under implementation can become invalid without failing the final matrix.

**Required resolution:** Map all 12 D10 domains one-to-one from design to scenario to exact task command and criterion. Add validation and status checks for this merge change; keep coexistence checks for `sync-upstream-structured-output-mode` as additional gates.

### CRITICAL C7 — Destructive and remote transitions lack explicit Commander authorization gates

**Spec reference:** `tasks.md:80-83`; migration plan `design.md:84-86`; collaboration phase-transition/remote-mutation governance.

**Evidence:** Tagging, fast-forwarding `main`, pushing `main`, and pushing the tag are ordinary sequential tasks. No STOP/Commander approval task separates verified local completion from mutation of `main` and remote state.

**Impact:** An Apply worker can follow the checklist and publish without a human phase-transition decision.

**Required resolution:** Insert an explicit Commander approval gate after all verification and before tag/main/push operations. Separate local verified-merge completion from remote publishing, and require workers to stop at the gate.

### WARNING W1 — Task-count metadata is false

**Evidence:** `tasks.md` contains 54 checkbox tasks across 10 groups, while the task/parent handoff claims 42.

**Required resolution:** Correct proposal/Kanban/handoff counts to 54, or intentionally consolidate the checklist and recount.

### WARNING W2 — Moving upstream ref is merged instead of the verified pinned object

**Evidence:** `tasks.md:4-7` fetches, names `UPSTREAM_SHA`, then runs `git merge upstream/main`. It does not require `upstream/main == UPSTREAM_SHA` or merge the pinned SHA.

**Required resolution:** Assert ref equality and fail closed, then merge the verified object ID.

### WARNING W3 — Alembic migration-conflict narrative is unsupported by the pinned diff

**Evidence:** Proposal `:3,31` and design `:3,72` claim upstream migration additions/conflicts and suggest `--rev-id` resequencing. `git diff --name-only PREMERGE...UPSTREAM -- '*migration*' '*migrations*' '*alembic*' | wc -l` returns `0`.

**Required resolution:** Retain the existing 25-test regression gate if desired, but remove unsupported migration-addition/conflict/resequencing claims.

### WARNING W4 — Static-analysis metrics conflate different path sets

**Evidence:** The merge-base union is independently confirmed as 254 Python paths, while the reviewed v10 protocol describes separate premerge-to-postmerge manifests. These are not equivalent metrics; a count assertion is absent.

**Required resolution:** Define baseline count, postmerge count, rename count, and unique old/new identity count explicitly and verify them in the orchestration test.

### WARNING W5 — Approval candidate is not immutable

**Evidence:** Git status shows `?? openspec/changes/sync-upstream-main-full-merge/`. The package under review is untracked; the comparator/test prerequisites are staged additions.

**Required resolution:** Stage or commit an immutable review candidate before re-review, and identify its commit/tree hash.

### INFO I1 — Structural and focused baseline checks pass

- `openspec validate sync-upstream-main-full-merge` → `Change 'sync-upstream-main-full-merge' is valid` (exit 0).
- `PYTHONPATH=. .venv/bin/python -m unittest tests/scripts/test_compare_diagnostics.py` → 5 tests, OK.
- Focused fork preservation command → 63 passed, 3 warnings, exit 0.
- `git rev-list --left-right --count PREMERGE...UPSTREAM` → `15 130`.
- `git diff --shortstat MERGE_BASE...PREMERGE` → 80 files, +5,678/-53.
- `git diff --shortstat MERGE_BASE...UPSTREAM` → 369 files, +54,465/-11,730.
- `git merge-tree PREMERGE UPSTREAM` reports exactly the 14 conflict paths listed in the exploration and mapped in `tasks.md`.

## Acceptance Mapping

| Review criterion | Result |
|---|---|
| Approved exploration alignment | Partial — package follows the blueprint but inherits its unresolved fail-open/static-scope defects |
| Preservation manifest | Present, but comparator/task prerequisites are not reproducible from pinned clean branch |
| 14 conflict files mapped | PASS — all 14 paths have explicit resolution tasks |
| Test/gate mapping | FAIL — rollback, self-validation/status, failure propagation, and Commander transition gates are missing |
| `openspec validate` | PASS — exit 0 |
| Implementation readiness | FAIL — seven CRITICAL findings |

## Re-review Gate

Re-review requires:

1. Scenario-safe MODIFIED deltas with all baseline behavior preserved or explicitly changed.
2. Correct per-agent/per-level fallback env contracts and tests.
3. Comparator artifacts committed or explicitly prerequisite-tasked.
4. Isolated pre/post-commit rollback verification tasks.
5. A tested, fail-closed 254-file orchestration path.
6. One-to-one D10 traceability and final validation/status of both active changes.
7. Explicit Commander approval before tag/main/push mutations.
8. Correct task/metric metadata, pinned-object merge semantics, truthful migration scope, and an immutable candidate.
