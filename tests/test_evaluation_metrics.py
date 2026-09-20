import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluation_metrics as em
import infra_classification as ic


# --- fixture builders ---------------------------------------------------------

def make_i4(status="success", subtype="missing_package", failing_module="sklearn", action="install", schema_valid=None, grounding_valid=None, retrieval_status=None, eligibility="usable"):
    return {
        "status": status,
        "eligibility": {"decision": eligibility},
        "input": {"refined_subtype": subtype, "failing_module": failing_module},
        "final_action": action,
        "retrieval_result": {"status": retrieval_status} if retrieval_status else None,
        "schema_validation": {"valid": schema_valid} if schema_valid is not None else None,
        "grounding_validation": {"valid": grounding_valid} if grounding_valid is not None else None,
    }


def make_i5(outcome, same_as_original_error=False, new_error_type="SomeError"):
    return {
        "status": "completed",
        "outcome": outcome,
        "new_error_type": new_error_type if outcome == "still_failing" else None,
        "same_as_original_error": same_as_original_error,
    }


def make_round(round_number, i4_result=None, i5_result=None, status="completed", round2_trigger=None, error=None):
    entry = {"round": round_number, "status": status}
    if i4_result is not None:
        entry["i4_result"] = i4_result
    if i5_result is not None:
        entry["i5_result"] = i5_result
    if round2_trigger is not None:
        entry["round2_trigger"] = round2_trigger
    if error is not None:
        entry["error"] = error
    return entry


def make_diagnostics(notebook_execution_id, rounds, explanation_status="success"):
    return {
        "notebook_execution_id": notebook_execution_id,
        "explanation_status": explanation_status,
        "rounds": rounds,
    }


def not_triggered(reason="round1_outcome_not_still_failing"):
    return {"triggered": False, "reason": reason}


def triggered():
    return {"triggered": True, "reason": "new_dependency_error_eligible"}


# --- build_comparison_record: final-outcome / round-1 derivation --------------

def test_comparison_record_fixed_round1_no_round2():
    diagnostics = make_diagnostics(
        8, [make_round(1, make_i4(action="install"), make_i5("fixed"), round2_trigger=not_triggered())]
    )
    record = em.build_comparison_record(diagnostics, "run-1")
    assert record["round1_category"] == ic.FIXED
    assert record["final_category"] == ic.FIXED
    assert record["round2_eligible"] is False
    assert record["round2_attempted"] is False
    assert record["additional_fix_from_round2"] is False


def test_comparison_record_still_failing_round1_no_round2_trigger():
    diagnostics = make_diagnostics(
        8,
        [
            make_round(
                1,
                make_i4(action="pin_version"),
                make_i5("still_failing", same_as_original_error=True),
                round2_trigger=not_triggered("same_as_original_error"),
            )
        ],
    )
    record = em.build_comparison_record(diagnostics, "run-1")
    assert record["round1_category"] == ic.STILL_FAILING
    assert record["final_category"] == ic.STILL_FAILING
    assert record["round2_eligible"] is False


def test_comparison_record_round2_eligible_and_attempted_fixes_notebook():
    diagnostics = make_diagnostics(
        174,
        [
            make_round(
                1,
                make_i4(action="pin_version", subtype="wrong_version", failing_module="scipy"),
                make_i5("still_failing", same_as_original_error=False, new_error_type="ModuleNotFoundError"),
                round2_trigger=triggered(),
            ),
            make_round(2, make_i4(action="install", subtype="missing_package", failing_module="tf_keras"), make_i5("fixed")),
        ],
    )
    record = em.build_comparison_record(diagnostics, "run-1")
    assert record["round1_category"] == ic.STILL_FAILING
    assert record["round2_eligible"] is True
    assert record["round2_attempted"] is True
    assert record["round2_category"] == ic.FIXED
    assert record["final_category"] == ic.FIXED
    assert record["additional_fix_from_round2"] is True


