#!/usr/bin/env python3
"""
Production-grade comparator script to evaluate Ruff and BasedPyright baseline vs post-merge diagnostics.
Uses multiset (collections.Counter) matching, path normalization, schema validation, and rename remapping.
"""
import argparse
import json
import os
import sys
from collections import Counter


def parse_args():
    parser = argparse.ArgumentParser(description="Compare linter diagnostics between baseline and postmerge worktrees.")
    parser.add_argument("--baseline-dir", required=True, help="Path to materialized baseline worktree root")
    parser.add_argument("--postmerge-dir", required=True, help="Path to post-merge worktree root")
    parser.add_argument("--baseline-json", required=True, help="Path to baseline JSON report")
    parser.add_argument("--postmerge-json", required=True, help="Path to postmerge JSON report")
    parser.add_argument("--mode", choices=["ruff", "pyright"], required=True, help="Diagnostic mode")
    parser.add_argument("--rename-map-json", default=None, help="Optional JSON file with {old_rel_path: new_rel_path}")
    return parser.parse_args()

def normalize_path(full_path: str, root_dir: str) -> str:
    rel = os.path.relpath(full_path, root_dir)
    return rel.replace("\\", "/")

def load_rename_map(rename_map_path: str | None) -> dict[str, str]:
    if not rename_map_path or not os.path.exists(rename_map_path):
        return {}
    with open(rename_map_path, encoding="utf-8") as f:
        data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Rename map JSON must be a dict, got {type(data)}")
        return data

def compare_ruff(baseline_json_path: str, postmerge_json_path: str, baseline_dir: str, postmerge_dir: str, rename_map: dict[str, str]):
    if not os.path.exists(baseline_json_path):
        raise FileNotFoundError(f"Baseline JSON missing: {baseline_json_path}")
    if not os.path.exists(postmerge_json_path):
        raise FileNotFoundError(f"Postmerge JSON missing: {postmerge_json_path}")

    with open(baseline_json_path, encoding="utf-8") as f:
        b_data = json.load(f)
    with open(postmerge_json_path, encoding="utf-8") as f:
        p_data = json.load(f)

    if not isinstance(b_data, list):
        raise ValueError(f"Ruff baseline report must be a JSON list, got {type(b_data)}")
    if not isinstance(p_data, list):
        raise ValueError(f"Ruff postmerge report must be a JSON list, got {type(p_data)}")

    baseline_counter: Counter[tuple[str, str, str, int, int]] = Counter()
    for item in b_data:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid Ruff diagnostic entry: {item}")
        norm_path = normalize_path(item.get("filename", ""), baseline_dir)
        remapped_path = rename_map.get(norm_path, norm_path)
        code = item.get("code") or ""
        msg = (item.get("message") or "").strip()
        loc = item.get("location", {})
        row = loc.get("row", 0)
        col = loc.get("column", 0)
        key = (remapped_path, code, msg, row, col)
        baseline_counter[key] += 1

    new_diagnostics = []
    postmerge_counter: Counter[tuple[str, str, str, int, int]] = Counter()
    for item in p_data:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid Ruff diagnostic entry: {item}")
        norm_path = normalize_path(item.get("filename", ""), postmerge_dir)
        code = item.get("code") or ""
        msg = (item.get("message") or "").strip()
        loc = item.get("location", {})
        row = loc.get("row", 0)
        col = loc.get("column", 0)
        key = (norm_path, code, msg, row, col)
        postmerge_counter[key] += 1
        if postmerge_counter[key] > baseline_counter[key]:
            new_diagnostics.append(item)

    return new_diagnostics

def compare_pyright(baseline_json_path: str, postmerge_json_path: str, baseline_dir: str, postmerge_dir: str, rename_map: dict[str, str]):
    if not os.path.exists(baseline_json_path):
        raise FileNotFoundError(f"Baseline JSON missing: {baseline_json_path}")
    if not os.path.exists(postmerge_json_path):
        raise FileNotFoundError(f"Postmerge JSON missing: {postmerge_json_path}")

    with open(baseline_json_path, encoding="utf-8") as f:
        b_data = json.load(f)
    with open(postmerge_json_path, encoding="utf-8") as f:
        p_data = json.load(f)

    if not isinstance(b_data, dict) or "generalDiagnostics" not in b_data:
        raise ValueError("BasedPyright baseline report missing required 'generalDiagnostics' key")
    if not isinstance(p_data, dict) or "generalDiagnostics" not in p_data:
        raise ValueError("BasedPyright postmerge report missing required 'generalDiagnostics' key")

    baseline_counter: Counter[tuple[str, str, str, str]] = Counter()
    for item in b_data.get("generalDiagnostics", []):
        if item.get("severity") == "error":
            norm_path = normalize_path(item.get("file", ""), baseline_dir)
            remapped_path = rename_map.get(norm_path, norm_path)
            rule = item.get("rule") or ""
            msg = (item.get("message") or "").strip()
            range_info = str(item.get("range", {}))
            key = (remapped_path, rule, msg, range_info)
            baseline_counter[key] += 1

    new_diagnostics = []
    postmerge_counter: Counter[tuple[str, str, str, str]] = Counter()
    for item in p_data.get("generalDiagnostics", []):
        if item.get("severity") == "error":
            norm_path = normalize_path(item.get("file", ""), postmerge_dir)
            rule = item.get("rule") or ""
            msg = (item.get("message") or "").strip()
            range_info = str(item.get("range", {}))
            key = (norm_path, rule, msg, range_info)
            postmerge_counter[key] += 1
            if postmerge_counter[key] > baseline_counter[key]:
                new_diagnostics.append(item)

    return new_diagnostics

def main():
    args = parse_args()
    try:
        rename_map = load_rename_map(args.rename_map_json)
        if args.mode == "ruff":
            new_diags = compare_ruff(args.baseline_json, args.postmerge_json, args.baseline_dir, args.postmerge_dir, rename_map)
            tool_name = "Ruff"
        else:
            new_diags = compare_pyright(args.baseline_json, args.postmerge_json, args.baseline_dir, args.postmerge_dir, rename_map)
            tool_name = "BasedPyright"

        if new_diags:
            print(f"FAILED: Found {len(new_diags)} new {tool_name} regression diagnostics:")
            for d in new_diags[:10]:
                print(f"  - {d}")
            sys.exit(1)

        print(f"SUCCESS: 0 new {tool_name} diagnostics introduced.")
        sys.exit(0)
    except Exception as e:
        print(f"ERROR executing comparator: {e}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
