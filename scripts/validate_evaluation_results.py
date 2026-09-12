#!/usr/bin/env python3

"""ValidateEvaluationResults (i8): integrity/consistency checks for one
evaluation run, run after scripts/run_evaluation.py and before any results
are trusted.

Every check is pure with respect to its inputs (manifest dict, trace
records, repair_attempts rows, i2 dataset records) so the whole module is
testable with synthetic fixtures - no live database or subprocess is
required to exercise the check logic itself; only main() touches a real
SQLite file and the real filesystem.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import evaluation_manifest as em  # noqa: E402
import evaluation_metrics as metrics  # noqa: E402


class CheckResult:
    def __init__(self, name: str, passed: bool, detail: str = ""):
        self.name = name
        self.passed = passed
        self.detail = detail

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


# --- individual checks -------------------------------------------------------

def check_expected_record_count(expected_count: int, trace: List[Dict[str, Any]]) -> CheckResult:
    actual = len(trace)
    return CheckResult(
        "expected_record_count",
        actual == expected_count,
        f"expected={expected_count} actual={actual}",
    )


def check_all_expected_ids_present(expected_ids: Set[int], trace: List[Dict[str, Any]]) -> CheckResult:
    trace_ids = {d.get("notebook_execution_id") for d in trace}
    missing = expected_ids - trace_ids
    unexpected = trace_ids - expected_ids
    passed = not missing and not unexpected
    detail = f"missing={sorted(missing)} unexpected={sorted(unexpected)}"
    return CheckResult("all_expected_ids_present", passed, detail)


def check_no_silent_skips(expected_ids: Set[int], trace: List[Dict[str, Any]]) -> CheckResult:
    """Every expected id appears in the trace EXACTLY once (a duplicate
    trace entry for one id is just as much a silent-skip risk as a missing
    one - it means some other expected id never got its own line)."""
    trace_ids = [d.get("notebook_execution_id") for d in trace]
    duplicates = {i for i in trace_ids if trace_ids.count(i) > 1}
    passed = not duplicates and set(trace_ids) == expected_ids
    return CheckResult("no_silent_skips", passed, f"duplicate_trace_ids={sorted(duplicates)}")


def check_no_duplicate_rows(rows: List[Dict[str, Any]]) -> CheckResult:
    seen = set()
    duplicates = []
    for row in rows:
        key = (row.get("notebook_execution_id"), row.get("run_id"), row.get("round"))
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    return CheckResult("no_duplicate_repair_attempts_rows", not duplicates, f"duplicates={duplicates}")


def check_no_round_above_two(rows: List[Dict[str, Any]]) -> CheckResult:
    offending = [row for row in rows if (row.get("round") or 0) > 2]
    return CheckResult(
        "no_round_greater_than_two",
        not offending,
        f"offending_notebook_execution_ids={[r.get('notebook_execution_id') for r in offending]}",
    )


def check_round2_has_round1(rows: List[Dict[str, Any]]) -> CheckResult:
    round1_keys = {(r.get("notebook_execution_id"), r.get("run_id")) for r in rows if r.get("round") == 1}
    round2_rows = [r for r in rows if r.get("round") == 2]
    orphans = [
        r.get("notebook_execution_id")
        for r in round2_rows
        if (r.get("notebook_execution_id"), r.get("run_id")) not in round1_keys
    ]
    return CheckResult("every_round2_row_has_round1_row", not orphans, f"orphan_round2_notebook_execution_ids={orphans}")


def check_round2_only_after_valid_trigger(trace: List[Dict[str, Any]]) -> CheckResult:
    """Cross-checks the orchestrator's OWN round2_trigger decision (see
    scripts/run_pipeline.py evaluate_round2_trigger()) against whether a
    Round 2 entry actually exists in the trace - a Round 2 entry without a
    triggered=True Round-1 trigger would indicate the orchestrator's own
    invariant broke, not just a reporting-tool bug."""
    offending = []
    for diagnostics in trace:
        rounds = diagnostics.get("rounds", [])
        round1 = next((r for r in rounds if r.get("round") == 1), None)
        round2_exists = any(r.get("round") == 2 for r in rounds)
        if round2_exists:
            trigger = (round1 or {}).get("round2_trigger") or {}
            if not trigger.get("triggered"):
                offending.append(diagnostics.get("notebook_execution_id"))
    return CheckResult("round2_only_after_valid_trigger", not offending, f"offending_notebook_execution_ids={offending}")


def check_single_run_id(run_id: str, trace: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> CheckResult:
    trace_run_ids = {d.get("explanation", {}).get("run_id") for d in trace if d.get("explanation")}
    row_run_ids = {r.get("run_id") for r in rows}
    offending_trace = trace_run_ids - {run_id}
    offending_rows = row_run_ids - {run_id}
    passed = not offending_trace and not offending_rows
    return CheckResult(
        "single_run_id",
        passed,
        f"expected={run_id} unexpected_trace_run_ids={sorted(offending_trace, key=str)} unexpected_row_run_ids={sorted(offending_rows, key=str)}",
    )


def check_no_excluded_in_evaluation_split(
    split: str, trace: List[Dict[str, Any]], i2_by_id: Dict[int, Dict[str, Any]]
) -> CheckResult:
    if split != "evaluation":
        return CheckResult("no_excluded_records_in_evaluation_split", True, "not applicable (split != evaluation)")
    offending = [
        d.get("notebook_execution_id")
        for d in trace
        if (i2_by_id.get(d.get("notebook_execution_id")) or {}).get("scope_status") == "excluded"
    ]
    return CheckResult("no_excluded_records_in_evaluation_split", not offending, f"offending_ids={offending}")


def check_no_dev_records_in_evaluation_split(
    split: str, trace: List[Dict[str, Any]], i2_by_id: Dict[int, Dict[str, Any]]
) -> CheckResult:
    if split != "evaluation":
        return CheckResult("no_dev_records_in_evaluation_split", True, "not applicable (split != evaluation)")
    offending = [
        d.get("notebook_execution_id")
        for d in trace
        if (i2_by_id.get(d.get("notebook_execution_id")) or {}).get("split") == "dev"
    ]
    return CheckResult("no_dev_records_in_evaluation_split", not offending, f"offending_ids={offending}")


def check_manifest_hash_consistency(manifest: Dict[str, Any], root: Path) -> CheckResult:
    """Recomputes config/prompt hashes right now and compares against what
    the manifest recorded at run-start - a mismatch means prompts/configs
    changed after this run began (or between the dev run and a later
    resumed/final run under the same configuration)."""
    current_hashes = em.build_config_hashes(root)
    recorded_hashes = manifest.get("config_hashes", {})
    mismatches = {
        name: {"recorded": recorded_hashes.get(name), "current": current_hashes.get(name)}
        for name in current_hashes
        if current_hashes.get(name) != recorded_hashes.get(name)
    }
    return CheckResult("manifest_config_hash_consistency", not mismatches, json.dumps(mismatches))


def check_result_logger_reconciliation(trace: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> CheckResult:
    """Every trace round with status "completed" or "excluded" should have
    produced exactly one repair_attempts row (a "component_error"/
    "orchestrator_error"/"skipped_already_logged" round never inserts a
    row - see scripts/run_pipeline.py process_record())."""
    expected_row_keys = set()
    for diagnostics in trace:
        notebook_execution_id = diagnostics.get("notebook_execution_id")
        for round_entry in diagnostics.get("rounds", []):
            if round_entry.get("status") in {"completed", "excluded"}:
                expected_row_keys.add((notebook_execution_id, round_entry.get("round")))

    actual_row_keys = {(r.get("notebook_execution_id"), r.get("round")) for r in rows}
    missing = expected_row_keys - actual_row_keys
    unexpected = actual_row_keys - expected_row_keys
    passed = not missing and not unexpected
    return CheckResult(
        "result_logger_row_reconciliation",
        passed,
        f"missing_rows={sorted(missing, key=str)} unexpected_rows={sorted(unexpected, key=str)}",
    )


# --- orchestration --------------------------------------------------------

def load_repair_attempts_rows(db_path: Path, run_id: str) -> List[Dict[str, Any]]:
    if not db_path.is_file():
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM repair_attempts WHERE run_id = ?", (run_id,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def load_i2_by_id(i2_path: Path) -> Dict[int, Dict[str, Any]]:
    index: Dict[int, Dict[str, Any]] = {}
    with i2_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            notebook_execution_id = record.get("notebook_execution_id")
            if notebook_execution_id is not None:
                index[int(notebook_execution_id)] = record
    return index


def run_all_checks(
    manifest: Dict[str, Any],
    trace: List[Dict[str, Any]],
    rows: List[Dict[str, Any]],
    i2_by_id: Dict[int, Dict[str, Any]],
    root: Path,
) -> List[CheckResult]:
    expected_ids = {
        notebook_execution_id
        for notebook_execution_id, record in i2_by_id.items()
        if record.get("split") == manifest["split"]
    }

    return [
        check_expected_record_count(manifest["expected_record_count"], trace),
        check_all_expected_ids_present(expected_ids, trace),
        check_no_silent_skips(expected_ids, trace),
        check_no_duplicate_rows(rows),
        check_no_round_above_two(rows),
        check_round2_has_round1(rows),
        check_round2_only_after_valid_trigger(trace),
        check_single_run_id(manifest["run_id"], trace, rows),
        check_no_excluded_in_evaluation_split(manifest["split"], trace, i2_by_id),
        check_no_dev_records_in_evaluation_split(manifest["split"], trace, i2_by_id),
        check_manifest_hash_consistency(manifest, root),
        check_result_logger_reconciliation(trace, rows),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run I8 consistency/integrity checks for one evaluation run.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--i2", default=em.DEFAULT_I2_PATH)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    manifest = em.load_manifest(run_dir / "manifest.json")

    trace_path = Path(manifest["output_dir"]) / f"{manifest['run_id']}.jsonl"
    if not trace_path.is_absolute():
        trace_path = ROOT / trace_path
    trace = metrics.load_trace(trace_path)

    db_path = Path(manifest["database_path"])
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    rows = load_repair_attempts_rows(db_path, manifest["run_id"])

    i2_path = Path(args.i2)
    if not i2_path.is_absolute():
        i2_path = ROOT / i2_path
    i2_by_id = load_i2_by_id(i2_path)

    results = run_all_checks(manifest, trace, rows, i2_by_id, ROOT)

    report = {"run_id": manifest["run_id"], "checks": [r.to_dict() for r in results]}
    (run_dir / "validation_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    all_passed = all(r.passed for r in results)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.name}: {r.detail}")

    if not all_passed:
        print("INTEGRITY CHECKS FAILED")
        raise SystemExit(1)

    print("ALL INTEGRITY CHECKS PASSED")


if __name__ == "__main__":
    main()
