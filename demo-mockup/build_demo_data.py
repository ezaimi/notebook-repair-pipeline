#!/usr/bin/env python3
"""Regenerate demo-mockup/data/*.js from the final, frozen evaluation artifacts.

Extraction only: every field is copied from a recorded artifact. Nothing is
recomputed, simulated, or invented, and no LLM / Docker / PyPI call is made.

Sources (all read-only):
  data/evaluation/<GEMMA_RUN>/raw/pipeline-runs/<GEMMA_RUN>.jsonl   round-by-round traces (main replay)
  data/evaluation/<GEMMA_RUN>/summary/per_notebook_comparison.csv   final categories
  data/evaluation/<GEMMA_RUN>/summary/evaluation_summary.json       frozen metrics (Gemma)
  data/evaluation/<QWEN_RUN>/raw/pipeline-runs/<QWEN_RUN>.jsonl     paired trace (model sensitivity)
  data/evaluation/<QWEN_RUN>/summary/evaluation_summary.json        frozen metrics (Qwen)
  data/evaluation/<RUN>/manifest.json, validation_report.json       provenance
  data/dependency-errors/dependency_errors.csv, statistics.json     notebook metadata, dataset counts
  data/context-classification/dependency_error_contexts.jsonl       classifier context
  data/human-evaluation/analysis/human_evaluation_final_report.json human study (copied, not recomputed)

Usage (from the repository root):
    python3 demo-mockup/build_demo_data.py [--check]

--check regenerates in memory and reports differences instead of writing.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GEMMA_RUN = "i10-eval-gemma-round2-explanations-20260918T161356Z"
QWEN_RUN = "i11-eval-qwen-round2-explanations-20260919T131359Z"
EVAL_ROOT = REPO / "data" / "evaluation"
ERRORS_CSV = REPO / "data" / "dependency-errors" / "dependency_errors.csv"
STATS_JSON = REPO / "data" / "dependency-errors" / "statistics.json"
CONTEXTS_JSONL = REPO / "data" / "context-classification" / "dependency_error_contexts.jsonl"
HUMAN_REPORT = REPO / "data" / "human-evaluation" / "analysis" / "human_evaluation_final_report.json"
OUT_DIR = Path(__file__).resolve().parent / "data"

MODEL_LABELS = {
    "gemma2:9b": "Gemma-2 9B",
    "Qwen3.6-35B-A3B-MLX-8bit": "Qwen3.6-35B-A3B-MLX-8bit",
}

# Real notebooks from the final Gemma trace that each illustrate one pattern.
# Keys are stable case ids used in URLs; the pattern text is shown in the UI.
SHOWCASE = {
    164: ("case_missing_package_round2_repaired", "Missing package → targeted repair → new failure → Round 2 repair"),
    158: ("case_wrong_version_round2_abstained", "SciPy version pin → new failure → Round-2 explanation → abstention"),
    163: ("case_two_targeted_repairs", "Two targeted repairs in a row, notebook still not fully recovered"),
    79: ("case_round2_system_library_explained", "Round-2 system_library error: explained, not repair-eligible"),
    134: ("case_round2_out_of_scope_explained", "Round-2 out_of_scope error: explained, not repair-eligible"),
    21: ("case_round1_mapping_unknown", "Round-1 abstention: no supported PyPI mapping for the import"),
    203: ("case_same_error_persists", "Repair applied, identical error persists — no second round"),
    189: ("case_numpy_model_difference", "NumPy pin: one of the 13 Gemma/Qwen version-selection differences"),
    445: ("case_infrastructure_failure", "Infrastructure failure: repository clone timed out"),
    370: ("case_method_failure", "Method failure: notebook not found in the cloned repository"),
}

# PyPI retrieval logs one "unparseable filename" warning per skipped sdist/wheel.
# The workspace prints the retrieval object verbatim, so keep a sample plus an
# explicit marker instead of all of them.
MAX_RETRIEVAL_WARNINGS = 3


def read_jsonl(path):
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def read_json(path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def read_csv_dict(path, key):
    with path.open(encoding="utf-8") as fh:
        return {int(r[key]): r for r in csv.DictReader(fh)}


def truthy(value):
    return str(value).strip().lower() == "true"


def bool_or_none(value):
    if value == "True":
        return True
    if value == "False":
        return False
    return None


def model_label(model):
    return MODEL_LABELS.get(model, model)


# ---------------------------------------------------------------------------
# Per-notebook case extraction (Gemma i10 = main replay)
# ---------------------------------------------------------------------------

def build_classifier(ctx):
    return {
        "subtype": ctx.get("refined_subtype"),
        "confidence": ctx.get("confidence"),
        "root_cause_hint": ctx.get("root_cause_hint"),
        "scope_status": ctx.get("scope_status"),
        "context_status": ctx.get("context_status"),
    }


def build_round_classifier(round_rec, ctx, round2_record):
    """Round 1 takes its confidence from the classifier context record; Round 2
    from the round-2 record that Round 1's trigger produced by reclassification."""
    i4_input = round_rec["i4_result"]["input"]
    confidence = ctx.get("confidence") if round_rec["round"] == 1 else (round2_record or {}).get("confidence")
    return {
        "failing_module": i4_input.get("failing_module"),
        "subtype": i4_input.get("refined_subtype"),
        "confidence": confidence,
        "root_cause_hint": i4_input.get("root_cause_hint"),
        "scope_status": i4_input.get("scope_status"),
        "context_status": i4_input.get("context_status"),
        "error_type": i4_input.get("error_type"),
        "error_message": i4_input.get("error_message"),
    }


