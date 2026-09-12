#!/usr/bin/env python3

"""EvaluationMetrics (i8): the frozen metric definitions from
docs/i8-evaluation-methodology.md, computed from scripts/run_pipeline.py's
own per-record JSONL trace.

Two layers:

1. `build_comparison_record()` derives ONE paired per-notebook record from
   a single trace entry (one `--max-rounds 2` run). "Round-1" and
   "up-to-Round-2" conditions are both read from the SAME Round-1
   realization - there is no second, independently-sampled Round-1 run.
   This is the frozen paired design (methodology §C): it avoids Ollama's
   nonzero temperature (config/rag_repair.yaml, config/llm_explainer.yaml)
   turning a stochastic difference into a false Round-2 effect.

2. Every metric formula in the frozen methodology, computed from a list of
   comparison records plus the manifest's `expected_record_count` - never
   a hardcoded 187/13 literal, so the same functions serve both the dev
   validation run and the final evaluation run.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import infra_classification as ic


# --- loading the orchestrator's own trace --------------------------------

def load_trace(path: Path) -> List[Dict[str, Any]]:
    """Load one scripts/run_pipeline.py trace JSONL file (one diagnostics
    dict per record processed)."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _round_entry(rounds: List[Dict[str, Any]], round_number: int) -> Optional[Dict[str, Any]]:
    for entry in rounds:
        if entry.get("round") == round_number:
            return entry
    return None


