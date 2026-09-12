#!/usr/bin/env python3

"""Centralized infrastructure-vs-method failure classification (i8), per
the frozen I8 evaluation methodology.

Governing principle (fixed before the evaluation run, never relaxed after
seeing results): when a case is ambiguous, classify it as a METHOD failure,
not an INFRASTRUCTURE failure. The opposite default would let
"infrastructure" absorb awkward cases and artificially inflate a
method-only success rate - exactly the misleading number the methodology
is designed to avoid.

This is the ONLY place this rule is implemented. Reporting/metrics code
(scripts/evaluation_metrics.py) must call into this module rather than
re-deriving the rule from raw failure_stage/execution_status/status fields
itself.

One round's outcome (from scripts/run_pipeline.py's own per-record trace
entry, which nests the exact i4_result/i5_result dicts produced by
scripts/rag_repair_agent.py and scripts/fix_applicator.py) is classified
into exactly one of:

  FIXED                 - i5 outcome == "fixed"
  STILL_FAILING         - i5 outcome == "still_failing"
  ABSTAINED             - i4 deliberately proposed no repair, for a
                           reason that reflects a genuine method limit
                           (unmapped/nonexistent package, ungrounded LLM
                           proposal, explicit action "none"), not an
                           environment fault
  INFRASTRUCTURE_FAILURE - an environment/tooling fault prevented a fair
                           trial of the method (LLM/Ollama unavailable,
                           PyPI network/response fault, git/Docker
                           clone/checkout/build/timeout fault, dataset-join
                           bookkeeping fault, an uncaught orchestrator
                           exception)
  METHOD_FAILURE        - a repair was proposed and grounded, but its
                           application could not be fairly judged for a
                           reason NOT unambiguously attributable to
                           infrastructure (pip install itself failed inside
                           the container, the notebook could not be found,
                           the container exited nonzero for an unclear
                           reason, or the output notebook could not be
                           read back) - conservative default per the
                           governing principle above
  EXCLUDED              - the record was never repair-eligible in the
                           first place (scope_status != "usable"); outside
                           the repair-success denominator entirely
"""

from typing import Any, Dict, Optional


FIXED = "fixed"
STILL_FAILING = "still_failing"
ABSTAINED = "abstained"
INFRASTRUCTURE_FAILURE = "infrastructure_failure"
METHOD_FAILURE = "method_failure"
EXCLUDED = "excluded"
UNKNOWN = "unknown"

ALL_CATEGORIES = {
    FIXED,
    STILL_FAILING,
    ABSTAINED,
    INFRASTRUCTURE_FAILURE,
    METHOD_FAILURE,
    EXCLUDED,
    UNKNOWN,
}

# i4 RAGRepairAgent retrieval statuses that indicate an environment/network
# fault rather than a genuine "this package/version does not exist" or
# "this import name has no known distribution mapping" finding. See
# scripts/pypi_retriever.py's fetch_pypi_project()/retrieve().
INFRA_RETRIEVAL_STATUSES = {"network_error", "invalid_response", "configuration_error"}

# i4 statuses whose abstention reflects a genuine method limit, not an
# environment fault: the import name has no known PyPI distribution
# mapping, the resolved distribution genuinely does not exist on PyPI, no
# release is compatible with the pinned runtime, the LLM's own proposal
# failed grounding validation, or the LLM explicitly proposed no fix.
METHOD_RETRIEVAL_STATUSES = {"mapping_unknown", "package_not_found", "no_compatible_release"}

# i5 FixApplicator apply_error failure_stage values that are unambiguous
# environment/tooling faults (git/Docker/timeout), plus the two pre-Docker
# bookkeeping stages ("join": i4-to-i2 dataset join failure; "validation":
# i4 output re-validation failure) - both reflect a pipeline-plumbing fault
# on this specific attempt, not a repair-quality judgment.
INFRA_APPLY_ERROR_STAGES = {"clone", "checkout", "build", "timeout", "join", "validation"}

# i5 execution_status values reached only after the container actually ran:
# each is a real, but not unambiguously infrastructure-attributable, application
# failure. Conservative default (per the governing principle): stays in the
# method-failure bucket rather than infrastructure.
METHOD_EXECUTION_STATUSES = {
    "fix_install_failed",
    "notebook_not_found",
    "docker_run_failed",
    "output_notebook_missing",
}


