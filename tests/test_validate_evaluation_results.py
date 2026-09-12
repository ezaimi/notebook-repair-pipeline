import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_evaluation_results as ver


def row(notebook_execution_id, run_id="run-1", round_=1, action="install", outcome="fixed"):
    return {"notebook_execution_id": notebook_execution_id, "run_id": run_id, "round": round_, "action": action, "outcome": outcome}


def diag(notebook_execution_id, rounds, explanation_run_id="run-1"):
    return {
        "notebook_execution_id": notebook_execution_id,
        "explanation": {"run_id": explanation_run_id},
        "rounds": rounds,
    }


def rnd(round_number, status="completed", round2_trigger=None):
    entry = {"round": round_number, "status": status}
    if round2_trigger is not None:
        entry["round2_trigger"] = round2_trigger
    return entry


# --- expected record count / silent skips / id accounting ---------------------

def test_check_expected_record_count_pass():
    result = ver.check_expected_record_count(3, [diag(1, [rnd(1)]), diag(2, [rnd(1)]), diag(3, [rnd(1)])])
    assert result.passed is True


def test_check_expected_record_count_incomplete_run_fails():
    result = ver.check_expected_record_count(13, [diag(1, [rnd(1)]), diag(2, [rnd(1)])])
    assert result.passed is False
    assert "expected=13" in result.detail
    assert "actual=2" in result.detail


def test_check_all_expected_ids_present_detects_missing():
    result = ver.check_all_expected_ids_present({1, 2, 3}, [diag(1, [rnd(1)]), diag(2, [rnd(1)])])
    assert result.passed is False
    assert "3" in result.detail


def test_check_all_expected_ids_present_detects_unexpected():
    result = ver.check_all_expected_ids_present({1}, [diag(1, [rnd(1)]), diag(99, [rnd(1)])])
    assert result.passed is False
    assert "99" in result.detail


def test_check_no_silent_skips_detects_duplicate_trace_entry():
    result = ver.check_no_silent_skips({1, 2}, [diag(1, [rnd(1)]), diag(1, [rnd(1)])])
    assert result.passed is False


def test_check_no_silent_skips_passes_for_exact_one_to_one():
    result = ver.check_no_silent_skips({1, 2}, [diag(1, [rnd(1)]), diag(2, [rnd(1)])])
    assert result.passed is True


# --- duplicate (notebook_execution_id, run_id, round) detection --------------

def test_check_no_duplicate_rows_detects_duplicate():
    rows = [row(8, round_=1), row(8, round_=1)]
    result = ver.check_no_duplicate_rows(rows)
    assert result.passed is False


def test_check_no_duplicate_rows_allows_same_notebook_different_round():
    rows = [row(8, round_=1), row(8, round_=2)]
    result = ver.check_no_duplicate_rows(rows)
    assert result.passed is True


def test_check_no_duplicate_rows_allows_same_notebook_different_run():
    rows = [row(8, run_id="run-1", round_=1), row(8, run_id="run-2", round_=1)]
    result = ver.check_no_duplicate_rows(rows)
    assert result.passed is True


# --- round > 2 rejection --------------------------------------------------------

def test_check_no_round_above_two_rejects_round_three():
    rows = [row(8, round_=1), row(8, round_=2), row(8, round_=3)]
    result = ver.check_no_round_above_two(rows)
    assert result.passed is False
    assert "8" in result.detail


def test_check_no_round_above_two_passes_for_rounds_one_and_two():
    rows = [row(8, round_=1), row(8, round_=2)]
    result = ver.check_no_round_above_two(rows)
    assert result.passed is True


# --- round 2 requires a round 1 --------------------------------------------------

def test_check_round2_has_round1_rejects_orphan_round2():
    rows = [row(8, round_=2)]  # no round=1 row for notebook 8
    result = ver.check_round2_has_round1(rows)
    assert result.passed is False
    assert "8" in result.detail


def test_check_round2_has_round1_passes_when_round1_present():
    rows = [row(8, round_=1), row(8, round_=2)]
    result = ver.check_round2_has_round1(rows)
    assert result.passed is True


def test_check_round2_only_after_valid_trigger_rejects_untriggered_round2():
    trace = [diag(174, [rnd(1, round2_trigger={"triggered": False, "reason": "same_as_original_error"}), rnd(2)])]
    result = ver.check_round2_only_after_valid_trigger(trace)
    assert result.passed is False


