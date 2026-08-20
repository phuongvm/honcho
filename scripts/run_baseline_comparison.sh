#!/usr/bin/env bash
# Fail-closed dual-worktree baseline-delta static analysis wrapper.
# Usage: ./scripts/run_baseline_comparison.sh <PREMERGE_SHA>
#
# Exit codes:
#   0  — all comparisons passed (zero new errors)
#   1  — new errors detected by comparator
#   2  — invalid/missing analyzer report or comparator schema error
#   >2 — analyzer crash or binary-not-found (propagated exit code)
set -Eeuo pipefail

###############################################################################
# Help
###############################################################################
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'EOF'
Usage: scripts/run_baseline_comparison.sh <PREMERGE_SHA>

Dual-worktree baseline-delta static analysis wrapper.

Steps performed:
  1. Materialise a detached baseline worktree at <PREMERGE_SHA>.
  2. Parse `git diff --name-status -M` into baseline and postmerge
     Python file manifests plus a rename_map.json.
  3. Capture Ruff and BasedPyright JSON diagnostics on BOTH worktrees
     (baseline analyzers run strictly inside the baseline worktree).
  4. Invoke scripts/compare_diagnostics.py for each analyzer with
     --baseline-dir, --postmerge-dir, --baseline-json, --postmerge-json,
     --rename-map-json, and --mode.
  5. Exit 0 only if both comparators report zero new errors.

Fail-closed semantics:
  - Analyzer exit >1 or 127 aborts immediately.
  - Comparator exit !=0 aborts immediately.
  - Cleanup trap removes the baseline worktree AND the report directory
    while preserving the original exit code.
EOF
    exit 0
fi

###############################################################################
# Arguments
###############################################################################
PREMERGE_SHA="${1:?Usage: $0 <PREMERGE_SHA>}"
BASELINE_DIR=""
REPORT_DIR=""
ORIGINAL_EXIT=0

###############################################################################
# Cleanup trap — always remove worktree AND report dir, preserve exit code
###############################################################################
cleanup() {
    ORIGINAL_EXIT=$?
    if [[ -n "${BASELINE_DIR}" && -d "${BASELINE_DIR}" ]]; then
        git worktree remove --force "${BASELINE_DIR}" 2>/dev/null || true
    fi
    if [[ -n "${REPORT_DIR}" && -d "${REPORT_DIR}" ]]; then
        rm -rf "${REPORT_DIR}"
    fi
    exit "${ORIGINAL_EXIT}"
}
trap cleanup EXIT

###############################################################################
# Validate analyzer exit code; abort on crash (>1) or missing binary (127)
###############################################################################
validate_analyzer_exit() {
    local name="$1" code="$2"
    if (( code == 127 )); then
        echo "FATAL: ${name} binary not found (exit 127). Aborting." >&2
        exit 127
    fi
    if (( code > 1 )); then
        echo "FATAL: ${name} crashed with exit code ${code}. Aborting." >&2
        exit "${code}"
    fi
    # exit 0 = clean; exit 1 = findings (acceptable for baseline capture)
}

###############################################################################
# Validate JSON report file exists and is non-empty
###############################################################################
validate_report() {
    local path="$1" label="$2"
    if [[ ! -f "${path}" ]]; then
        echo "FATAL: ${label} report not found at ${path}. Aborting." >&2
        exit 2
    fi
    if [[ ! -s "${path}" ]]; then
        echo "FATAL: ${label} report is empty at ${path}. Aborting." >&2
        exit 2
    fi
}

###############################################################################
# Resolve the project root (where this script lives under scripts/)
###############################################################################
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Ensure .venv/bin tools (ruff, basedpyright, python3) resolve reliably
export PATH="${PROJECT_ROOT}/.venv/bin:${PATH}"

