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


def round1_abstention_count(records: List[Dict[str, Any]]) -> int:
    """Records where Round 1's own i4 result classified as ABSTAINED -
    i.e. the repair agent declined to propose anything in Round 1, before
    any Round 2 could even be considered. Round 2 can never trigger from
    an abstained Round 1 (evaluate_round2_trigger() requires Round-1
    outcome "still_failing", which an abstained record never has), so this
    count is disjoint from round2_abstention_count() by construction."""
    return sum(1 for r in records if r["round1_category"] == ic.ABSTAINED)


def round1_abstention_rate(records: List[Dict[str, Any]], expected_record_count: int) -> Optional[float]:
    """round1_abstention_count() / expected_record_count. Named explicitly
    "round1_" (rather than a bare "abstention_rate") because
    final_state_abstention_rate() below is a DIFFERENT, larger number: it
    also counts notebooks that only abstained in Round 2, after a real
    Round-1 attempt left them still_failing. Do not use this name for that
    quantity, and do not use that quantity for this name."""
    return _rate(round1_abstention_count(records), expected_record_count)


def round2_abstention_count(records: List[Dict[str, Any]]) -> int:
    """Records where Round 2 actually ran (round2_category is not None -
    i.e. the notebook was Round-2-eligible) and Round 2's OWN i4 result
    classified as ABSTAINED: a real second attempt was possible, the
    repair agent was invoked again, and it declined to propose anything
    the second time too. Disjoint from round1_abstention_count() - a
    notebook that abstained in Round 1 never reaches Round 2 at all (see
    round1_abstention_rate())."""
    return sum(1 for r in records if r["round2_category"] == ic.ABSTAINED)


def final_state_abstention_count(records: List[Dict[str, Any]]) -> int:
    """Records whose FINAL classification (Round 2's, if Round 2 ran,
    else Round 1's) is ABSTAINED. Equal to round1_abstention_count() +
    round2_abstention_count() - the two are disjoint populations (a
    Round-1 abstention never reaches Round 2; a Round-2 abstention, by
    definition, did not abstain in Round 1). This is the number
    failure_breakdown()[ic.ABSTAINED] also reports; exposed directly here
    so callers/tables don't have to build the whole breakdown dict just to
    get this one count, and so it sits next to round1_abstention_count for
    an explicit side-by-side comparison."""
    return sum(1 for r in records if r["final_category"] == ic.ABSTAINED)


def final_state_abstention_rate(records: List[Dict[str, Any]], expected_record_count: int) -> Optional[float]:
    """final_state_abstention_count() / expected_record_count. Do not
    confuse with round1_abstention_rate(): this is the larger, post-Round-2
    figure (see docstrings above)."""
    return _rate(final_state_abstention_count(records), expected_record_count)


def round2_non_attempt_reasons(trace: List[Dict[str, Any]]) -> Dict[str, int]:
    """Among Round-2-eligible records that did NOT receive a real
    (i5-completed) Round-2 attempt, tally the exact reason from the raw
    Round-2 trace entry: i4's own status, and - when it abstained - the
    specific retrieval_result.status that caused the abstention (e.g.
    "mapping_unknown"). Answers "why didn't eligible-minus-attempted
    notebooks get a real second repair?" without assuming the answer is
    uniformly one thing."""
    reasons: Dict[str, int] = {}

    def _bump(key: str) -> None:
        reasons[key] = reasons.get(key, 0) + 1

    for diagnostics in trace:
        rounds = diagnostics.get("rounds", [])
        round1_entry = _round_entry(rounds, 1)
        if round1_entry is None:
            continue
        round2_trigger = round1_entry.get("round2_trigger") or {}
        if not round2_trigger.get("triggered"):
            continue

        round2_entry = _round_entry(rounds, 2)
        if _real_attempt(round2_entry) is not None:
            continue  # a real Round-2 attempt happened - not a non-attempt.

        if round2_entry is None:
            _bump("no_round2_trace_entry_despite_eligibility")
            continue

        status = round2_entry.get("status")
        if status != "completed":
            _bump(f"round2_entry_status_{status}")
            continue

        i4_result = round2_entry.get("i4_result") or {}
        i4_status = i4_result.get("status")
        if i4_status == "abstained":
            retrieval_status = (i4_result.get("retrieval_result") or {}).get("status") or "unknown"
            _bump(f"abstained_{retrieval_status}")
        elif i4_status == "failed":
            _bump("infrastructure_failure_llm_or_runtime_fault")
        else:
            _bump(f"unrecognized_i4_status_{i4_status!r}")

    return reasons


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


