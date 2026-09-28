#!/usr/bin/env python3

"""SelectHumanEvaluationPool: the exact, reproducible procedure used to
build the frozen 12-example pool for the human explanation-quality study
(docs/human-explanation-evaluation-questionnaire.md).

This is a VERIFICATION tool, not a re-selection tool: running it never
overwrites data/human-evaluation/human_evaluation_examples.csv or
human_evaluation_variants.csv. It recomputes the same deterministic
selection from the frozen final-evaluation trace and reports whether the
result still matches those two frozen files - the pool must never be
silently redrawn once participants may have started responding against
it. It does not call an LLM, does not regenerate any explanation, and
does not touch any I1-I8 pipeline output; it only reads the existing,
already-produced explanation trace.

Selection procedure ("diversity-constrained stratified sampling"):

1. Load every record from the final evaluation run's own trace
   (data/evaluation/i8-eval-final-rerun-20260913T113423Z/raw/pipeline-runs/
   i8-eval-final-rerun-20260913T113423Z.jsonl - the 187-row evaluation
   split; the 13-row development split lives in a separate run directory
   and is therefore structurally absent from this file).
2. Keep only records with a schema-valid explanation (explanation_result.
   status == "success", all six explanation fields non-empty), and drop
   notebook_execution_ids 21, 24, 25, 26, 29 (already used in earlier
   explanation-only development activity, per the study's design report).
3. Group the remaining eligible records by subtype. For missing_package,
   group further by failing_module. For wrong_version, group by the pair
   (failing_module, error_message) - its true distinct error signature,
   since two records with the same message produce near-identical
   explanations regardless of notebook_execution_id.
4. wrong_version has only 3 distinct signatures in the eligible
   population (verified, not assumed - see this module's
   `distinct_wrong_version_signatures()`), so all 3 are included, one
   representative record each. The remaining 9 pool slots come from
   missing_package, which has 41 distinct failing modules and therefore
   supports full diversity: 9 distinct modules are drawn, one
   representative record per module.
5. All sampling uses random.Random(seed=42) over alphabetically-sorted
   candidate lists, so the result is independent of dict/OS ordering and
   reproducible by anyone re-running this script.

This yields 9 missing_package + 3 wrong_version = 12 examples - not a 6/6
split, and the reason is recorded here and in the questionnaire document,
not just asserted.
"""

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple

SEED = 42
EXCLUDED_IDS = {21, 24, 25, 26, 29}
REQUIRED_EXPLANATION_FIELDS = [
    "summary", "root_cause", "evidence", "failing_module",
    "explanation_confidence", "limitations",
]

ROOT = Path(__file__).resolve().parent.parent
TRACE_PATH = ROOT / "data/evaluation/i8-eval-final-rerun-20260913T113423Z/raw/pipeline-runs/i8-eval-final-rerun-20260913T113423Z.jsonl"
FROZEN_EXAMPLES_CSV = ROOT / "data/human-evaluation/human_evaluation_examples.csv"
FROZEN_VARIANTS_CSV = ROOT / "data/human-evaluation/human_evaluation_variants.csv"


def load_eligible_records(trace_path: Path) -> List[Dict[str, Any]]:
    """Every record from the final evaluation trace with a schema-valid
    explanation, excluding the five already-seen development-activity IDs.
    Never reads or infers anything from repair outcome / Round-2 status."""
    eligible = []
    with trace_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            notebook_execution_id = record.get("notebook_execution_id")
            if notebook_execution_id in EXCLUDED_IDS:
                continue

            explanation = record.get("explanation") or {}
            input_block = explanation.get("input") or {}
            result = explanation.get("explanation_result") or {}
            explanation_json = result.get("explanation_json")

            if result.get("status") != "success" or not explanation_json:
                continue
            if any(not explanation_json.get(field) for field in REQUIRED_EXPLANATION_FIELDS):
                continue

            eligible.append({
                "notebook_execution_id": notebook_execution_id,
                "subtype": input_block.get("refined_subtype"),
                "error_type": input_block.get("error_type"),
                "error_message": input_block.get("error_message"),
                "failing_module": input_block.get("failing_module"),
                "explanation_json": explanation_json,
            })
    return eligible


def distinct_wrong_version_signatures(eligible: List[Dict[str, Any]]) -> Dict[Tuple[str, str], List[int]]:
    """{(failing_module, error_message): [candidate notebook_execution_ids]}
    over the eligible wrong_version population - the true ceiling on how
    many non-duplicate wrong_version examples the pool can contain."""
    signatures: Dict[Tuple[str, str], List[int]] = {}
    for r in eligible:
        if r["subtype"] != "wrong_version":
            continue
        key = (r["failing_module"], r["error_message"])
        signatures.setdefault(key, []).append(r["notebook_execution_id"])
    return signatures


def select_pool(eligible: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The frozen selection: 9 missing_package (one per distinct module) +
    3 wrong_version (one per distinct signature), seed=42. Deterministic
    given the same eligible population - never redraws."""
    rng = random.Random(SEED)
    by_id = {r["notebook_execution_id"]: r for r in eligible}

    missing_package = [r for r in eligible if r["subtype"] == "missing_package"]
    by_module: Dict[str, List[int]] = {}
    for r in missing_package:
        by_module.setdefault(r["failing_module"], []).append(r["notebook_execution_id"])

    modules_sorted = sorted(by_module.keys())
    chosen_modules = rng.sample(modules_sorted, 9)
    missing_package_ids = [rng.choice(sorted(by_module[m])) for m in chosen_modules]

    signatures = distinct_wrong_version_signatures(eligible)
    if len(signatures) != 3:
        raise AssertionError(
            f"expected exactly 3 distinct wrong_version signatures in the eligible "
            f"population, found {len(signatures)} - the frozen 9/3 split assumes this; "
            f"re-derive the pool composition by hand if this population has changed."
        )
    wrong_version_ids = [rng.choice(sorted(ids)) for _, ids in sorted(signatures.items())]

    return [by_id[i] for i in sorted(missing_package_ids + wrong_version_ids)]


def load_frozen_ids(examples_csv: Path) -> List[int]:
    with examples_csv.open("r", encoding="utf-8", newline="") as f:
        return sorted(int(row["notebook_execution_id"]) for row in csv.DictReader(f))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recompute the human-evaluation example pool and verify it against the frozen CSVs (never overwrites them)."
    )
    parser.add_argument("--trace", default=str(TRACE_PATH))
    args = parser.parse_args()

    eligible = load_eligible_records(Path(args.trace))
    recomputed = select_pool(eligible)
    recomputed_ids = sorted(r["notebook_execution_id"] for r in recomputed)

    print(f"Recomputed pool (seed={SEED}): {recomputed_ids}")

    if not FROZEN_EXAMPLES_CSV.is_file():
        print(f"No frozen pool file found at {FROZEN_EXAMPLES_CSV} - nothing to verify against.")
        return

    frozen_ids = load_frozen_ids(FROZEN_EXAMPLES_CSV)
    if recomputed_ids == frozen_ids:
        print(f"MATCH: recomputed pool is identical to the frozen pool in {FROZEN_EXAMPLES_CSV}.")
    else:
        print(f"MISMATCH against {FROZEN_EXAMPLES_CSV}:")
        print(f"  frozen:     {frozen_ids}")
        print(f"  recomputed: {recomputed_ids}")
        print("This does not overwrite the frozen files. Investigate before changing anything.")


if __name__ == "__main__":
    main()