def trim_retrieval(retrieval):
    if not retrieval:
        return retrieval
    trimmed = dict(retrieval)
    warnings = trimmed.get("warnings") or []
    if len(warnings) > MAX_RETRIEVAL_WARNINGS:
        omitted = len(warnings) - MAX_RETRIEVAL_WARNINGS
        trimmed["warnings"] = warnings[:MAX_RETRIEVAL_WARNINGS] + [
            f"... {omitted} more PyPI filename warnings omitted from this demo extract"
        ]
    return trimmed


def build_repair_agent(i4):
    llm = i4.get("llm") or {}
    schema = i4.get("schema_validation") or {}
    grounding = i4.get("grounding_validation") or {}
    action = i4.get("final_action")
    return {
        "status": i4.get("status"),
        "abstain_reasons": i4.get("errors") or [],
        "llm_model": llm.get("model"),
        "llm_called": bool(llm.get("model")),
        "attempts": i4.get("attempts"),
        "prompt_strategy": llm.get("prompt_template"),
        # the artifact records an abstention as the literal string "none"
        "action": None if action == "none" else action,
        "install_name": i4.get("final_install_name"),
        "version": i4.get("final_version"),
        "rationale": i4.get("final_rationale"),
        "command": i4.get("command"),
        "schema_valid": schema.get("valid") if i4.get("schema_validation") else None,
        "grounding_valid": grounding.get("valid") if i4.get("grounding_validation") else None,
    }


def build_fix_applicator(i5):
    return {
        "attempted": i5.get("status") != "skipped",
        "skip_reason": i5.get("skip_reason"),
        "command": i5.get("command"),
        "outcome": i5.get("outcome"),
        "failure_stage": i5.get("failure_stage"),
        "execution_status": i5.get("execution_status"),
        "diagnostic_message": i5.get("diagnostic_message"),
        "new_error_type": i5.get("new_error_type"),
        "new_error_message": i5.get("new_error_message"),
        "same_as_original_error": i5.get("same_as_original_error"),
        "commit_checkout_status": i5.get("commit_checkout_status"),
        "elapsed_seconds": i5.get("elapsed_seconds"),
    }


def explanation_payload(explanation_entry):
    """Normalise one recorded LLMExplainer result (Round 1 top-level entry or the
    Round-2 entry stored on the trigger) into what the UI needs."""
    entry = explanation_entry or {}
    result = entry.get("explanation_result") or {}
    llm = entry.get("llm") or {}
    status = result.get("status")
    failure = None
    if result and status != "success":
        failure = {
            "status": status,
            "category": result.get("failure_category"),
            "attempts": result.get("attempts"),
            "error": result.get("error"),
            "validation_errors": result.get("validation_errors") or [],
        }
    return {
        "status": status,
        "json": result.get("explanation_json") if status == "success" else None,
        "model": llm.get("llm_model"),
        "model_label": model_label(llm.get("llm_model")),
        "prompt_strategy": llm.get("prompt_strategy"),
        "attempts": result.get("attempts"),
        "latency_ms": result.get("latency_ms"),
        "round": entry.get("round"),
        "failure": failure,
    }


