import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import infra_classification as ic


def i4(status, eligibility_decision="usable", retrieval_status=None):
    return {
        "status": status,
        "eligibility": {"decision": eligibility_decision},
        "retrieval_result": {"status": retrieval_status} if retrieval_status else None,
    }


def i5(status, outcome=None, failure_stage=None, execution_status=None):
    return {"status": status, "outcome": outcome, "failure_stage": failure_stage, "execution_status": execution_status}


# --- fixed / still_failing ---------------------------------------------------

def test_classify_fixed():
    result = ic.classify_i4_i5(i4("success"), i5("completed", outcome="fixed"))
    assert result["category"] == ic.FIXED


def test_classify_still_failing():
    result = ic.classify_i4_i5(i4("success"), i5("completed", outcome="still_failing"))
    assert result["category"] == ic.STILL_FAILING


# --- excluded -----------------------------------------------------------------

def test_classify_excluded_record():
    result = ic.classify_i4_i5(i4("abstained", eligibility_decision="excluded"), None)
    assert result["category"] == ic.EXCLUDED


def test_classify_invalid_eligibility_treated_as_excluded():
    result = ic.classify_i4_i5(i4("abstained", eligibility_decision="invalid"), None)
    assert result["category"] == ic.EXCLUDED


# --- abstention (method, not infra) -------------------------------------------

def test_classify_abstained_mapping_unknown_is_method_not_infra():
    result = ic.classify_i4_i5(i4("abstained", retrieval_status="mapping_unknown"), None)
    assert result["category"] == ic.ABSTAINED


def test_classify_abstained_package_not_found_is_method():
    result = ic.classify_i4_i5(i4("abstained", retrieval_status="package_not_found"), None)
    assert result["category"] == ic.ABSTAINED


def test_classify_abstained_no_compatible_release_is_method():
    result = ic.classify_i4_i5(i4("abstained", retrieval_status="no_compatible_release"), None)
    assert result["category"] == ic.ABSTAINED


def test_classify_abstained_no_retrieval_result_is_method():
    """Covers abstention gates before any retrieval call (ineligible
    subtype, extraction failure, unsupported subtype) - no
    retrieval_result exists at all."""
    result = ic.classify_i4_i5({"status": "abstained", "eligibility": {"decision": "usable"}, "retrieval_result": None}, None)
    assert result["category"] == ic.ABSTAINED


# --- abstention (infra) ---------------------------------------------------------

def test_classify_abstained_network_error_is_infra():
    result = ic.classify_i4_i5(i4("abstained", retrieval_status="network_error"), None)
    assert result["category"] == ic.INFRASTRUCTURE_FAILURE


def test_classify_abstained_invalid_response_is_infra():
    result = ic.classify_i4_i5(i4("abstained", retrieval_status="invalid_response"), None)
    assert result["category"] == ic.INFRASTRUCTURE_FAILURE


def test_classify_abstained_configuration_error_is_infra():
    result = ic.classify_i4_i5(i4("abstained", retrieval_status="configuration_error"), None)
    assert result["category"] == ic.INFRASTRUCTURE_FAILURE


# --- i4 status == "failed" is always infra ------------------------------------

def test_classify_i4_failed_is_always_infra():
    result = ic.classify_i4_i5(i4("failed"), None)
    assert result["category"] == ic.INFRASTRUCTURE_FAILURE


# --- apply_error: infra stages vs method-attributed statuses -----------------

def test_classify_apply_error_clone_stage_is_infra():
    result = ic.classify_i4_i5(i4("success"), i5("completed", outcome="apply_error", failure_stage="clone"))
    assert result["category"] == ic.INFRASTRUCTURE_FAILURE


def test_classify_apply_error_checkout_stage_is_infra():
    result = ic.classify_i4_i5(i4("success"), i5("completed", outcome="apply_error", failure_stage="checkout"))
    assert result["category"] == ic.INFRASTRUCTURE_FAILURE


def test_classify_apply_error_build_stage_is_infra():
    result = ic.classify_i4_i5(i4("success"), i5("completed", outcome="apply_error", failure_stage="build"))
    assert result["category"] == ic.INFRASTRUCTURE_FAILURE


def test_classify_apply_error_timeout_stage_is_infra():
    result = ic.classify_i4_i5(i4("success"), i5("completed", outcome="apply_error", failure_stage="timeout"))
    assert result["category"] == ic.INFRASTRUCTURE_FAILURE


def test_classify_apply_error_join_stage_is_infra():
    result = ic.classify_i4_i5(i4("success"), i5("completed", outcome="apply_error", failure_stage="join"))
    assert result["category"] == ic.INFRASTRUCTURE_FAILURE


def test_classify_apply_error_validation_stage_is_infra():
    result = ic.classify_i4_i5(i4("success"), i5("completed", outcome="apply_error", failure_stage="validation"))
    assert result["category"] == ic.INFRASTRUCTURE_FAILURE


def test_classify_apply_error_fix_install_failed_is_method():
    result = ic.classify_i4_i5(
        i4("success"), i5("completed", outcome="apply_error", execution_status="fix_install_failed")
    )
    assert result["category"] == ic.METHOD_FAILURE


def test_classify_apply_error_notebook_not_found_is_method():
    result = ic.classify_i4_i5(
        i4("success"), i5("completed", outcome="apply_error", execution_status="notebook_not_found")
    )
    assert result["category"] == ic.METHOD_FAILURE


def test_classify_apply_error_docker_run_failed_is_method():
    result = ic.classify_i4_i5(
        i4("success"), i5("completed", outcome="apply_error", execution_status="docker_run_failed")
    )
    assert result["category"] == ic.METHOD_FAILURE


def test_classify_apply_error_output_notebook_missing_is_method():
    result = ic.classify_i4_i5(
        i4("success"), i5("completed", outcome="apply_error", execution_status="output_notebook_missing")
    )
    assert result["category"] == ic.METHOD_FAILURE


def test_classify_apply_error_unrecognized_defaults_to_method():
    """Governing principle: ambiguous cases default to method, never
    infrastructure, so infra-exclusion can never be used to inflate a
    reported success rate."""
    result = ic.classify_i4_i5(
        i4("success"), i5("completed", outcome="apply_error", failure_stage=None, execution_status="something_new")
    )
    assert result["category"] == ic.METHOD_FAILURE


# --- round-entry wrapper -------------------------------------------------------

def test_classify_round_entry_component_error_is_infra():
    result = ic.classify_round_entry({"status": "component_error", "error": "boom"})
    assert result["category"] == ic.INFRASTRUCTURE_FAILURE


def test_classify_round_entry_orchestrator_error_is_infra():
    result = ic.classify_round_entry({"status": "orchestrator_error", "error": "boom"})
    assert result["category"] == ic.INFRASTRUCTURE_FAILURE


def test_classify_round_entry_excluded():
    result = ic.classify_round_entry({"status": "excluded", "i4_result": i4("abstained", eligibility_decision="excluded")})
    assert result["category"] == ic.EXCLUDED


def test_classify_round_entry_completed_delegates_to_classify_i4_i5():
    result = ic.classify_round_entry(
        {"status": "completed", "i4_result": i4("success"), "i5_result": i5("completed", outcome="fixed")}
    )
    assert result["category"] == ic.FIXED


def test_classify_round_entry_skipped_already_logged_is_unknown():
    result = ic.classify_round_entry({"status": "skipped_already_logged"})
    assert result["category"] == ic.UNKNOWN