def test_comparison_record_round2_eligible_but_still_fails_is_not_an_additional_fix():
    diagnostics = make_diagnostics(
        174,
        [
            make_round(
                1,
                make_i4(action="pin_version"),
                make_i5("still_failing", same_as_original_error=False, new_error_type="ModuleNotFoundError"),
                round2_trigger=triggered(),
            ),
            make_round(2, make_i4(action="install"), make_i5("still_failing", same_as_original_error=True)),
        ],
    )
    record = em.build_comparison_record(diagnostics, "run-1")
    assert record["final_category"] == ic.STILL_FAILING
    assert record["additional_fix_from_round2"] is False


def test_comparison_record_abstained_round1_never_has_round2():
    diagnostics = make_diagnostics(8, [make_round(1, make_i4(status="abstained", action="none"), None)])
    record = em.build_comparison_record(diagnostics, "run-1")
    assert record["round1_category"] == ic.ABSTAINED
    assert record["round2_eligible"] is False
    assert record["round2_attempted"] is False


def test_comparison_record_excluded_record():
    diagnostics = make_diagnostics(
        15, [make_round(1, make_i4(status="abstained", eligibility="excluded"), None, status="excluded")]
    )
    record = em.build_comparison_record(diagnostics, "run-1")
    assert record["round1_category"] == ic.EXCLUDED
    assert record["final_category"] == ic.EXCLUDED


def test_comparison_record_infrastructure_failure_in_round1():
    diagnostics = make_diagnostics(9, [make_round(1, status="component_error", error="ConnectionError: boom")])
    record = em.build_comparison_record(diagnostics, "run-1")
    assert record["round1_category"] == ic.INFRASTRUCTURE_FAILURE
    assert record["infrastructure_failure"] is True


def test_comparison_record_infrastructure_failure_flagged_even_if_only_round2():
    diagnostics = make_diagnostics(
        174,
        [
            make_round(
                1,
                make_i4(action="pin_version"),
                make_i5("still_failing", same_as_original_error=False, new_error_type="X"),
                round2_trigger=triggered(),
            ),
            make_round(2, status="component_error", error="Docker build failed"),
        ],
    )
    record = em.build_comparison_record(diagnostics, "run-1")
    assert record["infrastructure_failure"] is True


# --- targeted error resolution flags -------------------------------------------

def test_targeted_error_resolved_true_when_fixed():
    diagnostics = make_diagnostics(8, [make_round(1, make_i4(), make_i5("fixed"), round2_trigger=not_triggered())])
    record = em.build_comparison_record(diagnostics, "run-1")
    assert record["targeted_error_resolved_round1"] is True


def test_targeted_error_resolved_true_when_still_failing_on_different_error():
    diagnostics = make_diagnostics(
        174,
        [
            make_round(
                1,
                make_i4(),
                make_i5("still_failing", same_as_original_error=False, new_error_type="ModuleNotFoundError"),
                round2_trigger=triggered(),
            )
        ],
    )
    record = em.build_comparison_record(diagnostics, "run-1")
    assert record["targeted_error_resolved_round1"] is True


def test_targeted_error_resolved_false_when_still_failing_on_same_error():
    diagnostics = make_diagnostics(
        8, [make_round(1, make_i4(), make_i5("still_failing", same_as_original_error=True), round2_trigger=not_triggered())]
    )
    record = em.build_comparison_record(diagnostics, "run-1")
    assert record["targeted_error_resolved_round1"] is False


def test_targeted_error_resolved_none_when_no_real_attempt():
    diagnostics = make_diagnostics(8, [make_round(1, make_i4(status="abstained", action="none"), None)])
    record = em.build_comparison_record(diagnostics, "run-1")
    assert record["targeted_error_resolved_round1"] is None


def test_targeted_error_resolved_false_for_apply_error():
    i5 = {"status": "completed", "outcome": "apply_error", "failure_stage": "clone"}
    diagnostics = make_diagnostics(8, [make_round(1, make_i4(), i5, round2_trigger=not_triggered())])
    record = em.build_comparison_record(diagnostics, "run-1")
    assert record["targeted_error_resolved_round1"] is False


# --- PRIMARY metrics ------------------------------------------------------------