def build_round2(record, rounds_out):
    """Everything the UI needs about the second round: the reclassified new
    error, its own explanation, the eligibility decision, and whether a repair
    round actually executed. None when Round 1 exposed no genuinely new error."""
    trigger = (record["rounds"][0].get("round2_trigger")) or {}
    if "round2_record" not in trigger:
        return None
    rec = trigger["round2_record"]
    executed = len(record["rounds"]) > 1
    explanation = explanation_payload(trigger.get("explanation"))
    if executed:
        r2 = rounds_out[1]
        if r2["repair_agent"]["status"] == "success":
            repair_status = "attempted"
        else:
            repair_status = "abstained"
    else:
        repair_status = "not_eligible"
    return {
        "new_error": {
            "error_type": rec.get("error_type"),
            "error_message": rec.get("error_message"),
        },
        "record": {
            "failing_module": rec.get("failing_module"),
            "subtype": rec.get("refined_subtype"),
            "original_subtype": rec.get("original_subtype"),
            "scope_status": rec.get("scope_status"),
            "exclusion_reason": rec.get("exclusion_reason") or None,
            "root_cause_hint": rec.get("root_cause_hint"),
            "confidence": rec.get("confidence"),
            "context_status": rec.get("context_status"),
        },
        "explanation": explanation,
        "eligible": bool(trigger.get("triggered")),
        "trigger_reason": trigger.get("reason"),
        "executed": executed,
        "repair_status": repair_status,
        "trace_only": not executed,
    }


def build_rounds(record, ctx):
    trigger = (record["rounds"][0].get("round2_trigger")) or {}
    round2_record = trigger.get("round2_record")
    rounds = []
    for round_rec in record["rounds"]:
        i4 = round_rec["i4_result"]
        i5 = round_rec["i5_result"]
        entry = {
            "round": round_rec["round"],
            "status": round_rec["status"],
            "classifier": build_round_classifier(round_rec, ctx, round2_record),
            "retrieval": trim_retrieval(i4.get("retrieval_result")),
            "repair_agent": build_repair_agent(i4),
            "fix_applicator": build_fix_applicator(i5),
            "repair_attempts_row_id": round_rec.get("repair_attempts_row_id"),
        }
        if round_rec["round"] == 1:
            entry["round2_trigger"] = {
                "triggered": bool(trigger.get("triggered")),
                "reason": trigger.get("reason"),
                "new_error_reclassified": "round2_record" in trigger,
            }
        rounds.append(entry)
    return rounds


def build_original_error(err_row, ctx):
    hint = ctx.get("legacy_traceback_hint") or {}
    prompt_ctx = ctx.get("prompt_context") or {}
    return {
        "error_type": err_row.get("error_type"),
        "error_message": err_row.get("error_message"),
        "failing_module": err_row.get("failing_module"),
        "error_cell_index": err_row.get("error_cell_index"),
        "error_count": err_row.get("error_count"),
        "failing_cell_source": prompt_ctx.get("failing_cell_source"),
        "raw_traceback": hint.get("raw_traceback"),
    }


def build_final_result(cmp_row):
    return {
        "round1_category": cmp_row["round1_category"],
        "round2_eligible": truthy(cmp_row["round2_eligible"]),
        "round2_attempted": truthy(cmp_row["round2_attempted"]),
        "round2_category": cmp_row["round2_category"] or None,
        "final_category": cmp_row["final_category"],
        "targeted_error_resolved_round1": bool_or_none(cmp_row["targeted_error_resolved_round1"]),
        "targeted_error_resolved_round2": bool_or_none(cmp_row["targeted_error_resolved_round2"]),
        "additional_fix_from_round2": cmp_row["additional_fix_from_round2"] or None,
        "infrastructure_failure": truthy(cmp_row["infrastructure_failure"]),
    }


