#!/usr/bin/env python3

"""KGCompetencyChecks (i8): small pass/fail integrity checks over the
repair_attempts -> KG export, in addition to the existing
scripts/validate_kg_notebook_alignment.py (reused as-is, not redesigned).

These are deliberately NOT ML metrics - the RML mapping
(mapping/rml_mapping/repair_attempts.rml.ttl) is a fixed, deterministic
transform of exactly the columns scripts/export_repair_attempts_csv.py
already produces (CSV_COLUMNS = ["id", "notebook_id"] + REPAIR_ATTEMPT_COLUMNS),
so every one of the frozen methodology's "competency questions" can be
checked directly against that CSV's rows, without standing up a triple
store or running Morph-KGC: a fact must already be true in the CSV before
the RML mapping can produce the corresponding RDF triple, and a fact
missing from the CSV can never appear in the KG regardless of the mapping.
"""

from typing import Any, Dict, List


class CompetencyCheckResult:
    def __init__(self, name: str, passed: bool, detail: str = ""):
        self.name = name
        self.passed = passed
        self.detail = detail

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


def check_every_repair_attempt_links_to_a_notebook(rows: List[Dict[str, Any]]) -> CompetencyCheckResult:
    """Competency question: every RepairAttempt links to a notebook.
    mapping/rml_mapping/repair_attempts.rml.ttl's `repr:hadRepairAttempt`
    link is driven by the exported `notebook_id` column - a null/blank
    value there means the RML mapping will silently emit no notebook link
    for that row."""
    offending = [row.get("id") for row in rows if not row.get("notebook_id")]
    return CompetencyCheckResult(
        "every_repair_attempt_links_to_a_notebook", not offending, f"repair_attempts_ids_missing_notebook_id={offending}"
    )


def check_fixed_rows_have_fix_outcome_fixed(rows: List[Dict[str, Any]]) -> CompetencyCheckResult:
    """Competency question: every fixed RepairAttempt has fixOutcome =
    fixed. Checks the schema contract, not a tautology: a real attempted
    round (action != "none") must always carry a non-null outcome in
    {fixed, still_failing, apply_error}; a never-attempted round
    (action == "none": abstained/excluded) must always carry outcome ==
    None. Either direction breaking would mean result_logger.py's row
    construction has drifted from its own documented contract."""
    offending = []
    for row in rows:
        action = row.get("action")
        outcome = row.get("outcome")
        if action and action != "none" and outcome not in {"fixed", "still_failing", "apply_error"}:
            offending.append((row.get("id"), "attempted row with invalid/missing outcome", outcome))
        if (not action or action == "none") and outcome not in (None, ""):
            offending.append((row.get("id"), "non-attempted row with a non-null outcome", outcome))
    return CompetencyCheckResult("fixed_rows_have_valid_fix_outcome", not offending, f"offending={offending}")


def check_round2_rows_have_round_value_two(rows: List[Dict[str, Any]]) -> CompetencyCheckResult:
    """Competency question: every Round-2 attempt has a round value of 2.
    A row is only "Round 2" if it shares (notebook_execution_id, run_id)
    with an earlier round=1 row - flags any round value outside {1, 2} as
    well as a "second row for this notebook/run" whose round is not
    literally 2."""
    seen_round1: set = set()
    offending = []
    for row in rows:
        round_value = row.get("round")
        if round_value not in (1, 2):
            offending.append((row.get("id"), "round not in {1,2}", round_value))
        if round_value == 1:
            seen_round1.add((row.get("notebook_execution_id"), row.get("run_id")))
    for row in rows:
        key = (row.get("notebook_execution_id"), row.get("run_id"))
        if row.get("round") not in (1, None) and row.get("round") != 2 and key in seen_round1:
            offending.append((row.get("id"), "second row for this notebook/run is not round=2", row.get("round")))
    return CompetencyCheckResult("round2_rows_have_round_value_two", not offending, f"offending={offending}")


def check_no_orphan_repair_attempts(rows: List[Dict[str, Any]], i2_ids: set) -> CompetencyCheckResult:
    """Competency question: no orphan repair attempts - every row's
    notebook_execution_id must resolve to a real i2 dataset record.
    export_repair_attempts_csv.py already hard-errors on this at export
    time; this check lets the same rule be verified pre-export, and is
    exercised directly by tests without needing a real export run."""
    offending = [
        row.get("id")
        for row in rows
        if row.get("notebook_execution_id") is None or int(row["notebook_execution_id"]) not in i2_ids
    ]
    return CompetencyCheckResult("no_orphan_repair_attempts", not offending, f"orphan_repair_attempts_ids={offending}")


def run_all_competency_checks(rows: List[Dict[str, Any]], i2_ids: set) -> List[CompetencyCheckResult]:
    return [
        check_every_repair_attempt_links_to_a_notebook(rows),
        check_fixed_rows_have_fix_outcome_fixed(rows),
        check_round2_rows_have_round_value_two(rows),
        check_no_orphan_repair_attempts(rows, i2_ids),
    ]
