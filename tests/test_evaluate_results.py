import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_results as er


def make_trace_line(notebook_execution_id, outcome="fixed", subtype="missing_package"):
    return {
        "notebook_execution_id": notebook_execution_id,
        "explanation_status": "success",
        "rounds": [
            {
                "round": 1,
                "status": "completed",
                "i4_result": {
                    "status": "success",
                    "eligibility": {"decision": "usable"},
                    "input": {"refined_subtype": subtype, "failing_module": "sklearn"},
                    "final_action": "install",
                    "schema_validation": {"valid": True},
                    "grounding_validation": {"valid": True},
                },
                "i5_result": {"status": "completed", "outcome": outcome, "same_as_original_error": False},
                "round2_trigger": {"triggered": False, "reason": "round1_outcome_not_still_failing"},
            }
        ],
    }


def test_build_report_marks_classifier_and_pypi_scoring_unavailable_when_no_ground_truth():
    trace = [make_trace_line(1)]
    report = er.build_report(trace, "run-1", expected_record_count=1)
    assert report["classifier_scoring"]["available"] is False
    assert report["pypi_resolution_scoring"]["available"] is False


def test_build_report_includes_classifier_scoring_once_labels_are_filled():
    trace = [make_trace_line(1)]
    classifier_rows = [
        {
            "predicted_scope_status": "usable",
            "manual_scope_status": "usable",
            "predicted_subtype": "missing_package",
            "manual_subtype": "missing_package",
            "predicted_failing_module": "sklearn",
            "manual_failing_module": "sklearn",
        }
    ]
    report = er.build_report(trace, "run-1", expected_record_count=1, classifier_rows=classifier_rows)
    assert "available" not in report["classifier_scoring"] or report["classifier_scoring"].get("available") is not False
    assert report["classifier_scoring"]["scope_status"]["n_scored"] == 1


def test_any_manual_labels_filled_detects_blank_rows():
    rows = [{"manual_scope_status": ""}, {"manual_scope_status": None}]
    assert er.any_manual_labels_filled(rows, ["manual_scope_status"]) is False


def test_any_manual_labels_filled_detects_at_least_one_filled():
    rows = [{"manual_scope_status": ""}, {"manual_scope_status": "usable"}]
    assert er.any_manual_labels_filled(rows, ["manual_scope_status"]) is True


def test_write_outputs_produces_all_expected_files(tmp_path):
    trace = [make_trace_line(1, outcome="fixed"), make_trace_line(2, outcome="still_failing")]
    report = er.build_report(trace, "run-1", expected_record_count=2)

    summary_dir = tmp_path / "summary"
    tables_dir = tmp_path / "tables"
    er.write_outputs(report, summary_dir, tables_dir)

    assert (summary_dir / "evaluation_summary.json").is_file()
    assert (summary_dir / "evaluation_summary.csv").is_file()
    assert (summary_dir / "per_notebook_comparison.csv").is_file()
    assert (summary_dir / "failure_breakdown.csv").is_file()
    assert (summary_dir / "subtype_breakdown.csv").is_file()

    for i in range(1, 9):
        assert list(tables_dir.glob(f"table_{i}_*.csv")), f"missing table {i}"


def test_write_outputs_json_is_valid_and_round_trips_key_metrics(tmp_path):
    trace = [make_trace_line(1, outcome="fixed")]
    report = er.build_report(trace, "run-1", expected_record_count=1)
    summary_dir = tmp_path / "summary"
    er.write_outputs(report, summary_dir, tmp_path / "tables")

    loaded = json.loads((summary_dir / "evaluation_summary.json").read_text(encoding="utf-8"))
    assert loaded["primary"]["system_level_repair_success_rate"] == 1.0