def build_flags(rounds, round2, final, explanation):
    r1 = rounds[0]
    return {
        "round1_abstained": r1["repair_agent"]["status"] == "abstained",
        "round1_llm_called": r1["repair_agent"]["llm_called"],
        "round2_reclassified": round2 is not None,
        "round2_eligible": bool(round2 and round2["eligible"]),
        "round2_attempted": bool(round2 and round2["repair_status"] == "attempted"),
        "round2_abstained": bool(round2 and round2["repair_status"] == "abstained"),
        "round2_trace_only": bool(round2 and round2["trace_only"]),
        "same_error_persisted": r1["round2_trigger"]["reason"] == "same_as_original_error",
        "targeted_resolved_any": final["targeted_error_resolved_round1"] is True or final["targeted_error_resolved_round2"] is True,
        "still_failing": final["final_category"] == "still_failing",
        "infrastructure_failure": final["final_category"] == "infrastructure_failure",
        "method_failure": final["final_category"] == "method_failure",
        "explanation_runtime_failure": explanation["status"] not in (None, "success"),
    }


def build_cases(run_dir):
    trace = read_jsonl(run_dir / "raw" / "pipeline-runs" / f"{run_dir.name}.jsonl")
    contexts = {r["notebook_execution_id"]: r for r in read_jsonl(CONTEXTS_JSONL)}
    errors = read_csv_dict(ERRORS_CSV, "notebook_execution_id")
    comparisons = read_csv_dict(run_dir / "summary" / "per_notebook_comparison.csv", "notebook_execution_id")

    cases, listing = [], []
    for record in trace:
        nb_id = record["notebook_execution_id"]
        ctx = contexts.get(nb_id, {})
        err_row = errors[nb_id]
        cmp_row = comparisons[nb_id]

        explanation = explanation_payload(record.get("explanation"))
        rounds = build_rounds(record, ctx)
        round2 = build_round2(record, rounds)
        final = build_final_result(cmp_row)
        flags = build_flags(rounds, round2, final, explanation)
        case_id, showcase_title = SHOWCASE.get(nb_id, (f"case_nb_{nb_id}", None))

        cases.append({
            "id": case_id,
            "notebook_execution_id": nb_id,
            "notebook_name": err_row.get("notebook_name"),
            "repository_url": err_row.get("repository_url"),
            "split": err_row.get("split"),
            "run_id": run_dir.name,
            "original_error": build_original_error(err_row, ctx),
            "classifier": build_classifier(ctx),
            "explanation": explanation,
            "rounds": rounds,
            "round2": round2,
            "repair_eligibility": record.get("repair_eligibility"),
            "final_result": final,
            "flags": flags,
            "showcase": showcase_title,
        })

        r1 = rounds[0]
        listing.append({
            "notebook_execution_id": nb_id,
            "case_id": case_id,
            "notebook_name": err_row.get("notebook_name"),
            "repository_url": err_row.get("repository_url"),
            "error_type": err_row.get("error_type"),
            "failing_module": err_row.get("failing_module"),
            "subtype": cmp_row["subtype"],
            "explanation_status": explanation["status"],
            "round1_action": cmp_row["round1_action"] or None,
            "round1_outcome": cmp_row["round1_outcome"] or None,
            "round1_category": cmp_row["round1_category"],
            "round1_proposal": (f"{r1['repair_agent']['install_name']}=={r1['repair_agent']['version']}"
                                if r1["repair_agent"]["version"] else r1["repair_agent"]["install_name"]),
            "round2_reclassified": round2 is not None,
            "round2_new_module": round2["record"]["failing_module"] if round2 else None,
            "round2_new_subtype": round2["record"]["subtype"] if round2 else None,
            "round2_scope_status": round2["record"]["scope_status"] if round2 else None,
            "round2_explanation_status": round2["explanation"]["status"] if round2 else None,
            "round2_eligible": bool(round2 and round2["eligible"]),
            "round2_status": round2["repair_status"] if round2 else "none",
            "round2_action": cmp_row["round2_action"] or None,
            "round2_outcome": cmp_row["round2_outcome"] or None,
            "round2_category": cmp_row["round2_category"] or None,
            "final_category": cmp_row["final_category"],
            "targeted_error_resolved_round1": final["targeted_error_resolved_round1"],
            "targeted_error_resolved_round2": final["targeted_error_resolved_round2"],
            "flags": flags,
            "showcase": showcase_title,
        })

    cases.sort(key=lambda c: c["notebook_execution_id"])
    listing.sort(key=lambda r: r["notebook_execution_id"])
    return cases, listing


# ---------------------------------------------------------------------------
# Run-level metrics and provenance (Gemma i10, Qwen i11)
# ---------------------------------------------------------------------------

