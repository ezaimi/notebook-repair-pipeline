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
    # Round-2 explanations (when present) must carry the same run id too.
    trace_run_ids |= {
        e.get("run_id") for e in (metrics.round2_explanation(d) for d in trace) if e is not None
    }
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
    resumed/final run under the same configuration).

    Recomputes against the config paths this run actually recorded in
    manifest["config_paths"] (e.g. a sibling config/*.kiste.yaml for a
    non-default LLM provider), not always the hardcoded Gemma defaults -
    mirrors the same fix already applied to build_manifest() in
    evaluation_manifest.py. Falls back to DEFAULT_HASHED_PATHS's own
    default for any path config_paths doesn't specify, so a manifest using
    the default Gemma paths (every existing I8 run) is checked exactly as
    before."""
    config_paths = manifest.get("config_paths", {})
    hashed_paths = dict(em.DEFAULT_HASHED_PATHS)
    hashed_paths["llm_explainer_config"] = config_paths.get("explainer_config", hashed_paths["llm_explainer_config"])
    hashed_paths["rag_repair_config"] = config_paths.get("repair_config", hashed_paths["rag_repair_config"])
    hashed_paths["fix_applicator_config"] = config_paths.get("fix_config", hashed_paths["fix_applicator_config"])

    current_hashes = em.build_config_hashes(root, hashed_paths)
    recorded_hashes = manifest.get("config_hashes", {})
    mismatches = {
        name: {"recorded": recorded_hashes.get(name), "current": current_hashes.get(name)}
        for name in current_hashes
        if current_hashes.get(name) != recorded_hashes.get(name)
    }
    # code_hashes (orchestrator/component source files) is a newer, optional
    # block: compared only when this manifest recorded it, so frozen I8/I9
    # manifests - which predate it - are checked exactly as before.
    recorded_code_hashes = manifest.get("code_hashes")
    if recorded_code_hashes is not None:
        current_code_hashes = em.build_code_hashes(root)
        for name in current_code_hashes:
            if current_code_hashes.get(name) != recorded_code_hashes.get(name):
                mismatches[f"code:{name}"] = {
                    "recorded": recorded_code_hashes.get(name),
                    "current": current_code_hashes.get(name),
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


# --- Round-2 explanation structure -------------------------------------------
#
# These checks describe the trace shape scripts/run_pipeline.py writes once
# Round-2 explanations exist. Every check passes trivially on an older trace
# that has no Round-2 explanations (frozen I8/I9 runs), so re-validating a
# frozen run is unaffected.

_ROUND2_INPUT_FIELDS = ("error_type", "error_message", "failing_module", "refined_subtype", "scope_status")


def _round1_and_trigger(diagnostics: Dict[str, Any]):
    rounds = diagnostics.get("rounds", [])
    round1 = next((r for r in rounds if r.get("round") == 1), None)
    round2 = next((r for r in rounds if r.get("round") == 2), None)
    trigger = (round1 or {}).get("round2_trigger") or {}
    return round1, round2, trigger


def check_round2_explanations_well_formed(trace: List[Dict[str, Any]]) -> CheckResult:
    """Every Round-2 explanation is tagged round == 2 and its input block
    is the reclassified round2_record it explains (same error type,
    message, failing module, subtype, scope) - never the original Round-1
    error."""
    offending = []
    for diagnostics in trace:
        _, _, trigger = _round1_and_trigger(diagnostics)
        explanation = trigger.get("explanation")
        if explanation is None:
            continue
        nid = diagnostics.get("notebook_execution_id")
        if explanation.get("round") != 2:
            offending.append((nid, f"round tag {explanation.get('round')!r}"))
            continue
        record = trigger.get("round2_record") or {}
        input_block = explanation.get("input") or {}
        for field in _ROUND2_INPUT_FIELDS:
            if input_block.get(field) != record.get(field):
                offending.append((nid, f"input.{field}={input_block.get(field)!r} != round2_record.{field}={record.get(field)!r}"))
                break
    return CheckResult("round2_explanations_well_formed", not offending, f"offending={offending}")


def check_round2_entry_explanation_matches_trigger(trace: List[Dict[str, Any]]) -> CheckResult:
    """When Round 2 executed, its entry's explanation is the SAME Round-2
    explanation the trigger carries (equal content). The duplicate is a
    representation of one record, not a second explanation."""
    offending = []
    for diagnostics in trace:
        _, round2, trigger = _round1_and_trigger(diagnostics)
        if round2 is None:
            continue
        entry_expl = round2.get("explanation")
        trig_expl = trigger.get("explanation")
        if entry_expl is None and trig_expl is None:
            continue  # pre-Round-2-explanation trace
        if entry_expl != trig_expl:
            offending.append(diagnostics.get("notebook_execution_id"))
    return CheckResult("round2_entry_explanation_matches_trigger", not offending, f"offending_notebook_execution_ids={offending}")


def check_no_round3_explanation(trace: List[Dict[str, Any]]) -> CheckResult:
    """No explanation anywhere carries a round tag above 2, and no Round-2
    entry carries its own round2_trigger (which is where a third
    reclassification/explanation would have to appear)."""
    offending = []
    for diagnostics in trace:
        nid = diagnostics.get("notebook_execution_id")
        rounds = diagnostics.get("rounds", [])
        for entry in rounds:
            expl = entry.get("explanation")
            if expl is not None and (expl.get("round") or 0) > 2:
                offending.append((nid, f"entry round tag {expl.get('round')}"))
            if entry.get("round") == 2 and "round2_trigger" in entry:
                offending.append((nid, "round2_trigger on a round-2 entry"))
            trig_expl = (entry.get("round2_trigger") or {}).get("explanation")
            if trig_expl is not None and (trig_expl.get("round") or 0) > 2:
                offending.append((nid, f"trigger explanation round tag {trig_expl.get('round')}"))
        if len([e for e in rounds if e.get("round") not in (1, 2)]) > 0:
            offending.append((nid, "rounds entry outside 1..2"))
    return CheckResult("no_round3_explanation", not offending, f"offending={offending}")


def check_top_level_explanation_is_round1(trace: List[Dict[str, Any]]) -> CheckResult:
    """The top-level explanation remains the ORIGINAL-failure explanation:
    tagged round 1 when tagged at all, and equal to the Round-1 entry's
    explanation when that entry carries one. Metric A reads the top level,
    so this is what keeps it comparable with the frozen runs."""
    offending = []
    for diagnostics in trace:
        nid = diagnostics.get("notebook_execution_id")
        top = diagnostics.get("explanation")
        if top is None:
            continue
        if "round" in top and top.get("round") != 1:
            offending.append((nid, f"top-level round tag {top.get('round')!r}"))
            continue
        round1, _, _ = _round1_and_trigger(diagnostics)
        r1_expl = (round1 or {}).get("explanation")
        if r1_expl is not None and r1_expl != top:
            offending.append((nid, "round-1 entry explanation differs from top-level"))
    return CheckResult("top_level_explanation_is_round1", not offending, f"offending={offending}")


def check_non_repairable_round2_explanations_are_trace_only(
    trace: List[Dict[str, Any]], rows: List[Dict[str, Any]]
) -> CheckResult:
    """A reclassified new error that was NOT repair-eligible may carry a
    Round-2 explanation on the trigger, but must have no executed Round-2
    entry and no round == 2 repair_attempts row (the one-row-per-executed-
    round contract is unchanged)."""
    round2_row_ids = {r.get("notebook_execution_id") for r in rows if r.get("round") == 2}
    offending = []
    for diagnostics in trace:
        _, round2, trigger = _round1_and_trigger(diagnostics)
        if "round2_record" not in trigger or trigger.get("triggered"):
            continue
        nid = diagnostics.get("notebook_execution_id")
        if round2 is not None:
            offending.append((nid, "executed round-2 entry despite not triggered"))
        if nid in round2_row_ids:
            offending.append((nid, "round-2 repair_attempts row despite not triggered"))
    return CheckResult("non_repairable_round2_explanations_are_trace_only", not offending, f"offending={offending}")


def check_round2_explanation_failure_did_not_block_repair(trace: List[Dict[str, Any]]) -> CheckResult:
    """A failed Round-2 explanation on a TRIGGERED record must not have
    prevented Round 2 from executing: a Round-2 entry must still exist
    (completed, or component_error from the repair round itself)."""
    offending = []
    for diagnostics in trace:
        _, round2, trigger = _round1_and_trigger(diagnostics)
        explanation = trigger.get("explanation")
        if explanation is None or not trigger.get("triggered"):
            continue
        status = (explanation.get("explanation_result") or {}).get("status")
        if status == "success":
            continue
        if round2 is None:
            offending.append(diagnostics.get("notebook_execution_id"))
    return CheckResult(
        "round2_explanation_failure_did_not_block_repair", not offending, f"offending_notebook_execution_ids={offending}"
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
        # Round-2 explanation structure (all pass trivially on traces that
        # predate Round-2 explanations, so frozen runs re-validate unchanged).
        check_round2_explanations_well_formed(trace),
        check_round2_entry_explanation_matches_trigger(trace),
        check_no_round3_explanation(trace),
        check_top_level_explanation_is_round1(trace),
        check_non_repairable_round2_explanations_are_trace_only(trace, rows),
        check_round2_explanation_failure_did_not_block_repair(trace),
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
