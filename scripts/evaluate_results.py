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
            {"metric": "abstention_rate", "value": report["secondary"]["abstention_rate"]},
        ],
        tables_dir / "table_1_overall_repair_results.csv",
    )

    write_kv_csv(
        [
            {"metric": "round1_repair_success_rate", "value": report["primary"]["round1_repair_success_rate"]},
            {"metric": "final_repair_success_rate_up_to_round2", "value": report["primary"]["final_repair_success_rate"]},
            {"metric": "round2_eligible", "value": report["round2_summary"]["eligible"]},
            {"metric": "round2_attempted", "value": report["round2_summary"]["attempted"]},
            {"metric": "additional_notebooks_fixed_by_round2", "value": report["primary"]["additional_notebooks_fixed_by_round2"]},
            {"metric": "absolute_pp_improvement_from_round2", "value": report["primary"]["absolute_pp_improvement_from_round2"]},
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
    write_dict_rows_csv(failure_rows, ["category", "count"], tables_dir / "table_5_failure_abstention_infra_breakdown.csv")

    write_kv_csv(
        [
            {"metric": "proposal_validity_rate", "value": report["secondary"]["proposal_validity_rate"]},
            {"metric": "grounding_pass_rate", "value": report["secondary"]["grounding_pass_rate"]},
            {
                "metric": "end_to_end_valid_grounded_proposal_rate",
                "value": report["secondary"]["end_to_end_valid_grounded_proposal_rate"],
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
                "metric": "explanation_schema_validity_rate",
                "value": report["secondary"]["explanation_schema_validity"]["rate"],
            },
            {
                "metric": "note",
                "value": "run scripts/validate_evaluation_results.py for full ResultLogger/KG integrity checks",
            },
        ],
        tables_dir / "table_8_pipeline_resultlogger_integrity.csv",
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