def load_run_metrics(run_dir):
    summary = read_json(run_dir / "summary" / "evaluation_summary.json")
    manifest = read_json(run_dir / "manifest.json")
    validation = read_json(run_dir / "validation_report.json")
    checks = validation["checks"]
    explanation = summary["explanation"]
    secondary = summary["secondary"]
    round2 = summary["round2_summary"]
    primary = summary.get("primary") or {}

    trace = read_jsonl(run_dir / "raw" / "pipeline-runs" / f"{run_dir.name}.jsonl")
    # Runtime-failure breakdown for original-failure explanations, copied from
    # each record's recorded failure category (timeout / model_unavailable / ...).
    failure_categories = {}
    round2_composition = {}
    for rec in trace:
        result = (rec.get("explanation") or {}).get("explanation_result") or {}
        if result.get("status") not in (None, "success"):
            cat = result.get("failure_category") or result.get("status")
            failure_categories[cat] = failure_categories.get(cat, 0) + 1
        trigger = (rec["rounds"][0].get("round2_trigger")) or {}
        if "round2_record" in trigger:
            sub = trigger["round2_record"].get("refined_subtype")
            round2_composition[sub] = round2_composition.get(sub, 0) + 1

    real_attempts = 0
    r1_attempts = r1_resolved = r2_attempts = r2_resolved = 0
    for row in summary["comparison_records"]:
        t1 = row.get("targeted_error_resolved_round1")
        t2 = row.get("targeted_error_resolved_round2")
        if t1 is not None:
            r1_attempts += 1
            r1_resolved += 1 if t1 else 0
        if t2 is not None:
            r2_attempts += 1
            r2_resolved += 1 if t2 else 0
    real_attempts = r1_attempts + r2_attempts

    return {
        "run_id": run_dir.name,
        "model": manifest["model"],
        "model_label": model_label(manifest["model"]),
        "provider": "ollama" if manifest["model"].startswith("gemma") else "kiste",
        "provenance": {
            "run_id": run_dir.name,
            "split": manifest["split"],
            "expected_record_count": manifest["expected_record_count"],
            "actual_record_count": summary["actual_record_count"],
            "git_commit_sha": manifest["git_commit_sha"],
            "git_working_tree_dirty": manifest.get("git_working_tree_dirty"),
            "max_rounds": manifest["max_rounds"],
            "prompt_strategy": manifest.get("prompt_strategy"),
            "explanation_prompt_version": manifest.get("explanation_prompt_version"),
            "repair_prompt_version": manifest.get("repair_prompt_version"),
            "python_version": manifest.get("python_version"),
            "config_paths": manifest.get("config_paths"),
            "orchestrator_features": manifest.get("orchestrator_features"),
            "created_at": manifest.get("created_at"),
            "integrity_checks_passed": sum(1 for c in checks if c["passed"]),
            "integrity_checks_total": len(checks),
            "integrity_check_names": [c["name"] for c in checks],
            "code_hashes": manifest.get("code_hashes"),
        },
        "explanation": {
            "original": {
                "records": explanation["original_explanation_schema_validity"]["processed"],
                "completed": explanation["original_explanation_schema_validity"]["valid"],
                "runtime_failures": explanation["original_explanation_schema_validity"]["failed"],
                "runtime_failure_categories": failure_categories,
                "completion_rate": explanation["original_explanation_schema_validity"]["rate"],
                "llm_attempts_incl_retries": explanation["call_counts"]["original_llm_attempts"],
                "records_with_retry": explanation["call_counts"]["records_with_retry"],
            },
            "round2": {
                "records": explanation["round2_explanation_schema_validity"]["processed"],
                "completed": explanation["round2_explanation_schema_validity"]["valid"],
                "runtime_failures": explanation["round2_explanation_schema_validity"]["failed"],
                "completion_rate": explanation["round2_explanation_schema_validity"]["rate"],
                "reclassified_new_errors": explanation["round2_explanation_schema_validity"]["reclassified_new_errors"],
                "explained_repair_eligible": explanation["round2_explanation_schema_validity"]["explained_repair_eligible"],
                "explained_not_repair_eligible_trace_only": explanation["round2_explanation_schema_validity"]["explained_not_repair_eligible_trace_only"],
                "composition_by_subtype": round2_composition,
                "llm_attempts_incl_retries": explanation["call_counts"]["round2_llm_attempts"],
            },
            "combined": {
                "records": explanation["combined_explanation_schema_validity"]["processed"],
                "completed": explanation["combined_explanation_schema_validity"]["valid"],
                "runtime_failures": explanation["combined_explanation_schema_validity"]["failed"],
                "completion_rate": explanation["combined_explanation_schema_validity"]["rate"],
                "llm_attempts_incl_retries": explanation["call_counts"]["total_llm_attempts"],
            },
            # Every completed response in both runs validated against the schema:
            # the recorded "valid" counts equal the completed counts, and the
            # "failed" counts are runtime failures (no response to validate).
            "schema_valid_among_completed": explanation["combined_explanation_schema_validity"]["valid"],
            "note": explanation.get("note"),
        },
        "repair": {
            "evaluation_notebooks": summary["expected_record_count"],
            "round1_abstentions": secondary["round1_abstention_count"],
            "round1_abstention_rate": secondary["round1_abstention_rate"],
            "final_state_abstentions": secondary["final_state_abstention_count"],
            "final_state_abstention_rate": secondary["final_state_abstention_rate"],
            "round2_abstentions": secondary["round2_abstention_count"],
            "repair_agent_invocations": summary["expected_record_count"] + round2["eligible"],
            "repair_llm_responses": real_attempts,
            "repair_llm_responses_round1": r1_attempts,
            "repair_llm_responses_round2": r2_attempts,
            "proposal_validity_rate": secondary["proposal_validity_rate"],
            "grounding_pass_rate": secondary["grounding_pass_rate"],
            "grounded_proposal_coverage_rate": secondary["overall_grounded_proposal_coverage_rate"],
            "targeted_resolved_round1": r1_resolved,
            "targeted_resolved_round2": r2_resolved,
            "targeted_resolved_total": r1_resolved + r2_resolved,
            "targeted_resolution_rate": secondary["targeted_error_resolution_rate"],
            "full_recovery_round1": primary.get("round1_repair_success_count", 0),
            "full_recovery_final": summary["failure_breakdown"].get("fixed", 0),
            "round2_eligible": round2["eligible"],
            "round2_proposals": round2["proposal_generated"],
            "round2_attempts": round2["attempted"],
            "round2_abstained": round2["abstained"],
            "round2_non_attempt_reasons": round2.get("non_attempt_reasons"),
            "final_outcomes": summary["failure_breakdown"],
            "subtype_breakdown": secondary["subtype_level_repair_success"],
            "infrastructure_failure_rate": secondary["infrastructure_failure_rate"],
        },
        "classifier_scoring": summary.get("classifier_scoring"),
        "pypi_resolution_scoring": summary.get("pypi_resolution_scoring"),
    }


