#!/usr/bin/env python3

"""EvaluateResults (i8) CLI: compute the frozen metrics
(scripts/evaluation_metrics.py) from one evaluation run's manifest + raw
trace, and write reproducible JSON/CSV summaries and thesis-ready tables.

Every number in every output file is computed from the run's own trace/
manifest/ground-truth files at report-generation time - nothing here is a
hardcoded literal. Classifier and PyPI distribution-resolution scoring
sections are included only when the corresponding ground-truth CSV is
supplied AND has at least one filled-in manual label; otherwise those
sections/tables are written with an explicit "not yet available" marker
rather than silently omitted or fabricated.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import evaluation_manifest as em  # noqa: E402
import evaluation_metrics as metrics  # noqa: E402
import manual_ground_truth_scoring as gts  # noqa: E402


# --- ground-truth loading (optional) ---------------------------------------

def load_ground_truth_csv(path: Optional[Path]) -> Optional[List[Dict[str, Any]]]:
    if path is None or not path.is_file():
        return None
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def any_manual_labels_filled(rows: Optional[List[Dict[str, Any]]], fields: List[str]) -> bool:
    if not rows:
        return False
    return any(
        any(row.get(field) is not None and str(row.get(field)).strip() for field in fields) for row in rows
    )


# --- CSV writers -------------------------------------------------------------

def write_kv_csv(rows: List[Dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "value"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_dict_rows_csv(rows: List[Dict[str, Any]], fields: List[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


# --- report assembly ---------------------------------------------------------

def build_report(
    trace: List[Dict[str, Any]],
    run_id: str,
    expected_record_count: int,
    classifier_rows: Optional[List[Dict[str, Any]]] = None,
    pypi_rows: Optional[List[Dict[str, Any]]] = None,
    classifier_population_weights: Optional[Dict[str, float]] = None,
    classifier_treat_as_full_population: bool = False,
) -> Dict[str, Any]:
    report = metrics.compute_all_metrics(trace, run_id, expected_record_count)

    if any_manual_labels_filled(classifier_rows, ["manual_scope_status", "manual_subtype", "manual_failing_module"]):
        report["classifier_scoring"] = gts.score_classifier_sample(
            classifier_rows,
            population_weights=classifier_population_weights,
            treat_as_full_population=classifier_treat_as_full_population,
        )
    else:
        report["classifier_scoring"] = {"available": False, "reason": "no manual ground-truth labels filled in yet"}

    if any_manual_labels_filled(pypi_rows, ["manual_correct_distribution"]):
        report["pypi_resolution_scoring"] = gts.score_distribution_resolution_sample(pypi_rows)
    else:
        report["pypi_resolution_scoring"] = {"available": False, "reason": "no manual ground-truth labels filled in yet"}

    return report


def write_outputs(report: Dict[str, Any], summary_dir: Path, tables_dir: Path) -> None:
    summary_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    comparison_records = report["comparison_records"]

    # --- JSON summary (full report, including per-notebook records) ---
    (summary_dir / "evaluation_summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )

    # --- flattened metric summary CSV ---
    flat_rows = [{"metric": f"primary.{k}", "value": v} for k, v in report["primary"].items()]
    flat_rows += [
        {"metric": f"secondary.{k}", "value": v}
        for k, v in report["secondary"].items()
        if k not in {"subtype_level_repair_success"}
    ]
    flat_rows += [{"metric": f"round2_summary.{k}", "value": v} for k, v in report["round2_summary"].items()]
    # Explanation-component block (metrics A/B/C + record/attempt counts),
    # flattened one level so each rate and count is its own row and a
    # later model comparison can read them without parsing dict strings.
    for block_name, block in report.get("explanation", {}).items():
        if isinstance(block, dict):
            flat_rows += [{"metric": f"explanation.{block_name}.{k}", "value": v} for k, v in block.items()]
        else:
            flat_rows.append({"metric": f"explanation.{block_name}", "value": block})
    write_kv_csv(flat_rows, summary_dir / "evaluation_summary.csv")

    # --- per-notebook comparison CSV ---
    comparison_fields = [
        "notebook_execution_id",
        "subtype",
        "failing_module",
        "round1_action",
        "round1_outcome",
        "round1_category",
        "round2_eligible",
        "round2_attempted",
        "round2_action",
        "round2_outcome",
        "round2_category",
        "final_category",
        "additional_fix_from_round2",
        "targeted_error_resolved_round1",
        "targeted_error_resolved_round2",
        "infrastructure_failure",
        "run_id",
    ]
    write_dict_rows_csv(comparison_records, comparison_fields, summary_dir / "per_notebook_comparison.csv")

    # --- failure breakdown CSV ---
    failure_rows = [{"category": k, "count": v} for k, v in report["failure_breakdown"].items()]
    write_dict_rows_csv(failure_rows, ["category", "count"], summary_dir / "failure_breakdown.csv")

    # --- subtype breakdown CSV ---
    subtype_rows = [
        {"subtype": subtype, **values} for subtype, values in report["secondary"]["subtype_level_repair_success"].items()
    ]
    write_dict_rows_csv(subtype_rows, ["subtype", "eligible", "fixed", "rate"], summary_dir / "subtype_breakdown.csv")

    # --- thesis-ready tables ---
    write_kv_csv(
        [
            {"metric": "system_level_repair_success_rate", "value": report["primary"]["system_level_repair_success_rate"]},
            {"metric": "round1_repair_success_rate", "value": report["primary"]["round1_repair_success_rate"]},
            {"metric": "final_repair_success_rate", "value": report["primary"]["final_repair_success_rate"]},
            {"metric": "conditional_repair_success_rate", "value": report["secondary"]["conditional_repair_success_rate"]},
            {"metric": "method_only_success_rate", "value": report["secondary"]["method_only_success_rate"]},
            {"metric": "infrastructure_failure_rate", "value": report["secondary"]["infrastructure_failure_rate"]},
            {"metric": "round1_abstention_rate", "value": report["secondary"]["round1_abstention_rate"]},
            {"metric": "final_state_abstention_rate", "value": report["secondary"]["final_state_abstention_rate"]},
            {
                "metric": "note",
                "value": (
                    "round1_abstention_rate counts only notebooks the repair agent declined on in "
                    "Round 1. final_state_abstention_rate additionally counts notebooks that had a "
                    "real Round-1 attempt (still_failing), became Round-2-eligible, and were declined "
                    "again in Round 2 - see table_5's abstained_from_round1/abstained_from_round2 rows "
                    "and table_2's round2_abstained row for that breakdown."
                ),
            },
        ],
        tables_dir / "table_1_overall_repair_results.csv",
    )

    write_kv_csv(
        [
            {"metric": "round1_repair_success_rate", "value": report["primary"]["round1_repair_success_rate"]},
            {"metric": "final_repair_success_rate_up_to_round2", "value": report["primary"]["final_repair_success_rate"]},
            {"metric": "round2_eligible", "value": report["round2_summary"]["eligible"]},
            {"metric": "round2_proposal_generated", "value": report["round2_summary"]["proposal_generated"]},
            {"metric": "round2_abstained", "value": report["round2_summary"]["abstained"]},
            {"metric": "round2_attempted", "value": report["round2_summary"]["attempted"]},
            {"metric": "round2_fixed", "value": report["round2_summary"]["fixed"]},
            {"metric": "round2_still_failing", "value": report["round2_summary"]["still_failing"]},
            {"metric": "round2_infrastructure_failure", "value": report["round2_summary"]["infrastructure_failure"]},
            {"metric": "round2_method_failure", "value": report["round2_summary"]["method_failure"]},
            {"metric": "round2_non_attempt_reasons", "value": report["round2_summary"]["non_attempt_reasons"]},
            {"metric": "additional_notebooks_fixed_by_round2", "value": report["primary"]["additional_notebooks_fixed_by_round2"]},
            {"metric": "absolute_pp_improvement_from_round2", "value": report["primary"]["absolute_pp_improvement_from_round2"]},
            {
                "metric": "note",
                "value": (
                    "A Round-2-eligible notebook either gets a real proposal from the repair agent "
                    "(round2_proposal_generated, which FixApplicator then always attempts, giving "
                    "round2_attempted) or the agent declines again (round2_abstained - see "
                    "round2_non_attempt_reasons for the exact cause, e.g. mapping_unknown); a Round-2 "
                    "orchestrator/component fault instead of either is possible in principle and would "
                    "show up in round2_infrastructure_failure without being in round2_proposal_generated. "
                    "round2_fixed + round2_still_failing + round2_infrastructure_failure + "
                    "round2_method_failure sum to round2_attempted's real-attempt outcomes."
                ),
            },
        ],
        tables_dir / "table_2_round1_vs_round2.csv",
    )

    full_fixed = sum(1 for r in comparison_records if r["final_category"] == "fixed")
    write_kv_csv(
        [
            {"metric": "notebooks_fully_fixed", "value": full_fixed},
            {"metric": "targeted_error_resolution_rate_attempt_level", "value": report["secondary"]["targeted_error_resolution_rate"]},
            {"metric": "system_level_repair_success_rate", "value": report["primary"]["system_level_repair_success_rate"]},
        ],
        tables_dir / "table_3_targeted_error_resolution_vs_full_repair.csv",
    )

    write_dict_rows_csv(subtype_rows, ["subtype", "eligible", "fixed", "rate"], tables_dir / "table_4_subtype_breakdown.csv")

    # table_5's "abstained" row is the FINAL-STATE count (post-Round-2):
    # every notebook whose last-classified round - Round 2's if it ran,
    # else Round 1's - was ABSTAINED. It is NOT the same population as
    # table_1/table_2's Round-1-only abstention figures, so this table adds
    # the two disjoint sub-counts it is made of directly beneath it.
    table_5_rows = list(failure_rows) + [
        {"category": "abstained_from_round1", "count": report["secondary"]["round1_abstention_count"]},
        {"category": "abstained_from_round2", "count": report["secondary"]["round2_abstention_count"]},
    ]
    write_dict_rows_csv(table_5_rows, ["category", "count"], tables_dir / "table_5_failure_abstention_infra_breakdown.csv")

    write_kv_csv(
        [
            {"metric": "proposal_validity_rate", "value": report["secondary"]["proposal_validity_rate"]},
            {"metric": "grounding_pass_rate", "value": report["secondary"]["grounding_pass_rate"]},
            {
                "metric": "grounded_proposal_rate_among_llm_invocations",
                "value": report["secondary"]["grounded_proposal_rate_among_llm_invocations"],
            },
            {
                "metric": "overall_grounded_proposal_coverage_rate",
                "value": report["secondary"]["overall_grounded_proposal_coverage_rate"],
            },
            {
                "metric": "distribution_resolution_accuracy_on_manually_resolvable_diagnostic_sample",
                "value": report["pypi_resolution_scoring"].get("distribution_resolution_accuracy")
                if report["pypi_resolution_scoring"].get("available", True)
                else "not yet available - manual ground truth not filled in",
            },
            {
                "metric": "note",
                "value": (
                    "Denominator is the manually resolvable rows in the frozen diagnostic sample "
                    "(known-mapped + frequent-unmapped + ambiguous import names), not a random or "
                    "population-representative sample - do not report as population-wide PyPI "
                    "resolution accuracy."
                ),
            },
            {
                "metric": "note_proposal_metrics",
                "value": (
                    "proposal_validity_rate and grounding_pass_rate are conditioned on LLM repair "
                    "responses only (i4 attempts where retrieval resolved a candidate and the LLM was "
                    "actually invoked), and so is grounded_proposal_rate_among_llm_invocations (formerly "
                    "named end_to_end_valid_grounded_proposal_rate - renamed because that name implied "
                    "full coverage while silently excluding every pre-LLM abstention). "
                    "overall_grounded_proposal_coverage_rate is the true full-population figure: grounded "
                    "proposals divided by every repair-agent invocation across both rounds, abstentions "
                    "included. A pipeline that abstains before the LLM on most records can still show "
                    "1.0 on the LLM-conditional metrics while overall_grounded_proposal_coverage_rate "
                    "stays low - both numbers are correct, they answer different questions."
                ),
            },
        ],
        tables_dir / "table_6_pypi_rag_proposal_quality.csv",
    )

    classifier_scoring = report.get("classifier_scoring", {})
    if classifier_scoring.get("available") is False:
        write_kv_csv(
            [{"metric": "status", "value": "not yet available - manual ground truth not filled in"}],
            tables_dir / "table_7_classifier_performance.csv",
        )
    else:
        n_scored = classifier_scoring["scope_status"]["n_scored"]
        write_kv_csv(
            [
                {
                    "metric": f"scope_status_accuracy_on_{n_scored}_record_manual_validation_sample",
                    "value": classifier_scoring["scope_status"]["metrics"]["accuracy"],
                },
                {
                    "metric": f"scope_status_precision_on_{n_scored}_record_manual_validation_sample",
                    "value": classifier_scoring["scope_status"]["metrics"]["precision"],
                },
                {
                    "metric": f"scope_status_recall_on_{n_scored}_record_manual_validation_sample",
                    "value": classifier_scoring["scope_status"]["metrics"]["recall"],
                },
                {
                    "metric": f"scope_status_f1_on_{n_scored}_record_manual_validation_sample",
                    "value": classifier_scoring["scope_status"]["metrics"]["f1"],
                },
                {
                    "metric": f"subtype_accuracy_on_{n_scored}_record_manual_validation_sample",
                    "value": classifier_scoring["subtype"]["naive_overall_accuracy"],
                },
                {
                    "metric": f"failing_module_exact_match_accuracy_on_{n_scored}_record_manual_validation_sample",
                    "value": classifier_scoring["failing_module"]["exact_match_accuracy"],
                },
                {
                    "metric": "population_wide_accuracy_estimate",
                    "value": (
                        "not reported - the validation sample deliberately oversamples rare subtypes, "
                        "and no statistically valid design-based population estimator is implemented; "
                        "see docs/i8-evaluation-methodology.md"
                    ),
                },
            ],
            tables_dir / "table_7_classifier_performance.csv",
        )

    write_kv_csv(
        [
            {"metric": "expected_record_count", "value": report["expected_record_count"]},
            {"metric": "actual_record_count", "value": report["actual_record_count"]},
            {
                # Kept under its historical name for continuity with the
                # frozen I8/I9 table_8 files. It is metric A (original-
                # failure explanations / notebooks processed) - see
                # table_9 for the Round-2 and combined views.
                "metric": "explanation_schema_validity_rate",
                "value": report["secondary"]["explanation_schema_validity"]["rate"],
            },
            {
                "metric": "note",
                "value": (
                    "explanation_schema_validity_rate is the ORIGINAL-failure explanation rate "
                    "(metric A, notebook-level denominator); Round-2 and combined explanation "
                    "validity are in table_9_explanation_schema_validity.csv. Run "
                    "scripts/validate_evaluation_results.py for full ResultLogger/KG integrity checks."
                ),
            },
        ],
        tables_dir / "table_8_pipeline_resultlogger_integrity.csv",
    )

    # --- table 9: explanation component, kept apart from every repair table ---
    expl = report.get("explanation", {})
    original = expl.get("original_explanation_schema_validity", {})
    round2 = expl.get("round2_explanation_schema_validity", {})
    combined = expl.get("combined_explanation_schema_validity", {})
    counts = expl.get("call_counts", {})

    def _frac(block: Dict[str, Any]) -> str:
        if not block or block.get("processed") is None:
            return "n/a"
        return f"{block.get('valid')}/{block.get('processed')}"

    write_kv_csv(
        [
            {"metric": "original_failures_schema_valid", "value": _frac(original)},
            {"metric": "original_explanation_schema_validity_rate", "value": original.get("rate")},
            {"metric": "round2_newly_exposed_failures_schema_valid", "value": _frac(round2)},
            {"metric": "round2_explanation_schema_validity_rate", "value": round2.get("rate")},
            {"metric": "combined_schema_valid", "value": _frac(combined)},
            {"metric": "combined_explanation_schema_validity_rate", "value": combined.get("rate")},
            {"metric": "original_explanation_records", "value": counts.get("original_records")},
            {"metric": "round2_explanation_records", "value": counts.get("round2_records")},
            {"metric": "total_explanation_records", "value": counts.get("total_records")},
            {"metric": "original_valid", "value": original.get("valid")},
            {"metric": "original_failed", "value": original.get("failed")},
            {"metric": "round2_valid", "value": round2.get("valid")},
            {"metric": "round2_failed", "value": round2.get("failed")},
            {"metric": "combined_valid", "value": combined.get("valid")},
            {"metric": "combined_failed", "value": combined.get("failed")},
            {"metric": "round2_reclassified_new_errors", "value": round2.get("reclassified_new_errors")},
            {"metric": "round2_reclassified_without_explanation", "value": round2.get("reclassified_without_explanation")},
            {"metric": "round2_explained_repair_eligible", "value": round2.get("explained_repair_eligible")},
            {
                "metric": "round2_explained_not_repair_eligible_trace_only",
                "value": round2.get("explained_not_repair_eligible_trace_only"),
            },
            {"metric": "original_llm_attempts_incl_retries", "value": counts.get("original_llm_attempts")},
            {"metric": "round2_llm_attempts_incl_retries", "value": counts.get("round2_llm_attempts")},
            {"metric": "total_llm_attempts_incl_retries", "value": counts.get("total_llm_attempts")},
            {"metric": "records_with_retry", "value": counts.get("records_with_retry")},
            {
                "metric": "note",
                "value": (
                    "Record-level schema validity, one record per encountered dependency error. "
                    "Denominators: original = notebooks processed in this run (comparable with "
                    "pre-Round-2-explanation runs); round2 = newly reclassified Round-2 errors that "
                    "received an explanation, INCLUDING non-repairable ones that exist in the trace only "
                    "(not the repair-eligible, LLM-reached, or executed-round subset); combined = both. "
                    "Retries are counted only in *_llm_attempts_incl_retries, never as extra records. "
                    "A Round-2 explanation call is not a repair-agent invocation and does not enter any "
                    "repair metric (table_1-table_6). These are automated schema checks only; the human "
                    "explanation-quality study covered original-failure explanations exclusively."
                ),
            },
        ],
        tables_dir / "table_9_explanation_schema_validity.csv",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute I8 frozen metrics and write summaries/tables for one evaluation run.")
    parser.add_argument("--run-dir", required=True, help="data/evaluation/<run_id> directory produced by scripts/run_evaluation.py")
    parser.add_argument("--classifier-ground-truth", default=None)
    parser.add_argument("--pypi-ground-truth", default=None)
    parser.add_argument(
        "--classifier-population-weights",
        default=None,
        help="JSON file mapping subtype -> true population share, for prevalence_weighted_overall_accuracy().",
    )
    parser.add_argument(
        "--classifier-treat-as-full-population",
        action="store_true",
        help="Pass when the classifier ground-truth sample IS the full 214-record population (methodology §D option A).",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    manifest = em.load_manifest(run_dir / "manifest.json")
    trace_path = Path(manifest["output_dir"]) / f"{manifest['run_id']}.jsonl"
    if not trace_path.is_absolute():
        trace_path = ROOT / trace_path
    trace = metrics.load_trace(trace_path)

    classifier_rows = load_ground_truth_csv(Path(args.classifier_ground_truth) if args.classifier_ground_truth else None)
    pypi_rows = load_ground_truth_csv(Path(args.pypi_ground_truth) if args.pypi_ground_truth else None)

    population_weights = None
    if args.classifier_population_weights:
        population_weights = json.loads(Path(args.classifier_population_weights).read_text(encoding="utf-8"))

    report = build_report(
        trace,
        manifest["run_id"],
        manifest["expected_record_count"],
        classifier_rows=classifier_rows,
        pypi_rows=pypi_rows,
        classifier_population_weights=population_weights,
        classifier_treat_as_full_population=args.classifier_treat_as_full_population,
    )

    write_outputs(report, run_dir / "summary", run_dir / "tables")
    print(f"wrote evaluation summary + tables under {run_dir}")


if __name__ == "__main__":
    main()
