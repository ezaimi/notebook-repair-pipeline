"""Evaluation-side contract for Round-2 LLMExplainer explanations.

Covers the three explanation metrics (A original / B Round-2 / C combined),
their denominators, the no-double-counting rule for the duplicated
trigger/round-entry trace representation, record-vs-attempt separation,
isolation from every repair metric, the new integrity checks, the manifest
provenance additions, and the explanation summary table.
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_results as er
import evaluation_manifest as em
import evaluation_metrics as metrics
import validate_evaluation_results as ver


# --- fixture builders (new trace shape written by scripts/run_pipeline.py) ----

def expl(round_number, status="success", attempts=1, run_id="run-1", **input_fields):
    """One explanation record as explain_record()/explain_round_record()
    produce it: input block, llm block, explanation_result, round tag."""
    module = input_fields.get("failing_module", "x")
    base_input = {
        "error_type": "ModuleNotFoundError",
        "error_message": f"No module named '{module}'",
        "failing_module": module,
        "refined_subtype": "missing_package",
        "scope_status": "usable",
    }
    base_input.update(input_fields)
    result = {"status": status, "attempts": attempts}
    if status == "success":
        result["explanation_json"] = {"summary": "s", "failing_module": base_input["failing_module"]}
    else:
        result["explanation_json"] = None
        result["failure_category"] = "timeout"
        result["error"] = "timeout: timed out"
    return {"run_id": run_id, "round": round_number, "input": base_input,
            "llm": {"llm_model": "gemma2:9b", "prompt_strategy": "few_shot"},
            "explanation_result": result}


def i4(status="success", schema_valid=True, grounding_valid=True, action="install", retrieval="resolved"):
    r = {"status": status, "eligibility": {"decision": "usable"},
         "input": {"refined_subtype": "missing_package", "failing_module": "x"},
         "final_action": action, "retrieval_result": {"status": retrieval}}
    if status == "success":
        r["schema_validation"] = {"valid": schema_valid}
        r["grounding_validation"] = {"valid": grounding_valid}
    else:
        r["schema_validation"] = None
        r["grounding_validation"] = None
    return r


def i5(outcome, new_error=None, same=False):
    return {"status": "completed", "outcome": outcome, "same_as_original_error": same,
            "new_error_type": "ModuleNotFoundError" if new_error else None,
            "new_error_message": f"No module named '{new_error}'" if new_error else None}


def r2record(module, subtype="missing_package", scope="usable"):
    return {"error_type": "ModuleNotFoundError", "error_message": f"No module named '{module}'",
            "failing_module": module, "refined_subtype": subtype, "scope_status": scope,
            "context_status": "round2_reclassified_from_execution_outcome"}


def one_round(nid, r1_expl=None, r1_i4=None, r1_i5=None, trigger=None):
    """A notebook whose Round 1 completed and (optionally) evaluated a trigger."""
    r1_expl = r1_expl or expl(1, failing_module="orig")
    entry = {"round": 1, "status": "completed", "explanation_status": r1_expl["explanation_result"]["status"],
             "explanation": r1_expl, "i4_result": r1_i4 or i4(), "i5_result": r1_i5 or i5("fixed")}
    if trigger is not None:
        entry["round2_trigger"] = trigger
    return {"notebook_execution_id": nid, "explanation_status": r1_expl["explanation_result"]["status"],
            "explanation": r1_expl, "rounds": [entry]}


def two_rounds(nid, r2_expl, r2_i4=None, r2_i5=None, rec=None):
    """A notebook where Round 2 executed: the Round-2 explanation appears on
    the trigger AND on the executed Round-2 entry (same content)."""
    rec = rec or r2record("pandas")
    trigger = {"triggered": True, "reason": "new_dependency_error_eligible", "round2_record": rec,
               "explanation_status": r2_expl["explanation_result"]["status"], "explanation": r2_expl}
    d = one_round(nid, r1_i5=i5("still_failing", new_error="pandas"), trigger=trigger)
    d["rounds"].append({"round": 2, "status": "completed",
                        "explanation_status": r2_expl["explanation_result"]["status"],
                        "explanation": json.loads(json.dumps(r2_expl)),  # on-disk copy, equal not identical
                        "i4_result": r2_i4 or i4(), "i5_result": r2_i5 or i5("fixed")})
    return d


def non_repairable(nid, r2_expl, rec=None):
    """A notebook whose new error was reclassified and explained but NOT
    repair-eligible: explanation on the trigger only, no Round-2 entry."""
    rec = rec or r2record("libxcb.so.1", subtype="system_library", scope="excluded")
    trigger = {"triggered": False, "reason": "new_error_not_repair_eligible:excluded", "round2_record": rec,
               "exclusion_reason": "requires system library, outside pip-only scope",
               "explanation_status": r2_expl["explanation_result"]["status"], "explanation": r2_expl}
    return one_round(nid, r1_i5=i5("still_failing", new_error="libxcb.so.1"), trigger=trigger)


def old_style(nid, explanation_status="success", triggered=True):
    """A pre-Round-2-explanation trace line (frozen I8/I9 shape): top-level
    explanation_status only, trigger without any explanation, Round-2 entry
    (if any) without explanation."""
    trigger = {"triggered": triggered, "reason": "x", "round2_record": r2record("pandas")}
    rounds = [{"round": 1, "status": "completed", "i4_result": i4(), "i5_result": i5("still_failing", "pandas"),
               "round2_trigger": trigger}]
    if triggered:
        rounds.append({"round": 2, "status": "completed", "i4_result": i4(), "i5_result": i5("fixed")})
    return {"notebook_execution_id": nid, "explanation_status": explanation_status,
            "explanation": {"run_id": "run-1"}, "rounds": rounds}


# =============================================================================
# Metric A: original-failure explanation validity is notebook-level
# =============================================================================

def test_original_denominator_is_notebooks_processed_regardless_of_round2_explanations():
    trace = [
        two_rounds(1, expl(2, failing_module="pandas")),
        non_repairable(2, expl(2, failing_module="libxcb.so.1")),
        one_round(3, r1_expl=expl(1, status="failed", attempts=2, failing_module="orig")),
    ]
    a = metrics.original_explanation_schema_validity_rate(trace)
    assert a == {"valid": 2, "failed": 1, "processed": 3, "rate": 2 / 3}
    # not 5 (3 originals + 2 Round-2), and not 2 (repair rounds executed)
    assert a["processed"] == len(trace)


def test_legacy_alias_keeps_exact_pre_round2_shape_and_meaning():
    trace = [two_rounds(1, expl(2)), non_repairable(2, expl(2, status="failed"))]
    legacy = metrics.explanation_schema_validity_rate(trace)
    assert legacy == {"valid": 2, "processed": 2, "rate": 1.0}
    assert set(legacy) == {"valid", "processed", "rate"}  # no new keys leak into the frozen CSV shape


# =============================================================================
# Metric B: Round-2 denominator = every explained reclassified error
# =============================================================================

def test_round2_denominator_includes_trace_only_non_repairable_explanations():
    trace = [
        two_rounds(1, expl(2, failing_module="pandas")),               # eligible, executed
        non_repairable(2, expl(2, failing_module="libxcb.so.1")),       # excluded, trace only
        non_repairable(3, expl(2, failing_module="utils", subtype="mapping_unknown", scope="excluded"),
                       rec=r2record("utils", "mapping_unknown", "excluded")),
        one_round(4, trigger={"triggered": False, "reason": "same_as_original_error"}),  # no new error
    ]
    b = metrics.round2_explanation_schema_validity_rate(trace)
    assert b["processed"] == 3          # not 1 (only executed) - includes the two trace-only ones
    assert b["valid"] == 3
    assert b["explained_repair_eligible"] == 1
    assert b["explained_not_repair_eligible_trace_only"] == 2
    assert b["reclassified_new_errors"] == 3
    assert b["reclassified_without_explanation"] == 0


def test_failed_round2_explanations_stay_in_the_denominator():
    trace = [
        two_rounds(1, expl(2, status="failed", attempts=2, failing_module="pandas")),
        non_repairable(2, expl(2, status="failed", attempts=2, failing_module="libxcb.so.1")),
        two_rounds(3, expl(2, failing_module="numpy"), rec=r2record("numpy")),
    ]
    b = metrics.round2_explanation_schema_validity_rate(trace)
    assert b == {**b, "valid": 1, "failed": 2, "processed": 3, "rate": 1 / 3}


def test_round2_denominator_is_not_the_llm_reached_or_executed_row_population():
    # eligible+executed but the repair agent abstained before its LLM: the
    # explanation still counts once; the repair side counts 0 LLM responses.
    d = two_rounds(1, expl(2, failing_module="tf_keras"), r2_i4=i4(status="abstained", action="none", retrieval="mapping_unknown"),
                   r2_i5={"status": "skipped"}, rec=r2record("tf_keras"))
    b = metrics.round2_explanation_schema_validity_rate([d])
    assert b["processed"] == 1 and b["valid"] == 1
    assert metrics.grounded_proposal_rate_among_llm_invocations([d]) == 1.0  # only Round 1's real response


# =============================================================================
# No double counting of the duplicated trigger / round-entry representation
# =============================================================================

def test_executed_round2_explanation_counted_exactly_once():
    d = two_rounds(1, expl(2, failing_module="pandas"))
    assert d["rounds"][0]["round2_trigger"]["explanation"] is not d["rounds"][1]["explanation"]  # two copies
    assert d["rounds"][0]["round2_trigger"]["explanation"] == d["rounds"][1]["explanation"]
    assert metrics.round2_explanation_schema_validity_rate([d])["processed"] == 1
    assert metrics.explanation_call_counts([d])["round2_records"] == 1


def test_combined_does_not_double_count_the_duplicate_representation():
    trace = [two_rounds(1, expl(2)), two_rounds(2, expl(2)), non_repairable(3, expl(2))]
    c = metrics.combined_explanation_schema_validity_rate(trace)
    assert c["processed"] == 3 + 3   # 3 originals + 3 Round-2 records, not 3 + 5
    assert c["valid"] == 6


def test_round2_explanation_falls_back_to_round2_entry_only_if_trigger_lacks_one():
    d = two_rounds(1, expl(2, failing_module="pandas"))
    del d["rounds"][0]["round2_trigger"]["explanation"]
    got = metrics.round2_explanation(d)
    assert got is d["rounds"][1]["explanation"]
    assert metrics.round2_explanation_schema_validity_rate([d])["processed"] == 1


# =============================================================================
# Records versus LLM attempts (retries)
# =============================================================================

def test_retries_are_attempts_not_extra_records():
    trace = [
        one_round(1, r1_expl=expl(1, attempts=2, failing_module="orig")),          # retried once, succeeded
        two_rounds(2, expl(2, status="failed", attempts=2, failing_module="pandas")),  # retried, failed
    ]
    counts = metrics.explanation_call_counts(trace)
    assert counts["original_records"] == 2 and counts["round2_records"] == 1 and counts["total_records"] == 3
    assert counts["original_llm_attempts"] == 3 and counts["round2_llm_attempts"] == 2
    assert counts["total_llm_attempts"] == 5
    assert counts["records_with_retry"] == 2
    # validity rates are over records, never attempts
    assert metrics.combined_explanation_schema_validity_rate(trace)["processed"] == 3


# =============================================================================
# Repair metrics are untouched by explanation calls
# =============================================================================

def test_repair_invocation_counts_are_unchanged_by_round2_explanations():
    without = [old_style(1, triggered=True), old_style(2, triggered=False)]
    with_expl = [two_rounds(1, expl(2)), non_repairable(2, expl(2))]
    for trace in (without, with_expl):
        assert len(metrics._all_i4_results(trace)) == 3        # R1 x2 + R2 x1 - explanations never appear here
        assert len(metrics._llm_repair_responses(metrics._all_i4_results(trace))) == 3
    assert metrics.overall_grounded_proposal_coverage_rate(with_expl) == metrics.overall_grounded_proposal_coverage_rate(without)
    assert metrics.proposal_validity_rate(with_expl) == metrics.proposal_validity_rate(without)


def test_compute_all_metrics_keeps_explanation_block_separate_from_repair_blocks():
    trace = [two_rounds(1, expl(2)), non_repairable(2, expl(2))]
    report = metrics.compute_all_metrics(trace, "run-1", expected_record_count=2)
    assert "explanation" in report
    assert report["secondary"]["explanation_schema_validity"] == {"valid": 2, "processed": 2, "rate": 1.0}
    assert report["explanation"]["round2_explanation_schema_validity"]["processed"] == 2
    assert report["explanation"]["combined_explanation_schema_validity"]["processed"] == 4
    # repair-side figures: 1 notebook round-2 eligible, 1 attempted; 3 repair-agent invocations
    assert report["round2_summary"]["eligible"] == 1 and report["round2_summary"]["attempted"] == 1
    assert report["secondary"]["overall_grounded_proposal_coverage_rate"] == 1.0


# =============================================================================
# Hard cap: nothing beyond Round 2 is counted
# =============================================================================

def test_no_round3_explanation_is_counted_or_tolerated():
    d = two_rounds(1, expl(2))
    d["rounds"][1]["round2_trigger"] = {"triggered": True, "round2_record": r2record("numpy"),
                                        "explanation": expl(3, failing_module="numpy")}
    # metrics read only rounds[0].round2_trigger, so a stray "third" explanation is invisible ...
    assert metrics.round2_explanation_schema_validity_rate([d])["processed"] == 1
    # ... and the integrity check rejects the structure outright
    assert ver.check_no_round3_explanation([d]).passed is False


# =============================================================================
# Backward compatibility with pre-Round-2-explanation traces
# =============================================================================

def test_old_traces_yield_zero_round2_explanations_and_unchanged_original_metric():
    trace = [old_style(1, "success"), old_style(2, "failed"), old_style(3, "success", triggered=False)]
    assert metrics.explanation_schema_validity_rate(trace) == {"valid": 2, "processed": 3, "rate": 2 / 3}
    b = metrics.round2_explanation_schema_validity_rate(trace)
    assert b["processed"] == 0 and b["rate"] is None
    assert b["reclassified_new_errors"] == 3 and b["reclassified_without_explanation"] == 3
    assert metrics.combined_explanation_schema_validity_rate(trace) == metrics.explanation_schema_validity_rate(trace) | {"failed": 1}
    counts = metrics.explanation_call_counts(trace)
    assert counts["round2_records"] == 0 and counts["round2_llm_attempts"] == 0


def test_new_integrity_checks_pass_on_old_traces():
    trace = [old_style(1), old_style(2, triggered=False)]
    rows = [{"notebook_execution_id": 1, "round": 1, "run_id": "run-1"}, {"notebook_execution_id": 1, "round": 2, "run_id": "run-1"},
            {"notebook_execution_id": 2, "round": 1, "run_id": "run-1"}]
    for check in (
        ver.check_round2_explanations_well_formed(trace),
        ver.check_round2_entry_explanation_matches_trigger(trace),
        ver.check_no_round3_explanation(trace),
        ver.check_top_level_explanation_is_round1(trace),
        ver.check_non_repairable_round2_explanations_are_trace_only(trace, rows),
        ver.check_round2_explanation_failure_did_not_block_repair(trace),
        ver.check_single_run_id("run-1", trace, rows),
    ):
        assert check.passed, check.name


# =============================================================================
# Integrity checks on the new structure
# =============================================================================

def test_well_formed_check_rejects_wrong_round_tag_and_mismatched_input():
    good = two_rounds(1, expl(2, failing_module="pandas"))
    assert ver.check_round2_explanations_well_formed([good]).passed
    wrong_tag = two_rounds(2, expl(1, failing_module="pandas"))
    assert ver.check_round2_explanations_well_formed([wrong_tag]).passed is False
    stale_input = two_rounds(3, expl(2, failing_module="orig", error_message="No module named 'orig'"))
    assert ver.check_round2_explanations_well_formed([stale_input]).passed is False


def test_entry_matches_trigger_check_rejects_divergent_copies():
    d = two_rounds(1, expl(2, failing_module="pandas"))
    assert ver.check_round2_entry_explanation_matches_trigger([d]).passed
    d["rounds"][1]["explanation"] = expl(2, failing_module="something-else")
    assert ver.check_round2_entry_explanation_matches_trigger([d]).passed is False


def test_top_level_is_round1_check():
    ok = two_rounds(1, expl(2))
    assert ver.check_top_level_explanation_is_round1([ok]).passed
    bad = two_rounds(2, expl(2))
    bad["explanation"] = bad["rounds"][1]["explanation"]  # Round-2 explanation leaked to the top level
    assert ver.check_top_level_explanation_is_round1([bad]).passed is False


def test_non_repairable_check_rejects_fake_round2_row_or_entry():
    d = non_repairable(1, expl(2, failing_module="libxcb.so.1"))
    assert ver.check_non_repairable_round2_explanations_are_trace_only([d], [{"notebook_execution_id": 1, "round": 1}]).passed
    fake_row = [{"notebook_execution_id": 1, "round": 1}, {"notebook_execution_id": 1, "round": 2}]
    assert ver.check_non_repairable_round2_explanations_are_trace_only([d], fake_row).passed is False
    d["rounds"].append({"round": 2, "status": "completed"})
    assert ver.check_non_repairable_round2_explanations_are_trace_only([d], [{"notebook_execution_id": 1, "round": 1}]).passed is False


def test_failed_round2_explanation_must_not_have_blocked_round2():
    ok = two_rounds(1, expl(2, status="failed", attempts=2))
    assert ver.check_round2_explanation_failure_did_not_block_repair([ok]).passed
    blocked = two_rounds(2, expl(2, status="failed", attempts=2))
    blocked["rounds"] = blocked["rounds"][:1]  # trigger fired, explanation failed, but no Round-2 entry
    assert ver.check_round2_explanation_failure_did_not_block_repair([blocked]).passed is False
    # the existing reconciliation and trigger checks are unaffected by a failed explanation
    assert ver.check_round2_only_after_valid_trigger([ok]).passed


def test_single_run_id_check_includes_round2_explanations():
    d = two_rounds(1, expl(2, run_id="stray-run"))
    rows = [{"notebook_execution_id": 1, "round": 1, "run_id": "run-1"}, {"notebook_execution_id": 1, "round": 2, "run_id": "run-1"}]
    assert ver.check_single_run_id("run-1", [d], rows).passed is False
    d2 = two_rounds(1, expl(2, run_id="run-1"))
    assert ver.check_single_run_id("run-1", [d2], rows).passed


# =============================================================================
# Manifest provenance
# =============================================================================

def _repo(tmp_path, with_round2=True):
    (tmp_path / "config").mkdir()
    for name in ["package_mapping.yaml", "rag_repair.yaml", "llm_explainer.yaml", "fix_applicator.yaml"]:
        (tmp_path / "config" / name).write_text(f"# {name}", encoding="utf-8")
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "p.txt").write_text("prompt", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    body = "def explain_round_record(record):\n    pass\n" if with_round2 else "def process_record():\n    pass\n"
    (tmp_path / "scripts" / "run_pipeline.py").write_text(body, encoding="utf-8")
    i2 = tmp_path / "i2.jsonl"
    i2.write_text("\n".join(json.dumps({"notebook_execution_id": i, "split": "dev"}) for i in range(3)) + "\n", encoding="utf-8")
    return tmp_path


def _manifest(root):
    return em.build_manifest(
        run_id="t", split="dev", max_rounds=2, model="gemma2:9b", prompt_strategy="few_shot",
        explanation_prompt_version="i3_prompt_v1", repair_prompt_version="i4_prompt_v1",
        database_path="db.sqlite", output_dir="out", explainer_config_path="config/llm_explainer.yaml",
        repair_config_path="config/rag_repair.yaml", fix_config_path="config/fix_applicator.yaml",
        repository_metadata_db_path=None, i2_path="i2.jsonl", root=root,
    )


def test_manifest_records_code_hashes_features_and_tree_state(tmp_path):
    m = _manifest(_repo(tmp_path))
    assert m["code_hashes"]["run_pipeline"] is not None
    assert m["orchestrator_features"] == {"round2_explanation": True}
    assert "git_working_tree_dirty" in m
    # config_hashes keys are unchanged, so frozen manifests still compare key-for-key
    assert set(m["config_hashes"]) == set(em.DEFAULT_HASHED_PATHS)


def test_manifest_feature_flag_is_derived_from_code_not_asserted(tmp_path):
    m = _manifest(_repo(tmp_path, with_round2=False))
    assert m["orchestrator_features"] == {"round2_explanation": False}


def test_diff_manifests_compares_code_hashes_only_when_both_present():
    old = {"split": "dev", "config_hashes": {"a": "1"}}
    new = {"split": "dev", "config_hashes": {"a": "1"}, "code_hashes": {"run_pipeline": "x"}}
    assert em.diff_manifests(old, new) == []            # old manifest predates code hashing
    other = {"split": "dev", "config_hashes": {"a": "1"}, "code_hashes": {"run_pipeline": "y"}}
    assert any(m.startswith("code_hashes") for m in em.diff_manifests(new, other))


def test_hash_consistency_check_ignores_code_hashes_when_manifest_lacks_them(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    m = _manifest(root)
    old_style_manifest = {k: v for k, v in m.items() if k != "code_hashes"}
    assert ver.check_manifest_hash_consistency(old_style_manifest, root).passed
    # but a manifest that recorded code hashes is checked against the current code
    assert ver.check_manifest_hash_consistency(m, root).passed
    (root / "scripts" / "run_pipeline.py").write_text("# changed after the run\n", encoding="utf-8")
    result = ver.check_manifest_hash_consistency(m, root)
    assert result.passed is False and "code:run_pipeline" in result.detail


# =============================================================================
# Summary outputs
# =============================================================================

def test_table_9_reports_three_explanation_views_with_explicit_denominators(tmp_path):
    trace = [
        two_rounds(1, expl(2, failing_module="pandas")),
        non_repairable(2, expl(2, status="failed", attempts=2, failing_module="libxcb.so.1")),
        one_round(3, trigger={"triggered": False, "reason": "same_as_original_error"}),
    ]
    report = er.build_report(trace, "run-1", expected_record_count=3)
    er.write_outputs(report, tmp_path / "summary", tmp_path / "tables")

    table = {r["metric"]: r["value"] for r in csv.DictReader((tmp_path / "tables" / "table_9_explanation_schema_validity.csv").open(encoding="utf-8"))}
    assert table["original_failures_schema_valid"] == "3/3"
    assert table["round2_newly_exposed_failures_schema_valid"] == "1/2"
    assert table["combined_schema_valid"] == "4/5"
    assert table["round2_explained_not_repair_eligible_trace_only"] == "1"
    assert table["round2_llm_attempts_incl_retries"] == "3"
    assert "human" in table["note"].lower() and "original-failure" in table["note"]

    flat = {r["metric"]: r["value"] for r in csv.DictReader((tmp_path / "summary" / "evaluation_summary.csv").open(encoding="utf-8"))}
    assert flat["explanation.round2_explanation_schema_validity.processed"] == "2"
    assert flat["explanation.original_explanation_schema_validity.processed"] == "3"
    # the legacy row keeps its historical name and meaning in table_8
    t8 = {r["metric"]: r["value"] for r in csv.DictReader((tmp_path / "tables" / "table_8_pipeline_resultlogger_integrity.csv").open(encoding="utf-8"))}
    assert t8["explanation_schema_validity_rate"] == "1.0"


def test_table_9_never_hardcodes_counts(tmp_path):
    a = [two_rounds(i, expl(2)) for i in range(4)]
    b = [two_rounds(i, expl(2)) for i in range(2)] + [non_repairable(9, expl(2))]
    for label, trace in (("a", a), ("b", b)):
        er.write_outputs(er.build_report(trace, "r", expected_record_count=len(trace)), tmp_path / label / "s", tmp_path / label / "t")
    ta = {r["metric"]: r["value"] for r in csv.DictReader((tmp_path / "a" / "t" / "table_9_explanation_schema_validity.csv").open(encoding="utf-8"))}
    tb = {r["metric"]: r["value"] for r in csv.DictReader((tmp_path / "b" / "t" / "table_9_explanation_schema_validity.csv").open(encoding="utf-8"))}
    assert ta["round2_explanation_records"] == "4" and tb["round2_explanation_records"] == "3"