def r1_proposal(rec):
    i4 = rec["rounds"][0]["i4_result"]
    return (i4.get("final_action"), i4.get("final_install_name"), i4.get("final_version"))


def build_comparison(gemma_dir, qwen_dir):
    """Paired notebook-by-notebook comparison, read from both raw traces."""
    gemma = {r["notebook_execution_id"]: r for r in read_jsonl(gemma_dir / "raw" / "pipeline-runs" / f"{gemma_dir.name}.jsonl")}
    qwen = {r["notebook_execution_id"]: r for r in read_jsonl(qwen_dir / "raw" / "pipeline-runs" / f"{qwen_dir.name}.jsonl")}
    gcmp = read_csv_dict(gemma_dir / "summary" / "per_notebook_comparison.csv", "notebook_execution_id")
    qcmp = read_csv_dict(qwen_dir / "summary" / "per_notebook_comparison.csv", "notebook_execution_id")
    assert set(gemma) == set(qwen), "paired runs cover different notebooks"

    def state(rec, cmp_row):
        out = []
        for rnd in rec["rounds"]:
            i4, i5 = rnd["i4_result"], rnd["i5_result"]
            out.append({
                "round": rnd["round"],
                "retrieval_status": (i4.get("retrieval_result") or {}).get("status"),
                "rag_status": i4.get("status"),
                "action": i4.get("final_action"),
                "install_name": i4.get("final_install_name"),
                "version": i4.get("final_version"),
                "outcome": i5.get("outcome"),
                "same_as_original_error": i5.get("same_as_original_error"),
                "new_error": (i5.get("new_error_type"), i5.get("new_error_message")),
            })
        trig = rec["rounds"][0].get("round2_trigger") or {}
        r2 = trig.get("round2_record") or {}
        return {
            "rounds": out,
            "round2": (bool(trig.get("triggered")), trig.get("reason"), r2.get("failing_module"), r2.get("refined_subtype"), r2.get("scope_status")),
            "final_category": cmp_row["final_category"],
            "targeted": (cmp_row["targeted_error_resolved_round1"], cmp_row["targeted_error_resolved_round2"]),
        }

    identical = 0
    differences = []
    for nb in sorted(gemma):
        gs, qs = state(gemma[nb], gcmp[nb]), state(qwen[nb], qcmp[nb])
        if gs == qs:
            identical += 1
            continue
        g1, q1 = gs["rounds"][0], qs["rounds"][0]
        gret = gemma[nb]["rounds"][0]["i4_result"].get("retrieval_result") or {}
        qret = qwen[nb]["rounds"][0]["i4_result"].get("retrieval_result") or {}
        gcands = [c.get("version") if isinstance(c, dict) else c for c in (gret.get("candidate_versions") or [])]
        qcands = [c.get("version") if isinstance(c, dict) else c for c in (qret.get("candidate_versions") or [])]
        compat = (gret.get("compatibility_evidence") or {})
        differing_fields = []
        for key in ("retrieval_status", "rag_status", "action", "install_name", "version", "outcome", "same_as_original_error", "new_error"):
            if g1.get(key) != q1.get(key):
                differing_fields.append(f"round1.{key}")
        if gs["round2"] != qs["round2"]:
            differing_fields.append("round2_trigger")
        if len(gs["rounds"]) != len(qs["rounds"]) or (len(gs["rounds"]) > 1 and gs["rounds"][1] != qs["rounds"][1]):
            differing_fields.append("round2")
        if gs["final_category"] != qs["final_category"]:
            differing_fields.append("final_category")
        if gs["targeted"] != qs["targeted"]:
            differing_fields.append("targeted_resolution")
        differences.append({
            "notebook_execution_id": nb,
            "failing_module": gemma[nb]["rounds"][0]["i4_result"]["input"].get("failing_module"),
            "subtype": gemma[nb]["rounds"][0]["i4_result"]["input"].get("refined_subtype"),
            "error_message": gemma[nb]["rounds"][0]["i4_result"]["input"].get("error_message"),
            "repository_url": (gemma[nb]["rounds"][0]["i5_result"] or {}).get("repository_url"),
            "differing_fields": differing_fields,
            "gemma": {"action": g1["action"], "install_name": g1["install_name"], "version": g1["version"],
                      "outcome": g1["outcome"], "new_error": g1["new_error"], "final_category": gs["final_category"],
                      "rationale": gemma[nb]["rounds"][0]["i4_result"].get("final_rationale")},
            "qwen": {"action": q1["action"], "install_name": q1["install_name"], "version": q1["version"],
                     "outcome": q1["outcome"], "new_error": q1["new_error"], "final_category": qs["final_category"],
                     "rationale": qwen[nb]["rounds"][0]["i4_result"].get("final_rationale")},
            "candidate_versions_identical": gcands == qcands,
            "candidate_versions": gcands,
            "compatibility_specifier": compat.get("compatible_specifier"),
            "compatibility_identical": json.dumps(gret.get("compatibility_evidence"), sort_keys=True) == json.dumps(qret.get("compatibility_evidence"), sort_keys=True),
            "downstream_identical": (g1["outcome"] == q1["outcome"] and g1["new_error"] == q1["new_error"]
                                     and gs["round2"] == qs["round2"] and gs["final_category"] == qs["final_category"]
                                     and gs["targeted"] == qs["targeted"]
                                     and (len(gs["rounds"]) == len(qs["rounds"]))
                                     and (len(gs["rounds"]) < 2 or gs["rounds"][1] == qs["rounds"][1])),
        })
    return {
        "paired_notebooks": len(gemma),
        "identical_notebooks": identical,
        "differing_notebooks": len(differences),
        "differences": differences,
        "note": "Computed by comparing the two raw traces field by field (retrieval status, repair status, action, "
                "install name, version, FixApplicator outcome, newly exposed error, Round-2 decision and outcome, "
                "final classification). Read-only extraction; nothing is re-executed.",
    }


