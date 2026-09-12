import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import kg_competency_checks as kg


def kg_row(id_, notebook_execution_id=8, notebook_id=27, action="install", outcome="fixed", round_=1, run_id="run-1"):
    return {
        "id": id_,
        "notebook_execution_id": notebook_execution_id,
        "notebook_id": notebook_id,
        "action": action,
        "outcome": outcome,
        "round": round_,
        "run_id": run_id,
    }


def test_every_repair_attempt_links_to_a_notebook_passes():
    rows = [kg_row(1, notebook_id=27)]
    result = kg.check_every_repair_attempt_links_to_a_notebook(rows)
    assert result.passed is True


def test_every_repair_attempt_links_to_a_notebook_fails_for_null_notebook_id():
    rows = [kg_row(1, notebook_id=None)]
    result = kg.check_every_repair_attempt_links_to_a_notebook(rows)
    assert result.passed is False
    assert "1" in result.detail


def test_fixed_rows_have_valid_fix_outcome_passes_for_normal_rows():
    rows = [kg_row(1, action="install", outcome="fixed"), kg_row(2, action="none", outcome=None)]
    result = kg.check_fixed_rows_have_fix_outcome_fixed(rows)
    assert result.passed is True


def test_fixed_rows_have_valid_fix_outcome_fails_when_attempted_row_has_no_outcome():
    rows = [kg_row(1, action="install", outcome=None)]
    result = kg.check_fixed_rows_have_fix_outcome_fixed(rows)
    assert result.passed is False


def test_fixed_rows_have_valid_fix_outcome_fails_when_none_action_has_an_outcome():
    rows = [kg_row(1, action="none", outcome="fixed")]
    result = kg.check_fixed_rows_have_fix_outcome_fixed(rows)
    assert result.passed is False


def test_round2_rows_have_round_value_two_passes_for_normal_sequence():
    rows = [kg_row(1, round_=1, notebook_execution_id=174, run_id="run-1"), kg_row(2, round_=2, notebook_execution_id=174, run_id="run-1")]
    result = kg.check_round2_rows_have_round_value_two(rows)
    assert result.passed is True


def test_round2_rows_have_round_value_two_fails_for_round_three():
    rows = [kg_row(1, round_=3)]
    result = kg.check_round2_rows_have_round_value_two(rows)
    assert result.passed is False


def test_no_orphan_repair_attempts_passes_when_id_known():
    rows = [kg_row(1, notebook_execution_id=8)]
    result = kg.check_no_orphan_repair_attempts(rows, i2_ids={8, 174})
    assert result.passed is True


def test_no_orphan_repair_attempts_fails_when_id_unknown():
    rows = [kg_row(1, notebook_execution_id=999)]
    result = kg.check_no_orphan_repair_attempts(rows, i2_ids={8, 174})
    assert result.passed is False
    assert "1" in result.detail


def test_run_all_competency_checks_returns_four_checks():
    rows = [kg_row(1, notebook_execution_id=8)]
    results = kg.run_all_competency_checks(rows, i2_ids={8})
    assert len(results) == 4
    assert all(r.passed for r in results)