def _records_for_five_notebooks():
    """3 fixed at round 1, 1 still_failing (no round2 trigger), 1 excluded."""
    trace = [
        make_diagnostics(1, [make_round(1, make_i4(), make_i5("fixed"), round2_trigger=not_triggered())]),
        make_diagnostics(2, [make_round(1, make_i4(), make_i5("fixed"), round2_trigger=not_triggered())]),
        make_diagnostics(3, [make_round(1, make_i4(), make_i5("fixed"), round2_trigger=not_triggered())]),
        make_diagnostics(
            4,
            [make_round(1, make_i4(), make_i5("still_failing", same_as_original_error=True), round2_trigger=not_triggered())],
        ),
        make_diagnostics(5, [make_round(1, make_i4(status="abstained", eligibility="excluded"), None, status="excluded")]),
    ]
    return em.build_comparison_dataset(trace, "run-1")


def test_system_level_repair_success_rate_uses_expected_record_count_not_hardcoded():
    records = _records_for_five_notebooks()
    assert em.system_level_repair_success_rate(records, 5) == 3 / 5
    # Same records, different expected_record_count (e.g. a differently-sized
    # dev split) - must scale, never assume 187 or any other constant.
    assert em.system_level_repair_success_rate(records, 10) == 3 / 10


def test_round1_repair_success_rate():
    records = _records_for_five_notebooks()
    assert em.round1_repair_success_rate(records, 5) == 3 / 5


def test_final_repair_success_rate_equals_system_level():
    records = _records_for_five_notebooks()
    assert em.final_repair_success_rate(records, 5) == em.system_level_repair_success_rate(records, 5)


def test_additional_notebooks_fixed_by_round2():
    trace = [
        make_diagnostics(
            174,
            [
                make_round(
                    1,
                    make_i4(),
                    make_i5("still_failing", same_as_original_error=False, new_error_type="X"),
                    round2_trigger=triggered(),
                ),
                make_round(2, make_i4(), make_i5("fixed")),
            ],
        ),
        make_diagnostics(8, [make_round(1, make_i4(), make_i5("fixed"), round2_trigger=not_triggered())]),
    ]
    records = em.build_comparison_dataset(trace, "run-1")
    assert em.additional_notebooks_fixed_by_round2(records) == 1


def test_absolute_pp_improvement_from_round2_is_positive_when_round2_helps():
    trace = [
        make_diagnostics(
            174,
            [
                make_round(
                    1,
                    make_i4(),
                    make_i5("still_failing", same_as_original_error=False, new_error_type="X"),
                    round2_trigger=triggered(),
                ),
                make_round(2, make_i4(), make_i5("fixed")),
            ],
        )
    ]
    records = em.build_comparison_dataset(trace, "run-1")
    improvement = em.absolute_pp_improvement_from_round2(records, 1)
    assert improvement == 1.0  # 0% round1 -> 100% final


# --- SECONDARY metrics -----------------------------------------------------------

def test_conditional_repair_success_rate_excludes_abstained_and_excluded():
    records = _records_for_five_notebooks()
    # attempted = notebooks 1,2,3 (fixed) + 4 (still_failing) = 4 attempted; 3 fixed
    assert em.conditional_repair_success_rate(records) == 3 / 4


def test_targeted_error_resolution_rate_is_attempt_level_not_notebook_level():
    trace = [
        make_diagnostics(
            174,
            [
                make_round(
                    1,
                    make_i4(),
                    make_i5("still_failing", same_as_original_error=False, new_error_type="X"),
                    round2_trigger=triggered(),
                ),
                make_round(2, make_i4(), make_i5("fixed")),
            ],
        )
    ]
    records = em.build_comparison_dataset(trace, "run-1")
    # Both round-1 (targeted error resolved: True, different error) and
    # round-2 (fixed: True) attempts count - denominator is 2, not 1.
    assert em.targeted_error_resolution_rate(records) == 1.0
    resolved_flags = [records[0]["targeted_error_resolved_round1"], records[0]["targeted_error_resolved_round2"]]
    assert resolved_flags == [True, True]