def build_human_evaluation():
    h = read_json(HUMAN_REPORT)
    items = {}
    for key, val in h["overall_by_item"].items():
        items[key] = {
            "n": val["n"], "median": val["median"], "iqr": val["iqr"],
            "pct_agree_or_strongly_agree": val["pct_agree_or_strongly_agree"],
            "distribution": val["distribution"],
        }
    verification = h.get("verification") or {}
    per_variant = verification.get("per_variant") or {}
    return {
        "status": "completed",
        "scope": "Original-failure Gemma-2 9B explanations only. Round-2 explanations and Qwen explanations were not rated by participants.",
        "n_complete_participants": h["n_complete_participants"],
        "n_explanation_evaluations": h["n_explanation_evaluations"],
        "n_likert_ratings": h["n_likert_ratings"],
        "pooled_median": h["overall_pooled"]["median"],
        "pooled_iqr": h["overall_pooled"]["iqr"],
        "pooled_pct_agree_or_strongly_agree": h["overall_pooled"]["pct_agree_or_strongly_agree"],
        "pooled_distribution": h["overall_pooled"]["distribution"],
        "items": items,
        "cronbachs_alpha": h["reliability"]["cronbachs_alpha"],
        "raw_responses": sum(v.get("raw_responses", 0) for v in per_variant.values()),
        "excluded_responses": sum(v.get("excluded_responses", 0) for v in per_variant.values()),
        "composite_score_reported": h.get("composite_score") is not None,
        "note": "Copied from data/human-evaluation/analysis/human_evaluation_final_report.json, which scripts/analyze_human_evaluation.py derives from the four raw survey exports.",
    }