def test_write_outputs_per_notebook_csv_has_expected_columns(tmp_path):
    trace = [make_trace_line(1, outcome="fixed")]
    report = er.build_report(trace, "run-1", expected_record_count=1)
    summary_dir = tmp_path / "summary"
    er.write_outputs(report, summary_dir, tmp_path / "tables")

    with (summary_dir / "per_notebook_comparison.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["notebook_execution_id"] == "1"
    assert rows[0]["final_category"] == "fixed"


def make_abstained_trace_line(notebook_execution_id):
    """A Round-1 abstention: retrieval never found a package mapping, so
    the repair agent declined before any LLM call - schema_validation is
    None (no LLM invocation), distinguishing this from a malformed LLM
    response."""
    return {
        "notebook_execution_id": notebook_execution_id,
        "explanation_status": "success",
        "rounds": [
            {
                "round": 1,
                "status": "completed",
                "i4_result": {
                    "status": "abstained",
                    "eligibility": {"decision": "usable"},
                    "input": {"refined_subtype": "missing_package", "failing_module": "some_obscure_pkg"},
                    "final_action": "none",
                    "retrieval_result": {"status": "mapping_unknown"},
                    "schema_validation": None,
                    "grounding_validation": None,
                },
                "i5_result": None,
                "round2_trigger": {"triggered": False, "reason": "round1_outcome_not_still_failing"},
            }
        ],
    }


def _read_kv_table(path):
    with path.open(encoding="utf-8", newline="") as f:
        return {row["metric"]: row["value"] for row in csv.DictReader(f)}


def test_table_1_reports_round1_and_final_state_abstention_rates_separately(tmp_path):
    # 1 fixed, 1 Round-1 abstention (mapping_unknown) -> round1 == final-state here (no Round-2 involved).
    trace = [make_trace_line(1, outcome="fixed"), make_abstained_trace_line(2)]
    report = er.build_report(trace, "run-1", expected_record_count=2)
    er.write_outputs(report, tmp_path / "summary", tmp_path / "tables")

    table_1 = _read_kv_table(tmp_path / "tables" / "table_1_overall_repair_results.csv")
    assert "abstention_rate" not in table_1  # old ambiguous name must be gone
    assert float(table_1["round1_abstention_rate"]) == 0.5
    assert float(table_1["final_state_abstention_rate"]) == 0.5


def test_table_5_breaks_down_abstained_by_round(tmp_path):
    trace = [
        make_trace_line(1, outcome="fixed"),
        make_abstained_trace_line(2),
        make_abstained_trace_line(3),
    ]
    report = er.build_report(trace, "run-1", expected_record_count=3)
    er.write_outputs(report, tmp_path / "summary", tmp_path / "tables")

    with (tmp_path / "tables" / "table_5_failure_abstention_infra_breakdown.csv").open(
        encoding="utf-8", newline=""
    ) as f:
        rows = {row["category"]: int(row["count"]) for row in csv.DictReader(f)}

    assert rows["abstained"] == 2
    assert rows["abstained_from_round1"] == 2
    assert rows["abstained_from_round2"] == 0
    assert rows["abstained"] == rows["abstained_from_round1"] + rows["abstained_from_round2"]


def test_table_6_labels_match_their_denominators(tmp_path):
    trace = [make_trace_line(1, outcome="fixed"), make_abstained_trace_line(2)]
    report = er.build_report(trace, "run-1", expected_record_count=2)
    er.write_outputs(report, tmp_path / "summary", tmp_path / "tables")

    table_6 = _read_kv_table(tmp_path / "tables" / "table_6_pypi_rag_proposal_quality.csv")
    assert "end_to_end_valid_grounded_proposal_rate" not in table_6  # old misleading name must be gone
    # Only 1 of 2 i4 attempts ever reached the LLM (the abstained one never did) -
    # LLM-conditional rate is 1/1, but overall coverage is only 1/2.
    assert float(table_6["grounded_proposal_rate_among_llm_invocations"]) == 1.0
    assert float(table_6["overall_grounded_proposal_coverage_rate"]) == 0.5


def test_write_outputs_never_hardcodes_numbers_reflects_actual_counts(tmp_path):
    """Two different reports (different fixed counts) must produce
    different table contents - proof the tables are generated from data,
    not hardcoded."""
    trace_a = [make_trace_line(1, outcome="fixed")]
    trace_b = [make_trace_line(1, outcome="still_failing")]
    report_a = er.build_report(trace_a, "run-a", expected_record_count=1)
    report_b = er.build_report(trace_b, "run-b", expected_record_count=1)

    er.write_outputs(report_a, tmp_path / "a" / "summary", tmp_path / "a" / "tables")
    er.write_outputs(report_b, tmp_path / "b" / "summary", tmp_path / "b" / "tables")

    content_a = (tmp_path / "a" / "tables" / "table_1_overall_repair_results.csv").read_text(encoding="utf-8")
    content_b = (tmp_path / "b" / "tables" / "table_1_overall_repair_results.csv").read_text(encoding="utf-8")
    assert content_a != content_b