###############################################################################
# Step 1: Create baseline worktree
###############################################################################
BASELINE_DIR=$(mktemp -d /tmp/honcho-baseline-XXXXXX)
rmdir "${BASELINE_DIR}"  # git worktree add needs a non-existing target
git worktree add -d "${BASELINE_DIR}" "${PREMERGE_SHA}"
echo "Baseline worktree created at ${BASELINE_DIR}"

###############################################################################
# Step 2: Generate manifests with rename tracking
###############################################################################
REPORT_DIR=$(mktemp -d /tmp/honcho-reports-XXXXXX)
git diff --name-status -M "${PREMERGE_SHA}...HEAD" > "${REPORT_DIR}/name_status.txt"

# Parse name_status.txt into:
#   baseline_manifest.txt  — Python files that existed in baseline
#   postmerge_manifest.txt — Python files that exist in postmerge
#   rename_map.json        — {old_rel_path: new_rel_path}
python3 - "${REPORT_DIR}" "${BASELINE_DIR}" "${PROJECT_ROOT}" <<'PYEOF'
import json, os, sys

report_dir = sys.argv[1]
baseline_dir = sys.argv[2]
postmerge_dir = sys.argv[3]

baseline_paths = set()
postmerge_paths = set()
rename_map = {}

with open(os.path.join(report_dir, "name_status.txt"), encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        status = parts[0]
        if status == "D":
            # Deleted — existed in baseline only
            path = parts[1]
            if path.endswith(".py"):
                baseline_paths.add(path)
        elif status == "A":
            # Added — exists in postmerge only
            path = parts[1]
            if path.endswith(".py"):
                postmerge_paths.add(path)
        elif status == "M":
            # Modified — exists in both
            path = parts[1]
            if path.endswith(".py"):
                baseline_paths.add(path)
                postmerge_paths.add(path)
        elif status.startswith("R"):
            # Renamed (with optional similarity score, e.g. R100)
            old_path = parts[1]
            new_path = parts[2]
            if old_path.endswith(".py"):
                baseline_paths.add(old_path)
                rename_map[old_path] = new_path
            if new_path.endswith(".py"):
                postmerge_paths.add(new_path)
        elif status == "C":
            # Copied
            old_path = parts[1]
            new_path = parts[2]
            if old_path.endswith(".py"):
                baseline_paths.add(old_path)
            if new_path.endswith(".py"):
                postmerge_paths.add(new_path)
        elif status == "T":
            # Type change — exists in both
            path = parts[1]
            if path.endswith(".py"):
                baseline_paths.add(path)
                postmerge_paths.add(path)

# Write manifests
with open(os.path.join(report_dir, "baseline_manifest.txt"), "w") as f:
    for p in sorted(baseline_paths):
        f.write(p + "\n")

with open(os.path.join(report_dir, "postmerge_manifest.txt"), "w") as f:
    for p in sorted(postmerge_paths):
        f.write(p + "\n")

# Write rename map
with open(os.path.join(report_dir, "rename_map.json"), "w") as f:
    json.dump(rename_map, f, indent=2)

# Print summary
print(f"Manifests generated: baseline={len(baseline_paths)} files, "
      f"postmerge={len(postmerge_paths)} files, renames={len(rename_map)}")
PYEOF

echo "Manifests and rename map generated in ${REPORT_DIR}"

###############################################################################
# Step 3: Capture baseline Ruff diagnostics (inside BASELINE_DIR, manifest-scoped)
###############################################################################
echo "=== Capturing baseline Ruff diagnostics ==="
ruff_baseline_exit=0
if [[ -s "${REPORT_DIR}/baseline_manifest.txt" ]]; then
    # Read manifest into array; run ruff directly (not via xargs) so exit 1
    # (findings present) is preserved — xargs would remap it to exit 123.
    mapfile -t baseline_files < "${REPORT_DIR}/baseline_manifest.txt"
    (cd "${BASELINE_DIR}" && ruff check --output-format=json "${baseline_files[@]}") > "${REPORT_DIR}/ruff_baseline.json" 2>/dev/null || ruff_baseline_exit=$?
else
    echo "[]" > "${REPORT_DIR}/ruff_baseline.json"
fi
validate_analyzer_exit "Ruff (baseline)" "${ruff_baseline_exit}"
validate_report "${REPORT_DIR}/ruff_baseline.json" "Ruff baseline"

###############################################################################
# Step 4: Capture baseline BasedPyright diagnostics (inside BASELINE_DIR)
###############################################################################
echo "=== Capturing baseline BasedPyright diagnostics ==="
pyright_baseline_exit=0
(cd "${BASELINE_DIR}" && basedpyright --outputjson) > "${REPORT_DIR}/pyright_baseline.json" 2>/dev/null || pyright_baseline_exit=$?
validate_analyzer_exit "BasedPyright (baseline)" "${pyright_baseline_exit}"
validate_report "${REPORT_DIR}/pyright_baseline.json" "BasedPyright baseline"

###############################################################################
# Step 5: Capture postmerge Ruff diagnostics (in project root, manifest-scoped)
###############################################################################
echo "=== Capturing postmerge Ruff diagnostics ==="
ruff_postmerge_exit=0
if [[ -s "${REPORT_DIR}/postmerge_manifest.txt" ]]; then
    # Read manifest into array; run ruff directly (not via xargs) so exit 1
    # (findings present) is preserved — xargs would remap it to exit 123.
    mapfile -t postmerge_files < "${REPORT_DIR}/postmerge_manifest.txt"
    (cd "${PROJECT_ROOT}" && ruff check --output-format=json "${postmerge_files[@]}") > "${REPORT_DIR}/ruff_postmerge.json" 2>/dev/null || ruff_postmerge_exit=$?
else
    echo "[]" > "${REPORT_DIR}/ruff_postmerge.json"
fi
validate_analyzer_exit "Ruff (postmerge)" "${ruff_postmerge_exit}"
validate_report "${REPORT_DIR}/ruff_postmerge.json" "Ruff postmerge"

###############################################################################
# Step 6: Capture postmerge BasedPyright diagnostics (in project root)
###############################################################################
echo "=== Capturing postmerge BasedPyright diagnostics ==="
pyright_postmerge_exit=0
(cd "${PROJECT_ROOT}" && basedpyright --outputjson) > "${REPORT_DIR}/pyright_postmerge.json" 2>/dev/null || pyright_postmerge_exit=$?
validate_analyzer_exit "BasedPyright (postmerge)" "${pyright_postmerge_exit}"
validate_report "${REPORT_DIR}/pyright_postmerge.json" "BasedPyright postmerge"

###############################################################################
# Step 7: Run Ruff comparator — fail on new errors
###############################################################################
echo "=== Running Ruff comparator ==="
python3 scripts/compare_diagnostics.py \
    --mode=ruff \
    --baseline-dir "${BASELINE_DIR}" \
    --postmerge-dir "${PROJECT_ROOT}" \
    --baseline-json "${REPORT_DIR}/ruff_baseline.json" \
    --postmerge-json "${REPORT_DIR}/ruff_postmerge.json" \
    --rename-map-json "${REPORT_DIR}/rename_map.json"
# comparator exit 0=pass, 1=new errors, 2=schema error — all nonzero abort via set -e

###############################################################################
# Step 8: Run BasedPyright comparator — fail on new errors
###############################################################################
echo "=== Running BasedPyright comparator ==="
python3 scripts/compare_diagnostics.py \
    --mode=pyright \
    --baseline-dir "${BASELINE_DIR}" \
    --postmerge-dir "${PROJECT_ROOT}" \
    --baseline-json "${REPORT_DIR}/pyright_baseline.json" \
    --postmerge-json "${REPORT_DIR}/pyright_postmerge.json" \
    --rename-map-json "${REPORT_DIR}/rename_map.json"

###############################################################################
# Step 9: All passed
###############################################################################
echo "=== All baseline-delta comparisons passed: 0 new errors ==="
# cleanup trap fires and exits with 0