def test_method_only_success_rate_excludes_infra_failures_from_denominator():
    trace = [
        make_diagnostics(1, [make_round(1, make_i4(), make_i5("fixed"), round2_trigger=not_triggered())]),
        make_diagnostics(2, [make_round(1, status="component_error", error="boom")]),
    ]
    records = em.build_comparison_dataset(trace, "run-1")
    # system-level: 1 fixed / 2 total = 0.5; method-only: 1 fixed / (2-1 infra) = 1.0
    assert em.system_level_repair_success_rate(records, 2) == 0.5
    assert em.method_only_success_rate(records, 2) == 1.0


def test_infrastructure_failure_rate():
    trace = [
        make_diagnostics(1, [make_round(1, make_i4(), make_i5("fixed"), round2_trigger=not_triggered())]),
        make_diagnostics(2, [make_round(1, status="component_error", error="boom")]),
    ]
    records = em.build_comparison_dataset(trace, "run-1")
    assert em.infrastructure_failure_rate(records, 2) == 0.5


def test_round1_abstention_rate():
    records = _records_for_five_notebooks()
    trace_with_abstention = em.build_comparison_dataset(
        [make_diagnostics(6, [make_round(1, make_i4(status="abstained", action="none"), None)])], "run-1"
    )
    combined = records + trace_with_abstention
    assert em.round1_abstention_count(combined) == 1
    assert em.round1_abstention_rate(combined, 6) == 1 / 6


def test_round1_abstention_count_and_round2_abstention_count_are_disjoint():
    """A notebook that abstains in Round 1 never reaches Round 2 (no
    round2_trigger can fire from an abstained Round-1 outcome); a notebook
    that abstains in Round 2 had a real, non-abstained Round-1 attempt
    that left it still_failing. round1_abstention_count and
    round2_abstention_count must never double-count the same notebook."""
    trace = [
        # Round-1 abstention - never becomes Round-2 eligible.
        make_diagnostics(1, [make_round(1, make_i4(status="abstained", action="none"), None)]),
        # Round-1 real attempt (still_failing) -> Round-2 eligible -> Round-2 itself abstains.
        make_diagnostics(
            2,
            [
                make_round(
                    1,
                    make_i4(action="install"),
                    make_i5("still_failing", same_as_original_error=False, new_error_type="X"),
                    round2_trigger=triggered(),
                ),
                make_round(2, make_i4(status="abstained", action="none", retrieval_status="mapping_unknown"), None),
            ],
        ),
    ]
    records = em.build_comparison_dataset(trace, "run-1")
    assert em.round1_abstention_count(records) == 1
    assert em.round2_abstention_count(records) == 1
    assert em.final_state_abstention_count(records) == 2
    assert em.final_state_abstention_rate(records, 2) == 1.0


def test_round2_non_attempt_reasons_identifies_mapping_unknown():
    trace = [
        make_diagnostics(
            2,
            [
                make_round(
                    1,
                    make_i4(action="install"),
                    make_i5("still_failing", same_as_original_error=False, new_error_type="X"),
                    round2_trigger=triggered(),
                ),
                make_round(2, make_i4(status="abstained", action="none", retrieval_status="mapping_unknown"), None),
            ],
        )
    ]
    reasons = em.round2_non_attempt_reasons(trace)
    assert reasons == {"abstained_mapping_unknown": 1}


def test_round2_non_attempt_reasons_excludes_real_attempts():
    trace = [
        make_diagnostics(
            174,
            [
                make_round(
                    1,
                    make_i4(),
                    make_i5("still_failing", same_as_original_error=False, new_error_type="X"),
                    round2_trigger=triggered(),
                ),
                make_round(2, make_i4(), make_i5("fixed")),
            ],
        )
    ]
    assert em.round2_non_attempt_reasons(trace) == {}


def test_subtype_level_repair_success_uses_actual_run_counts():
    trace = [
        make_diagnostics(
            1, [make_round(1, make_i4(subtype="missing_package"), make_i5("fixed"), round2_trigger=not_triggered())]
        ),
        make_diagnostics(
            2,
            [
                make_round(
                    1,
                    make_i4(subtype="missing_package"),
                    make_i5("still_failing", same_as_original_error=True),
                    round2_trigger=not_triggered(),
                )
            ],
        ),
        make_diagnostics(
            3,
            [make_round(1, make_i4(subtype="wrong_version"), make_i5("fixed"), round2_trigger=not_triggered())],
        ),
    ]
    records = em.build_comparison_dataset(trace, "run-1")
    breakdown = em.subtype_level_repair_success(records)
    assert breakdown["missing_package"] == {"eligible": 2, "fixed": 1, "rate": 0.5}
    assert breakdown["wrong_version"] == {"eligible": 1, "fixed": 1, "rate": 1.0}