def _real_attempt(round_entry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The i5_result dict IF FixApplicator actually executed a real
    (Docker) attempt in this round - i.e. i5's own status is "completed",
    not "skipped" (i4 abstained/failed/proposed action "none") - else
    None. Never inferred from i4 alone, so this stays correct even if
    classify_i4_i5's own i4-first branching ever changes."""
    if round_entry is None or round_entry.get("status") != "completed":
        return None
    i5_result = round_entry.get("i5_result")
    if i5_result is None or i5_result.get("status") != "completed":
        return None
    return i5_result


def _targeted_error_resolved(round_entry: Optional[Dict[str, Any]]) -> Optional[bool]:
    """None if this round never reached a real FixApplicator attempt (not
    part of the Targeted Error Resolution Rate denominator at all). True if
    the ORIGINAL dependency error this attempt targeted is gone - whether
    because the notebook is now fully "fixed", or because it is
    "still_failing" on a genuinely different, newly-exposed error
    (same_as_original_error == False). False if the attempt ran but the
    original error is still present (same_as_original_error == True) or
    the attempt could not even be fairly judged (apply_error)."""
    i5_result = _real_attempt(round_entry)
    if i5_result is None:
        return None
    outcome = i5_result.get("outcome")
    if outcome == "fixed":
        return True
    if outcome == "still_failing":
        return not i5_result.get("same_as_original_error", True)
    if outcome == "apply_error":
        return False
    return None


def _extracted_subtype_and_module(round1_entry: Optional[Dict[str, Any]]) -> (Optional[str], Optional[str]):
    i4_result = (round1_entry or {}).get("i4_result") or {}
    input_block = i4_result.get("input") or {}
    return input_block.get("refined_subtype"), input_block.get("failing_module")


# --- one paired per-notebook comparison record ----------------------------

def build_comparison_record(diagnostics: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    """Derive the paired Round-1 / up-to-Round-2 comparison record for one
    notebook from a single trace entry. See module docstring - both
    conditions are read from this one entry, never re-run."""
    notebook_execution_id = diagnostics.get("notebook_execution_id")
    rounds = diagnostics.get("rounds", [])
    round1_entry = _round_entry(rounds, 1)
    round2_entry = _round_entry(rounds, 2)

    round1_classification = ic.classify_round_entry(round1_entry) if round1_entry else {
        "category": ic.UNKNOWN,
        "detail": "no round 1 trace entry",
    }
    round2_classification = ic.classify_round_entry(round2_entry) if round2_entry else None

    subtype, failing_module = _extracted_subtype_and_module(round1_entry)

    round1_i4 = (round1_entry or {}).get("i4_result") or {}
    round1_action = round1_i4.get("final_action")
    round1_i5 = _real_attempt(round1_entry)
    round1_outcome = round1_i5.get("outcome") if round1_i5 else None

    round2_trigger = (round1_entry or {}).get("round2_trigger") or {}
    round2_eligible = bool(round2_trigger.get("triggered"))

    round2_i5 = _real_attempt(round2_entry)
    round2_attempted = round2_i5 is not None
    round2_action = None
    round2_outcome = None
    if round2_entry is not None and round2_entry.get("status") == "completed":
        round2_i4 = round2_entry.get("i4_result") or {}
        round2_action = round2_i4.get("final_action")
    if round2_i5:
        round2_outcome = round2_i5.get("outcome")

    # Up-to-Round-2 condition: Round 2's classification if Round 2 actually
    # ran, else Round 1's - never a fresh/independent Round-1 re-sample.
    if round2_classification is not None:
        final_classification = round2_classification
    else:
        final_classification = round1_classification

    additional_fix_from_round2 = (
        round1_classification["category"] == ic.STILL_FAILING
        and round2_classification is not None
        and round2_classification["category"] == ic.FIXED
    )

    infrastructure_failure = round1_classification["category"] == ic.INFRASTRUCTURE_FAILURE or (
        round2_classification is not None and round2_classification["category"] == ic.INFRASTRUCTURE_FAILURE
    )

    return {
        "notebook_execution_id": notebook_execution_id,
        "subtype": subtype,
        "failing_module": failing_module,
        "round1_action": round1_action,
        "round1_outcome": round1_outcome,
        "round1_category": round1_classification["category"],
        "round2_eligible": round2_eligible,
        "round2_attempted": round2_attempted,
        "round2_action": round2_action,
        "round2_outcome": round2_outcome,
        "round2_category": round2_classification["category"] if round2_classification else None,
        "final_category": final_classification["category"],
        "additional_fix_from_round2": additional_fix_from_round2,
        "targeted_error_resolved_round1": _targeted_error_resolved(round1_entry),
        "targeted_error_resolved_round2": _targeted_error_resolved(round2_entry),
        "infrastructure_failure": infrastructure_failure,
        "run_id": run_id,
    }


def build_comparison_dataset(trace: List[Dict[str, Any]], run_id: str) -> List[Dict[str, Any]]:
    return [build_comparison_record(diagnostics, run_id) for diagnostics in trace]


# --- PRIMARY metrics -------------------------------------------------------

def _rate(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return numerator / denominator


def system_level_repair_success_rate(records: List[Dict[str, Any]], expected_record_count: int) -> Optional[float]:
    """fixed (final, <=2 rounds) / expected_record_count. THE headline
    metric - never replace this denominator with a smaller one."""
    fixed = sum(1 for r in records if r["final_category"] == ic.FIXED)
    return _rate(fixed, expected_record_count)


def round1_repair_success_rate(records: List[Dict[str, Any]], expected_record_count: int) -> Optional[float]:
    fixed = sum(1 for r in records if r["round1_category"] == ic.FIXED)
    return _rate(fixed, expected_record_count)


def final_repair_success_rate(records: List[Dict[str, Any]], expected_record_count: int) -> Optional[float]:
    """Numerically identical to system_level_repair_success_rate() by
    definition (both are "fixed after <=2 rounds" / expected count) -
    exposed under both names because the frozen methodology reports them
    in two different contexts (headline number vs. Round-1-vs-2 table)."""
    return system_level_repair_success_rate(records, expected_record_count)


def additional_notebooks_fixed_by_round2(records: List[Dict[str, Any]]) -> int:
    return sum(1 for r in records if r["additional_fix_from_round2"])


def absolute_pp_improvement_from_round2(records: List[Dict[str, Any]], expected_record_count: int) -> Optional[float]:
    round1_rate = round1_repair_success_rate(records, expected_record_count)
    final_rate = final_repair_success_rate(records, expected_record_count)
    if round1_rate is None or final_rate is None:
        return None
    return final_rate - round1_rate


# --- SECONDARY / diagnostic metrics -----------------------------------------

def conditional_repair_success_rate(records: List[Dict[str, Any]]) -> Optional[float]:
    """fixed / notebooks where FixApplicator actually attempted a repair
    (round 1 or round 2). Diagnostic - must never be reported as the
    headline number, since it silently drops every abstention/exclusion
    from the denominator."""
    attempted = [r for r in records if r["round1_outcome"] is not None or r["round2_outcome"] is not None]
    fixed = sum(1 for r in attempted if r["final_category"] == ic.FIXED)
    return _rate(fixed, len(attempted))


def targeted_error_resolution_rate(records: List[Dict[str, Any]]) -> Optional[float]:
    """Attempt-level (not notebook-level, per the frozen definition): a
    notebook contributing both a Round-1 and a Round-2 real attempt counts
    twice. Numerator: attempts where the ORIGINAL targeted dependency error
    disappeared (fully fixed, OR still_failing on a genuinely different new
    error). Denominator: every real FixApplicator attempt, any round."""
    resolutions = []
    for r in records:
        if r["targeted_error_resolved_round1"] is not None:
            resolutions.append(r["targeted_error_resolved_round1"])
        if r["targeted_error_resolved_round2"] is not None:
            resolutions.append(r["targeted_error_resolved_round2"])
    return _rate(sum(1 for x in resolutions if x), len(resolutions))


def method_only_success_rate(records: List[Dict[str, Any]], expected_record_count: int) -> Optional[float]:
    """fixed / (expected_record_count - genuine infrastructure failures).
    Diagnostic only - reported alongside, never instead of, the headline
    system-level rate."""
    infra = sum(1 for r in records if r["infrastructure_failure"])
    fixed = sum(1 for r in records if r["final_category"] == ic.FIXED)
    return _rate(fixed, expected_record_count - infra)


def infrastructure_failure_rate(records: List[Dict[str, Any]], expected_record_count: int) -> Optional[float]:
    infra = sum(1 for r in records if r["infrastructure_failure"])
    return _rate(infra, expected_record_count)


def abstention_rate(records: List[Dict[str, Any]], expected_record_count: int) -> Optional[float]:
    """Round-1 abstention rate. Round 2 can never trigger from an
    abstained Round 1 (evaluate_round2_trigger() requires Round-1 outcome
    "still_failing", which an abstained record never has), so Round-1
    abstention alone is unambiguous here."""
    abstained = sum(1 for r in records if r["round1_category"] == ic.ABSTAINED)
    return _rate(abstained, expected_record_count)


def subtype_level_repair_success(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{subtype: {"eligible": n, "fixed": n, "rate": x}} - denominator is
    the actual count of records with that subtype in THIS run's eligible
    population, never a hardcoded population-wide count."""
    by_subtype: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        if r["round1_category"] == ic.EXCLUDED:
            continue
        subtype = r.get("subtype") or "unknown"
        by_subtype.setdefault(subtype, []).append(r)

    result = {}
    for subtype, subset in by_subtype.items():
        fixed = sum(1 for r in subset if r["final_category"] == ic.FIXED)
        result[subtype] = {"eligible": len(subset), "fixed": fixed, "rate": _rate(fixed, len(subset))}
    return result


def failure_breakdown(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count of every final-category bucket across all processed records -
    fixed/still_failing/abstained/infrastructure_failure/method_failure/
    excluded/unknown. Uses `final_category` (up-to-Round-2), matching the
    headline metric's own scope."""
    counts: Dict[str, int] = {category: 0 for category in ic.ALL_CATEGORIES}
    for r in records:
        category = r["final_category"]
        counts[category] = counts.get(category, 0) + 1
    return counts


# --- proposal validity / grounding (attempt-level, both rounds) ------------

def _all_i4_results(trace: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every i4_result across both rounds of every record in a raw trace -
    used for Proposal Validity Rate / Grounding Pass Rate, which are
    attempt-level metrics over every real LLM call, not per-notebook."""
    results = []
    for diagnostics in trace:
        for round_entry in diagnostics.get("rounds", []):
            i4_result = round_entry.get("i4_result")
            if i4_result is not None:
                results.append(i4_result)
    return results


def _llm_repair_responses(i4_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """i4 results for which an actual Ollama call was made - i.e.
    schema_validation was set at all. Records that abstained BEFORE any LLM
    call (ineligible, unsupported subtype, extraction failure, retrieval
    fault) never reach this point in scripts/rag_repair_agent.py and must
    not be counted as a "malformed LLM response"."""
    return [r for r in i4_results if r.get("schema_validation") is not None]


def proposal_validity_rate(trace: List[Dict[str, Any]]) -> Optional[float]:
    """schema-valid repair proposals / LLM repair responses. Malformed LLM
    output only - never conflated with grounding rejection."""
    responses = _llm_repair_responses(_all_i4_results(trace))
    valid = sum(1 for r in responses if (r.get("schema_validation") or {}).get("valid"))
    return _rate(valid, len(responses))


def grounding_pass_rate(trace: List[Dict[str, Any]]) -> Optional[float]:
    """grounded proposals / schema-valid proposals. Grounding rejection
    only - never conflated with malformed LLM output."""
    responses = _llm_repair_responses(_all_i4_results(trace))
    schema_valid = [r for r in responses if (r.get("schema_validation") or {}).get("valid")]
    grounded = sum(1 for r in schema_valid if (r.get("grounding_validation") or {}).get("valid"))
    return _rate(grounded, len(schema_valid))


def end_to_end_valid_grounded_proposal_rate(trace: List[Dict[str, Any]]) -> Optional[float]:
    """grounded proposals / LLM repair responses - the composite of
    proposal_validity_rate() and grounding_pass_rate() over the same base
    population, reported only because both stages are already separately
    available and unambiguous to combine."""
    responses = _llm_repair_responses(_all_i4_results(trace))
    grounded = sum(1 for r in responses if (r.get("grounding_validation") or {}).get("valid"))
    return _rate(grounded, len(responses))


# --- explanation coverage ---------------------------------------------------

def explanation_schema_validity_rate(trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    """valid (status == "success") / records actually explanation-processed
    in THIS run. The denominator is always what was actually executed here
    - never claim 214 unless excluded records were also explicitly run
    through explain_record() in this same invocation (methodology §8)."""
    total = len(trace)
    valid = sum(1 for d in trace if d.get("explanation_status") == "success")
    return {"valid": valid, "processed": total, "rate": _rate(valid, total)}


# --- top-level report --------------------------------------------------------

def compute_all_metrics(
    trace: List[Dict[str, Any]],
    run_id: str,
    expected_record_count: int,
) -> Dict[str, Any]:
    """Assemble the full PRIMARY + SECONDARY metrics report from one raw
    trace. Does not require manual ground truth - classifier and PyPI
    distribution-resolution scoring are separate (scripts/
    manual_ground_truth_scoring.py) since they depend on files that do not
    exist until a human fills them in."""
    records = build_comparison_dataset(trace, run_id)

    return {
        "run_id": run_id,
        "expected_record_count": expected_record_count,
        "actual_record_count": len(records),
        "primary": {
            "system_level_repair_success_rate": system_level_repair_success_rate(records, expected_record_count),
            "round1_repair_success_rate": round1_repair_success_rate(records, expected_record_count),
            "final_repair_success_rate": final_repair_success_rate(records, expected_record_count),
            "additional_notebooks_fixed_by_round2": additional_notebooks_fixed_by_round2(records),
            "absolute_pp_improvement_from_round2": absolute_pp_improvement_from_round2(records, expected_record_count),
        },
        "secondary": {
            "conditional_repair_success_rate": conditional_repair_success_rate(records),
            "targeted_error_resolution_rate": targeted_error_resolution_rate(records),
            "method_only_success_rate": method_only_success_rate(records, expected_record_count),
            "infrastructure_failure_rate": infrastructure_failure_rate(records, expected_record_count),
            "abstention_rate": abstention_rate(records, expected_record_count),
            "proposal_validity_rate": proposal_validity_rate(trace),
            "grounding_pass_rate": grounding_pass_rate(trace),
            "end_to_end_valid_grounded_proposal_rate": end_to_end_valid_grounded_proposal_rate(trace),
            "subtype_level_repair_success": subtype_level_repair_success(records),
            "explanation_schema_validity": explanation_schema_validity_rate(trace),
        },
        "failure_breakdown": failure_breakdown(records),
        "round2_summary": {
            "eligible": sum(1 for r in records if r["round2_eligible"]),
            "attempted": sum(1 for r in records if r["round2_attempted"]),
        },
        "comparison_records": records,
    }
