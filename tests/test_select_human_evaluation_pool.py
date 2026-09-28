import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import select_human_evaluation_pool as sp


def _explanation_record(notebook_execution_id, subtype, failing_module, error_message,
                         error_type="ModuleNotFoundError", status="success"):
    explanation_json = None
    if status == "success":
        explanation_json = {
            "summary": f"summary for {notebook_execution_id}",
            "root_cause": "root cause",
            "evidence": ["evidence item"],
            "failing_module": failing_module,
            "explanation_confidence": "high",
            "limitations": "limitations text",
        }
    return {
        "notebook_execution_id": notebook_execution_id,
        "explanation": {
            "input": {
                "refined_subtype": subtype,
                "failing_module": failing_module,
                "error_type": error_type,
                "error_message": error_message,
            },
            "explanation_result": {
                "status": status,
                "explanation_json": explanation_json,
            },
        },
    }


def _write_trace(path, records):
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


# --- load_eligible_records ------------------------------------------------------

def test_load_eligible_records_excludes_named_ids(tmp_path):
    records = [
        _explanation_record(21, "missing_package", "foo", "No module named 'foo'"),
        _explanation_record(100, "missing_package", "bar", "No module named 'bar'"),
    ]
    trace = tmp_path / "trace.jsonl"
    _write_trace(trace, records)
    eligible = sp.load_eligible_records(trace)
    ids = {r["notebook_execution_id"] for r in eligible}
    assert ids == {100}


def test_load_eligible_records_excludes_failed_explanations(tmp_path):
    records = [
        _explanation_record(100, "missing_package", "bar", "No module named 'bar'", status="failed"),
        _explanation_record(101, "missing_package", "baz", "No module named 'baz'", status="success"),
    ]
    trace = tmp_path / "trace.jsonl"
    _write_trace(trace, records)
    eligible = sp.load_eligible_records(trace)
    ids = {r["notebook_execution_id"] for r in eligible}
    assert ids == {101}


def test_load_eligible_records_excludes_incomplete_explanation_json(tmp_path):
    incomplete = _explanation_record(102, "missing_package", "qux", "No module named 'qux'")
    incomplete["explanation"]["explanation_result"]["explanation_json"]["limitations"] = ""
    trace = tmp_path / "trace.jsonl"
    _write_trace(trace, [incomplete])
    eligible = sp.load_eligible_records(trace)
    assert eligible == []


# --- distinct_wrong_version_signatures ------------------------------------------

def test_distinct_wrong_version_signatures_groups_by_module_and_message():
    eligible = [
        {"notebook_execution_id": 1, "subtype": "wrong_version", "failing_module": "numpy", "error_message": "msg-A"},
        {"notebook_execution_id": 2, "subtype": "wrong_version", "failing_module": "numpy", "error_message": "msg-A"},
        {"notebook_execution_id": 3, "subtype": "wrong_version", "failing_module": "scipy", "error_message": "msg-B"},
        {"notebook_execution_id": 4, "subtype": "missing_package", "failing_module": "sklearn", "error_message": "msg-C"},
    ]
    signatures = sp.distinct_wrong_version_signatures(eligible)
    assert set(signatures.keys()) == {("numpy", "msg-A"), ("scipy", "msg-B")}
    assert sorted(signatures[("numpy", "msg-A")]) == [1, 2]
    assert signatures[("scipy", "msg-B")] == [3]


# --- select_pool ------------------------------------------------------------------

def _synthetic_eligible_population():
    """9 distinct missing_package modules (2 candidates each) and exactly
    3 distinct wrong_version signatures (spread over several candidate
    notebook_execution_ids), matching the real population's shape closely
    enough to exercise select_pool()'s logic end to end."""
    eligible = []
    for i, module in enumerate(["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9"]):
        for j in range(2):
            nid = 1000 + i * 10 + j
            eligible.append({
                "notebook_execution_id": nid,
                "subtype": "missing_package",
                "failing_module": module,
                "error_message": f"No module named '{module}'",
            })
    signatures = [("numpy", "sig-A"), ("scipy", "sig-B"), ("scipy", "sig-C")]
    for k, (module, sig) in enumerate(signatures):
        for j in range(3):
            nid = 2000 + k * 10 + j
            eligible.append({
                "notebook_execution_id": nid,
                "subtype": "wrong_version",
                "failing_module": module,
                "error_message": sig,
            })
    return eligible


def test_select_pool_returns_nine_missing_package_and_three_wrong_version():
    eligible = _synthetic_eligible_population()
    pool = sp.select_pool(eligible)
    assert len(pool) == 12
    subtypes = [r["subtype"] for r in pool]
    assert subtypes.count("missing_package") == 9
    assert subtypes.count("wrong_version") == 3

    # missing_package side: 9 distinct modules, no duplication
    mp_modules = [r["failing_module"] for r in pool if r["subtype"] == "missing_package"]
    assert len(set(mp_modules)) == 9

    # wrong_version side: one representative per distinct signature
    wv = [(r["failing_module"], r["error_message"]) for r in pool if r["subtype"] == "wrong_version"]
    assert set(wv) == {("numpy", "sig-A"), ("scipy", "sig-B"), ("scipy", "sig-C")}


def test_select_pool_is_deterministic_across_repeated_calls():
    eligible = _synthetic_eligible_population()
    pool_a = sp.select_pool(eligible)
    pool_b = sp.select_pool(eligible)
    ids_a = sorted(r["notebook_execution_id"] for r in pool_a)
    ids_b = sorted(r["notebook_execution_id"] for r in pool_b)
    assert ids_a == ids_b


def test_select_pool_raises_if_wrong_version_signature_count_is_not_three():
    eligible = _synthetic_eligible_population()
    # add a fourth distinct wrong_version signature - the frozen 9/3 split
    # assumes exactly 3, and must not silently proceed if that changes.
    eligible.append({
        "notebook_execution_id": 3000,
        "subtype": "wrong_version",
        "failing_module": "pandas",
        "error_message": "sig-D",
    })
    with pytest.raises(AssertionError, match="expected exactly 3"):
        sp.select_pool(eligible)


# --- end-to-end against the real frozen pool (regression guard) ----------------

def test_recomputed_pool_matches_frozen_pool_on_real_data():
    """Guards against silently drifting from the frozen study pool: if the
    real trace file or the frozen CSV ever change, this test fails loudly
    instead of the human-evaluation study quietly running against a
    different set of examples than what was approved."""
    trace_path = ROOT / "data/evaluation/i8-eval-final-rerun-20260913T113423Z/raw/pipeline-runs/i8-eval-final-rerun-20260913T113423Z.jsonl"
    if not trace_path.is_file() or not sp.FROZEN_EXAMPLES_CSV.is_file():
        pytest.skip("real evaluation trace or frozen pool CSV not present in this environment")

    eligible = sp.load_eligible_records(trace_path)
    recomputed_ids = sorted(r["notebook_execution_id"] for r in sp.select_pool(eligible))
    frozen_ids = sp.load_frozen_ids(sp.FROZEN_EXAMPLES_CSV)
    assert recomputed_ids == frozen_ids