def test_failure_breakdown_counts_every_category():
    records = _records_for_five_notebooks()
    breakdown = em.failure_breakdown(records)
    assert breakdown[ic.FIXED] == 3
    assert breakdown[ic.STILL_FAILING] == 1
    assert breakdown[ic.EXCLUDED] == 1


# --- proposal validity / grounding pass rate (attempt-level, raw trace) --------

def test_proposal_validity_rate_excludes_pre_llm_abstentions():
    trace = [
        # abstained before any LLM call - schema_validation is None, must not count.
        make_diagnostics(1, [make_round(1, make_i4(status="abstained", schema_valid=None), None)]),
        # a real LLM call that produced invalid JSON.
        make_diagnostics(2, [make_round(1, make_i4(status="abstained", schema_valid=False), None)]),
        # a real LLM call that produced a schema-valid proposal.
        make_diagnostics(3, [make_round(1, make_i4(status="success", schema_valid=True, grounding_valid=True), make_i5("fixed"))]),
    ]
    # denominator: only notebooks 2 and 3 made an actual LLM call -> 1/2 valid
    assert em.proposal_validity_rate(trace) == 1 / 2


def test_grounding_pass_rate_only_over_schema_valid_proposals():
    trace = [
        make_diagnostics(1, [make_round(1, make_i4(status="abstained", schema_valid=True, grounding_valid=False), None)]),
        make_diagnostics(2, [make_round(1, make_i4(status="success", schema_valid=True, grounding_valid=True), make_i5("fixed"))]),
    ]
    assert em.grounding_pass_rate(trace) == 1 / 2


def test_grounded_proposal_rate_among_llm_invocations():
    trace = [
        make_diagnostics(1, [make_round(1, make_i4(status="abstained", schema_valid=False), None)]),
        make_diagnostics(2, [make_round(1, make_i4(status="abstained", schema_valid=True, grounding_valid=False), None)]),
        make_diagnostics(3, [make_round(1, make_i4(status="success", schema_valid=True, grounding_valid=True), make_i5("fixed"))]),
    ]
    # 3 LLM responses total, only 1 both schema-valid and grounded
    assert em.grounded_proposal_rate_among_llm_invocations(trace) == 1 / 3


def test_overall_grounded_proposal_coverage_rate_denominator_includes_pre_llm_abstentions():
    trace = [
        # pre-LLM abstention (mapping_unknown) - schema_validation is None,
        # never reaches the LLM at all, but IS a repair-agent invocation.
        make_diagnostics(1, [make_round(1, make_i4(status="abstained", schema_valid=None, retrieval_status="mapping_unknown"), None)]),
        make_diagnostics(2, [make_round(1, make_i4(status="abstained", schema_valid=False), None)]),
        make_diagnostics(3, [make_round(1, make_i4(status="success", schema_valid=True, grounding_valid=True), make_i5("fixed"))]),
    ]
    # Denominator is ALL i4 attempts (3), not just the 2 that reached the LLM -
    # this is what distinguishes it from grounded_proposal_rate_among_llm_invocations.
    assert em.overall_grounded_proposal_coverage_rate(trace) == 1 / 3
    assert em.grounded_proposal_rate_among_llm_invocations(trace) == 1 / 2
    # A pipeline that abstains pre-LLM on most records can show a perfect
    # LLM-conditional rate while overall coverage stays low - verify the two
    # numbers can genuinely diverge, not just differ by construction above.
    trace_mostly_pre_llm_abstained = trace + [
        make_diagnostics(4, [make_round(1, make_i4(status="abstained", schema_valid=None, retrieval_status="mapping_unknown"), None)]),
        make_diagnostics(5, [make_round(1, make_i4(status="abstained", schema_valid=None, retrieval_status="mapping_unknown"), None)]),
    ]
    assert em.grounded_proposal_rate_among_llm_invocations(trace_mostly_pre_llm_abstained) == 1 / 2
    assert em.overall_grounded_proposal_coverage_rate(trace_mostly_pre_llm_abstained) == 1 / 5