def grounded_proposal_rate_among_llm_invocations(trace: List[Dict[str, Any]]) -> Optional[float]:
    """grounded proposals / LLM repair responses - the composite of
    proposal_validity_rate() and grounding_pass_rate() over the same base
    population, reported only because both stages are already separately
    available and unambiguous to combine.

    Formerly named "end_to_end_valid_grounded_proposal_rate". That name is
    misleading: the denominator here is LLM repair responses only (i.e.
    _llm_repair_responses() - i4 attempts where retrieval actually resolved
    a candidate and the LLM was invoked), which silently EXCLUDES every
    notebook that abstained before ever reaching the LLM (mapping_unknown,
    unsupported subtype, ineligible, etc.). A pipeline that abstains before
    the LLM on most records can still report 1.0 here while resolving only
    a small fraction of all repair opportunities - see
    overall_grounded_proposal_coverage_rate() for that fraction. Use this
    metric only to answer "when the LLM was actually called, how often did
    it produce something valid and grounded", never as a stand-in for
    "what fraction of all repair opportunities got a good proposal"."""
    responses = _llm_repair_responses(_all_i4_results(trace))
    grounded = sum(1 for r in responses if (r.get("grounding_validation") or {}).get("valid"))
    return _rate(grounded, len(responses))


def overall_grounded_proposal_coverage_rate(trace: List[Dict[str, Any]]) -> Optional[float]:
    """grounded proposals / ALL repair-agent (i4) invocations across both
    rounds - including every pre-LLM abstention (mapping_unknown,
    unsupported subtype, ineligible, etc.), not just the subset that
    reached the LLM. This is the genuinely end-to-end figure: "out of
    every opportunity RAGRepairAgent had to act, in what fraction did it
    end up producing a schema-valid, grounded, non-none proposal."
    Attempt-level (both rounds), matching proposal_validity_rate() and
    grounding_pass_rate()'s own population framing - NOT a per-notebook
    coverage figure. Always <= grounded_proposal_rate_among_llm_invocations()
    over the same trace, since its denominator is a superset."""
    all_i4 = _all_i4_results(trace)
    grounded = sum(1 for r in all_i4 if (r.get("grounding_validation") or {}).get("valid"))
    return _rate(grounded, len(all_i4))


# --- explanation coverage ---------------------------------------------------
#
# Three explanation views, each with an explicit denominator (methodology
# "Explanation metrics"). They are RECORD-level: one explanation record per
# encountered dependency error, regardless of how many LLM attempts
# (retries) that record needed. Retries are reported separately by
# explanation_call_counts() and never inflate a record count.
#
#   A. original_explanation_schema_validity_rate
#        valid original-failure explanations / notebooks processed
#        (one record per notebook; == the pre-Round-2-explanation metric,
#        so it stays directly comparable with the frozen Gemma/Qwen runs)
#   B. round2_explanation_schema_validity_rate
#        valid Round-2 explanations / Round-2 explanation records
#        (one record per newly reclassified Round-2 error that was
#        explained - INCLUDING errors later excluded from repair, which
#        exist in the trace only; never restricted to repair-eligible,
#        LLM-reached, or executed-round populations)
#   C. combined_explanation_schema_validity_rate
#        (A.valid + B.valid) / (A.processed + B.processed)
#
# None of these touches any repair metric: repair-agent invocations are
# counted from i4_result entries only (_all_i4_results), and an
# explanation record is never an i4_result.


def _explanation_status(explanation: Optional[Dict[str, Any]]) -> Optional[str]:
    if not explanation:
        return None
    return (explanation.get("explanation_result") or {}).get("status")


def _explanation_attempts(explanation: Optional[Dict[str, Any]]) -> int:
    """Underlying LLM attempts (including the explainer's own bounded
    retries) behind ONE explanation record. 0 when unavailable (e.g. a
    render failure that never reached the model)."""
    if not explanation:
        return 0
    return int((explanation.get("explanation_result") or {}).get("attempts") or 0)