def classify_i4_i5(i4_result: Optional[Dict[str, Any]], i5_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Classify one repair round given its raw i4_result (RAGRepairAgent)
    and i5_result (FixApplicator, or None if FixApplicator never ran - i4
    abstained/failed, or an excluded-record stub). Pure function, no I/O.

    Returns {"category": one of ALL_CATEGORIES, "detail": short string}.
    """
    if i4_result is None:
        return {"category": UNKNOWN, "detail": "no i4_result available"}

    i4_status = i4_result.get("status")
    eligibility_decision = (i4_result.get("eligibility") or {}).get("decision")

    if eligibility_decision is not None and eligibility_decision != "usable":
        return {"category": EXCLUDED, "detail": f"not repair-eligible: {eligibility_decision}"}

    if i4_status == "failed":
        # rag_repair_agent.run_repair_agent() only ever sets status="failed"
        # when the final validation-error category is timeout/
        # model_unavailable/runtime_error (scripts/rag_repair_agent.py,
        # run_repair_agent()) - by construction this is always an
        # infrastructure fault, never a persistent schema/grounding defect
        # (those map to "abstained" instead, handled below).
        return {"category": INFRASTRUCTURE_FAILURE, "detail": "i4 status=failed (LLM/runtime fault)"}

    if i4_status == "abstained":
        retrieval_status = (i4_result.get("retrieval_result") or {}).get("status")
        if retrieval_status in INFRA_RETRIEVAL_STATUSES:
            return {
                "category": INFRASTRUCTURE_FAILURE,
                "detail": f"i4 abstained due to PyPI retrieval fault: {retrieval_status}",
            }
        return {"category": ABSTAINED, "detail": "i4 abstained (no grounded repair proposed)"}

    if i4_status != "success":
        return {"category": UNKNOWN, "detail": f"unrecognized i4 status: {i4_status!r}"}

    # i4 status == "success": a grounded repair was proposed and i5 always
    # attempts it (fix_applicator.resolve_attempt() only skips for
    # status != "success" or action == "none", neither of which applies here).
    if i5_result is None:
        return {"category": UNKNOWN, "detail": "i4 succeeded but no i5_result was recorded"}

    i5_status = i5_result.get("status")
    if i5_status == "skipped":
        return {"category": UNKNOWN, "detail": f"unexpected i5 skip after i4 success: {i5_result.get('skip_reason')}"}

    outcome = i5_result.get("outcome")
    if outcome == "fixed":
        return {"category": FIXED, "detail": "notebook re-executed with no error output"}
    if outcome == "still_failing":
        return {"category": STILL_FAILING, "detail": "notebook re-executed with an error output remaining"}

    if outcome == "apply_error":
        failure_stage = i5_result.get("failure_stage")
        execution_status = i5_result.get("execution_status")
        if failure_stage in INFRA_APPLY_ERROR_STAGES:
            return {
                "category": INFRASTRUCTURE_FAILURE,
                "detail": f"apply_error at infrastructure stage: {failure_stage}",
            }
        if execution_status in METHOD_EXECUTION_STATUSES:
            return {
                "category": METHOD_FAILURE,
                "detail": f"apply_error, execution_status={execution_status} (conservative: method, not infra)",
            }
        return {
            "category": METHOD_FAILURE,
            "detail": (
                f"apply_error with unrecognized failure_stage={failure_stage!r}/"
                f"execution_status={execution_status!r} (conservative default: method)"
            ),
        }

    return {"category": UNKNOWN, "detail": f"unrecognized i5 outcome: {outcome!r}"}


def classify_round_entry(round_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Classify one entry of scripts/run_pipeline.py's own per-record trace
    "rounds" list (see process_record()'s docstring for its shape:
    {"round", "status", "i4_result"?, "i5_result"?, "error"?})."""
    status = round_entry.get("status")

    if status == "component_error":
        return {
            "category": INFRASTRUCTURE_FAILURE,
            "detail": f"component_error: {round_entry.get('error')}",
        }
    if status == "orchestrator_error":
        return {
            "category": INFRASTRUCTURE_FAILURE,
            "detail": f"orchestrator_error: {round_entry.get('error')}",
        }
    if status == "excluded":
        return classify_i4_i5(round_entry.get("i4_result"), None)
    if status == "skipped_already_logged":
        return {"category": UNKNOWN, "detail": "round already logged in a prior invocation; not re-classified"}
    if status == "completed":
        return classify_i4_i5(round_entry.get("i4_result"), round_entry.get("i5_result"))

    return {"category": UNKNOWN, "detail": f"unrecognized round status: {status!r}"}