COMMIT_PINNING_NOTE = (
    "Provenance-specific checkout is supported by FixApplicator and was validated separately. "
    "In the final WSL evaluation runs, repository metadata was unavailable to FixApplicator because of a "
    "local path mismatch, so repositories were cloned from their default branches. This applied equally "
    "to Gemma and Qwen."
)


def build_evaluation(gemma_dir, qwen_dir):
    stats = read_json(STATS_JSON)
    stats.pop("source_database", None)
    return {
        "main_run_id": gemma_dir.name,
        "sensitivity_run_id": qwen_dir.name,
        "gemma": load_run_metrics(gemma_dir),
        "qwen": load_run_metrics(qwen_dir),
        "comparison": build_comparison(gemma_dir, qwen_dir),
        "human_evaluation": build_human_evaluation(),
        "dataset": stats,
        "commit_pinning_note": COMMIT_PINNING_NOTE,
        "demo_note": "Demo mode: replays recorded pipeline runs. No live LLM, Docker, or PyPI calls.",
    }


# ---------------------------------------------------------------------------

def as_js(const_name, payload, note):
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    return f"// {note}\nconst {const_name} = {body};\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="compare against the committed files instead of writing")
    args = parser.parse_args()

    gemma_dir = EVAL_ROOT / GEMMA_RUN
    qwen_dir = EVAL_ROOT / QWEN_RUN
    cases, listing = build_cases(gemma_dir)
    evaluation = build_evaluation(gemma_dir, qwen_dir)

    note = f"Generated by demo-mockup/build_demo_data.py from the frozen runs {GEMMA_RUN} (main) and {QWEN_RUN} (sensitivity). Do not edit by hand."
    outputs = {
        OUT_DIR / "cases.js": as_js("CASES", cases, note),
        OUT_DIR / "notebook_list.js": as_js("NOTEBOOK_LIST", listing, note),
        OUT_DIR / "evaluation.js": as_js("EVALUATION", evaluation, note),
    }

    if args.check:
        ok = True
        for path, text in outputs.items():
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            state = "match" if current == text else "DIFFERS"
            ok = ok and current == text
            print(f"{path.name}: {state}")
        print(f"cases: {len(cases)}  listing rows: {len(listing)}  differences: {evaluation['comparison']['differing_notebooks']}")
        return 0 if ok else 1

    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(REPO)} ({len(text):,} bytes)")
    r2 = [c for c in cases if c["round2"]]
    print(f"cases: {len(cases)}  round2 reclassified: {len(r2)}  trace-only: {sum(1 for c in r2 if c['round2']['trace_only'])}"
          f"  comparison differences: {evaluation['comparison']['differing_notebooks']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