# --- explanation coverage -------------------------------------------------------

def test_explanation_schema_validity_rate_denominator_is_actual_processed_count():
    trace = [
        make_diagnostics(1, [make_round(1, make_i4(), make_i5("fixed"), round2_trigger=not_triggered())], explanation_status="success"),
        make_diagnostics(2, [make_round(1, make_i4(), make_i5("fixed"), round2_trigger=not_triggered())], explanation_status="failed"),
    ]
    result = em.explanation_schema_validity_rate(trace)
    assert result == {"valid": 1, "processed": 2, "rate": 0.5}


# --- top-level report -------------------------------------------------------------

def test_compute_all_metrics_uses_manifest_expected_count_not_a_literal():
    trace = [make_diagnostics(1, [make_round(1, make_i4(), make_i5("fixed"), round2_trigger=not_triggered())])]
    report = em.compute_all_metrics(trace, "run-1", expected_record_count=13)
    assert report["expected_record_count"] == 13
    assert report["primary"]["system_level_repair_success_rate"] == 1 / 13


def test_compute_all_metrics_round1_and_round2_abstention_counts_sum_to_final_state():
    """Regression test for the 126-vs-162 ambiguity: whatever
    round1_abstention_count and round2_abstention_count are on a given
    trace, they must always sum to final_state_abstention_count (and thus
    to failure_breakdown()[ic.ABSTAINED]) - the two counts are a partition
    of the final-state abstention population, never overlapping or
    incomplete."""
    trace = [
        # Round-1 abstention (mapping_unknown before any LLM call).
        make_diagnostics(1, [make_round(1, make_i4(status="abstained", action="none", retrieval_status="mapping_unknown"), None)]),
        make_diagnostics(2, [make_round(1, make_i4(status="abstained", action="none", retrieval_status="mapping_unknown"), None)]),
        # Round-1 real attempt, fixed - no abstention anywhere.
        make_diagnostics(3, [make_round(1, make_i4(), make_i5("fixed"), round2_trigger=not_triggered())]),
        # Round-1 real attempt (still_failing) -> Round-2 eligible -> Round-2 abstains (mapping_unknown again).
        make_diagnostics(
            4,
            [
                make_round(
                    1,
                    make_i4(action="install"),
                    make_i5("still_failing", same_as_original_error=False, new_error_type="X"),
                    round2_trigger=triggered(),
                ),
                make_round(2, make_i4(status="abstained", action="none", retrieval_status="mapping_unknown"), None),
            ],
        ),
        # Round-1 real attempt (still_failing) -> Round-2 eligible -> Round-2 real attempt, fixed.
        make_diagnostics(
            5,
            [
                make_round(
                    1,
                    make_i4(action="install"),
                    make_i5("still_failing", same_as_original_error=False, new_error_type="X"),
                    round2_trigger=triggered(),
                ),
                make_round(2, make_i4(), make_i5("fixed")),
            ],
        ),
    ]
    report = em.compute_all_metrics(trace, "run-1", expected_record_count=5)
    secondary = report["secondary"]
    assert secondary["round1_abstention_count"] == 2
    assert secondary["round2_abstention_count"] == 1
    assert secondary["final_state_abstention_count"] == 3
    assert secondary["final_state_abstention_count"] == (
        secondary["round1_abstention_count"] + secondary["round2_abstention_count"]
    )
    assert report["failure_breakdown"][ic.ABSTAINED] == 3
    assert report["round2_summary"]["eligible"] == 2
    assert report["round2_summary"]["attempted"] == 1
    assert report["round2_summary"]["abstained"] == 1
    assert report["round2_summary"]["proposal_generated"] == 1
    assert report["round2_summary"]["fixed"] == 1
    assert report["round2_summary"]["non_attempt_reasons"] == {"abstained_mapping_unknown": 1}