def original_explanation(diagnostics: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The Round-1 explanation of the ORIGINAL failure: the top-level
    `explanation` record, which scripts/run_pipeline.py keeps at the top
    level for exactly this purpose (and mirrors, as the same record, onto
    the Round-1 entry - never counted twice)."""
    return diagnostics.get("explanation")


def round2_explanation(diagnostics: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The single Round-2 explanation record for one notebook, or None.

    Authoritative location: rounds[0].round2_trigger.explanation - the
    orchestrator attaches the explanation there whenever a genuinely new
    error was reclassified into a round2_record and explained, whether or
    not that error then proved repair-eligible. For a non-repairable new
    error (system_library, mapping_unknown, ...) this is the ONLY place the
    explanation exists: no Round-2 round entry and no repair_attempts row
    are written for it, so the trace is the authoritative source.

    When Round 2 did execute, the executed Round-2 entry carries the same
    record again (rounds[1].explanation). That duplicate representation is
    deliberately NOT a second explanation: this function returns exactly
    one record per notebook, preferring the trigger's copy and falling back
    to the executed entry's only if the trigger lacks one. Old traces
    (frozen I8/I9 runs, produced before Round-2 explanations existed)
    have neither and yield None, so every Round-2 count is 0 for them."""
    rounds = diagnostics.get("rounds", [])
    round1_entry = _round_entry(rounds, 1)
    trigger = (round1_entry or {}).get("round2_trigger") or {}
    explanation = trigger.get("explanation")
    if explanation is not None:
        return explanation
    round2_entry = _round_entry(rounds, 2)
    if round2_entry is not None:
        return round2_entry.get("explanation")
    return None


def _reclassified_new_error(diagnostics: Dict[str, Any]) -> bool:
    """True if Round 1 exposed a genuinely new error that the orchestrator
    reclassified into a round2_record (regardless of repair eligibility)."""
    rounds = diagnostics.get("rounds", [])
    round1_entry = _round_entry(rounds, 1)
    trigger = (round1_entry or {}).get("round2_trigger") or {}
    return "round2_record" in trigger


def _validity_block(explanations: List[Dict[str, Any]]) -> Dict[str, Any]:
    valid = sum(1 for e in explanations if _explanation_status(e) == "success")
    processed = len(explanations)
    return {"valid": valid, "failed": processed - valid, "processed": processed, "rate": _rate(valid, processed)}


def original_explanation_schema_validity_rate(trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A. valid original-failure explanations / notebooks processed in THIS
    run (one explanation record per notebook, read from the top-level
    explanation_status exactly as before Round-2 explanations existed, so
    the number is directly comparable with the frozen Gemma/Qwen runs).
    The denominator is always what was actually executed here - never
    claim 214 unless excluded records were also explicitly run through
    explain_record() in this same invocation (methodology §8)."""
    total = len(trace)
    valid = sum(1 for d in trace if d.get("explanation_status") == "success")
    return {"valid": valid, "failed": total - valid, "processed": total, "rate": _rate(valid, total)}


def explanation_schema_validity_rate(trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Backward-compatible alias of original_explanation_schema_validity_rate()
    (metric A) under the name, and with the exact {valid, processed, rate}
    shape, that every pre-Round-2-explanation report used (frozen I8/I9
    summary CSVs serialise this dict verbatim). Meaning and denominator are
    unchanged: original-failure explanations over notebooks processed. It
    does NOT include Round-2 explanations - use round2_/combined_ for those."""
    block = original_explanation_schema_validity_rate(trace)
    return {"valid": block["valid"], "processed": block["processed"], "rate": block["rate"]}


def round2_explanation_schema_validity_rate(trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    """B. valid Round-2 explanations / Round-2 explanation records. The
    denominator is every newly reclassified Round-2 dependency error that
    received an explanation record (success OR failed), including errors
    later excluded from repair that exist only in the trace. It is not the
    repair-eligible subset, not the Round-2-LLM-reached subset, and not the
    executed-Round-2-row subset. Counted once per notebook via
    round2_explanation()."""
    explanations = [e for e in (round2_explanation(d) for d in trace) if e is not None]
    block = _validity_block(explanations)
    # Population diagnostics: how the explained Round-2 errors split by
    # repair eligibility (explanation scope is broader than repair scope),
    # and whether any reclassified error somehow went unexplained.
    triggered = not_triggered = 0
    reclassified = 0
    for d in trace:
        if not _reclassified_new_error(d):
            continue
        reclassified += 1
        trig = (_round_entry(d.get("rounds", []), 1) or {}).get("round2_trigger") or {}
        if round2_explanation(d) is None:
            continue
        if trig.get("triggered"):
            triggered += 1
        else:
            not_triggered += 1
    block["reclassified_new_errors"] = reclassified
    block["reclassified_without_explanation"] = reclassified - block["processed"]
    block["explained_repair_eligible"] = triggered
    block["explained_not_repair_eligible_trace_only"] = not_triggered
    return block


def combined_explanation_schema_validity_rate(trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    """C. (valid original + valid Round-2) / (original records + Round-2
    records). A descriptive total-reliability figure for the explanation
    component; it never replaces metric A, whose notebook-level denominator
    is the comparable one."""
    original = original_explanation_schema_validity_rate(trace)
    round2 = round2_explanation_schema_validity_rate(trace)
    valid = original["valid"] + round2["valid"]
    processed = original["processed"] + round2["processed"]
    return {"valid": valid, "failed": processed - valid, "processed": processed, "rate": _rate(valid, processed)}


def explanation_call_counts(trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Explanation RECORDS versus underlying LLM ATTEMPTS, kept apart.
    `*_records` are what the validity rates are computed over (one per
    encountered error). `*_llm_attempts` sum each record's own `attempts`
    field, so a record that needed the explainer's bounded retry counts
    once as a record and twice (or more) as attempts. Never use attempts
    as a validity denominator."""
    originals = [e for e in (original_explanation(d) for d in trace) if e is not None]
    round2s = [e for e in (round2_explanation(d) for d in trace) if e is not None]
    original_attempts = sum(_explanation_attempts(e) for e in originals)
    round2_attempts = sum(_explanation_attempts(e) for e in round2s)
    return {
        "original_records": len(trace),
        "round2_records": len(round2s),
        "total_records": len(trace) + len(round2s),
        "original_llm_attempts": original_attempts,
        "round2_llm_attempts": round2_attempts,
        "total_llm_attempts": original_attempts + round2_attempts,
        "records_with_retry": sum(1 for e in originals + round2s if _explanation_attempts(e) > 1),
    }


def explanation_metrics(trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    """All three explanation views plus the record/attempt counts, in one
    block. Kept separate from every repair metric in compute_all_metrics()."""
    return {
        "original_explanation_schema_validity": original_explanation_schema_validity_rate(trace),
        "round2_explanation_schema_validity": round2_explanation_schema_validity_rate(trace),
        "combined_explanation_schema_validity": combined_explanation_schema_validity_rate(trace),
        "call_counts": explanation_call_counts(trace),
        "note": (
            "Record-level schema validity (one record per encountered dependency error). "
            "A: original failures / notebooks processed - comparable with pre-Round-2-explanation runs. "
            "B: Round-2 explanations / newly reclassified Round-2 errors that were explained, INCLUDING "
            "non-repairable ones that exist in the trace only. C: A+B combined. Retries are counted in "
            "call_counts.*_llm_attempts, never as extra records. None of these are human-evaluated; the "
            "human study covered original-failure explanations only."
        ),
    }


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
            "round1_abstention_count": round1_abstention_count(records),
            "round1_abstention_rate": round1_abstention_rate(records, expected_record_count),
            "round2_abstention_count": round2_abstention_count(records),
            "final_state_abstention_count": final_state_abstention_count(records),
            "final_state_abstention_rate": final_state_abstention_rate(records, expected_record_count),
            "proposal_validity_rate": proposal_validity_rate(trace),
            "grounding_pass_rate": grounding_pass_rate(trace),
            "grounded_proposal_rate_among_llm_invocations": grounded_proposal_rate_among_llm_invocations(trace),
            "overall_grounded_proposal_coverage_rate": overall_grounded_proposal_coverage_rate(trace),
            "subtype_level_repair_success": subtype_level_repair_success(records),
            # Backward-compatible alias of explanation.original_explanation_
            # schema_validity (metric A): the ORIGINAL-failure explanation
            # rate over notebooks processed, exactly as every frozen I8/I9
            # report computed it. Round-2 explanations are reported under
            # "explanation" below, never folded into this number.
            "explanation_schema_validity": explanation_schema_validity_rate(trace),
        },
        # Explanation component metrics, deliberately separate from the
        # repair metrics above: a Round-2 explanation call is never a
        # repair-agent invocation, and nothing here feeds any repair rate.
        "explanation": explanation_metrics(trace),
        "failure_breakdown": failure_breakdown(records),
        "round2_summary": {
            "eligible": sum(1 for r in records if r["round2_eligible"]),
            "attempted": sum(1 for r in records if r["round2_attempted"]),
            "abstained": round2_abstention_count(records),
            "proposal_generated": sum(1 for r in records if r["round2_action"] not in (None, "none")),
            "fixed": sum(1 for r in records if r["round2_category"] == ic.FIXED),
            "still_failing": sum(1 for r in records if r["round2_category"] == ic.STILL_FAILING),
            "infrastructure_failure": sum(1 for r in records if r["round2_category"] == ic.INFRASTRUCTURE_FAILURE),
            "method_failure": sum(1 for r in records if r["round2_category"] == ic.METHOD_FAILURE),
            "non_attempt_reasons": round2_non_attempt_reasons(trace),
        },
        "comparison_records": records,
    }