def test_check_round2_only_after_valid_trigger_passes_when_triggered():
    trace = [diag(174, [rnd(1, round2_trigger={"triggered": True, "reason": "new_dependency_error_eligible"}), rnd(2)])]
    result = ver.check_round2_only_after_valid_trigger(trace)
    assert result.passed is True


def test_check_round2_only_after_valid_trigger_passes_when_no_round2_at_all():
    trace = [diag(8, [rnd(1, round2_trigger={"triggered": False, "reason": "round1_outcome_not_still_failing"})])]
    result = ver.check_round2_only_after_valid_trigger(trace)
    assert result.passed is True


# --- single run_id ----------------------------------------------------------------

def test_check_single_run_id_detects_stray_run_id_in_rows():
    trace = [diag(8, [rnd(1)], explanation_run_id="run-1")]
    rows = [row(8, run_id="run-1"), row(9, run_id="run-STRAY")]
    result = ver.check_single_run_id("run-1", trace, rows)
    assert result.passed is False


def test_check_single_run_id_passes_when_consistent():
    trace = [diag(8, [rnd(1)], explanation_run_id="run-1")]
    rows = [row(8, run_id="run-1")]
    result = ver.check_single_run_id("run-1", trace, rows)
    assert result.passed is True


# --- excluded / dev leakage into evaluation split -------------------------------

def test_check_no_excluded_in_evaluation_split_detects_leak():
    trace = [diag(15, [rnd(1)])]
    i2_by_id = {15: {"scope_status": "excluded", "split": "excluded"}}
    result = ver.check_no_excluded_in_evaluation_split("evaluation", trace, i2_by_id)
    assert result.passed is False


def test_check_no_excluded_in_evaluation_split_not_applicable_for_dev_run():
    result = ver.check_no_excluded_in_evaluation_split("dev", [], {})
    assert result.passed is True
    assert "not applicable" in result.detail


def test_check_no_dev_records_in_evaluation_split_detects_leak():
    trace = [diag(8, [rnd(1)])]
    i2_by_id = {8: {"scope_status": "usable", "split": "dev"}}
    result = ver.check_no_dev_records_in_evaluation_split("evaluation", trace, i2_by_id)
    assert result.passed is False


# --- manifest hash consistency ---------------------------------------------------

def test_check_manifest_hash_consistency_detects_drift(tmp_path, monkeypatch):
    import evaluation_manifest as em

    def fake_build_config_hashes(root, hashed_paths=None):
        return {"package_mapping": "NEW_HASH"}

    monkeypatch.setattr(em, "build_config_hashes", fake_build_config_hashes)
    manifest = {"config_hashes": {"package_mapping": "OLD_HASH"}}
    result = ver.check_manifest_hash_consistency(manifest, tmp_path)
    assert result.passed is False
    assert "OLD_HASH" in result.detail
    assert "NEW_HASH" in result.detail


def test_check_manifest_hash_consistency_passes_when_unchanged(tmp_path, monkeypatch):
    import evaluation_manifest as em

    monkeypatch.setattr(em, "build_config_hashes", lambda root, hashed_paths=None: {"package_mapping": "SAME"})
    manifest = {"config_hashes": {"package_mapping": "SAME"}}
    result = ver.check_manifest_hash_consistency(manifest, tmp_path)
    assert result.passed is True


# --- ResultLogger row reconciliation ---------------------------------------------

def test_check_result_logger_reconciliation_detects_missing_row():
    trace = [diag(8, [rnd(1, status="completed")])]
    rows = []  # expected one row for (8, 1), none present
    result = ver.check_result_logger_reconciliation(trace, rows)
    assert result.passed is False


def test_check_result_logger_reconciliation_ignores_component_error_rounds():
    trace = [diag(8, [rnd(1, status="component_error")])]
    rows = []
    result = ver.check_result_logger_reconciliation(trace, rows)
    assert result.passed is True


def test_check_result_logger_reconciliation_passes_for_matching_rows():
    trace = [diag(8, [rnd(1, status="completed")])]
    rows = [row(8, round_=1)]
    result = ver.check_result_logger_reconciliation(trace, rows)
    assert result.passed is True
