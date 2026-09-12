#!/usr/bin/env python3

"""FreezeManualSamples (i8): select and persist the manual ground-truth
sample IDs/import-names BEFORE the reserved 187-record evaluation split is
ever run, per the frozen I8 methodology.

Selection is entirely deterministic (a stable hash of each record's own
identity, never Python's seeded `random` module, which is not guaranteed
stable across interpreter/version changes) - re-running this script
against the same dataset always reproduces the exact same sample. It never
looks at final evaluation outcomes and never writes a "correct" label
itself: every output file's manual_* / correct_distribution columns are
left blank for a human to fill in later, and `predicted_*` /
`pipeline_resolved_distribution` columns are shown only as reference
context, never copied into the manual column.

Two samples are produced:

1. ErrorClassifier ground-truth sample (data/manual-ground-truth/
   classifier_ground_truth_sample.csv): exhaustive for the rare excluded
   subtypes (system_library, mapping_unknown), stratified for the two
   repair-eligible subtypes (missing_package, wrong_version), drawn
   primarily from the evaluation split with a small dev-split slice kept
   for calibration.
2. PyPI distribution-resolution sample (data/manual-ground-truth/
   pypi_resolution_sample.csv): every import name already in
   config/package_mapping.yaml that is actually exercised by the dataset,
   plus the most frequently exercised import names that are NOT in that
   mapping (surfacing static-mapping-table coverage gaps honestly).
"""

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pypi_retriever import resolve_distribution_name  # noqa: E402


DEFAULT_I2_PATH = ROOT / "data" / "context-classification" / "dependency_error_contexts.jsonl"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "manual-ground-truth"

REPAIR_ELIGIBLE_SUBTYPES = {"missing_package", "wrong_version"}
EXCLUDED_SUBTYPES = {"system_library", "mapping_unknown"}

# Target sample sizes. Fixed here, once, before any evaluation-set outcome
# is observed - see docs/i8-evaluation-methodology.md §D.
SAMPLE_PLAN = {
    "system_library": {"n": None},  # None => take every record (exhaustive)
    "mapping_unknown": {"n": None},  # None => take every record (exhaustive)
    "wrong_version": {"n": 15, "n_from_dev": 3},
    "missing_package": {"n": 20, "n_from_dev": 3},
}


def _stable_key(*parts: Any) -> str:
    """A deterministic, dataset-content-derived ordering key - NOT
    Python's seeded random module (whose output is not guaranteed stable
    across interpreter/version changes), so re-running this script always
    reproduces the same sample from the same dataset."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8"))
    return digest.hexdigest()


def load_i2_records(i2_path: Path) -> List[Dict[str, Any]]:
    records = []
    with i2_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# --- classifier ground-truth sample -----------------------------------------

def _select_stratum(records: List[Dict[str, Any]], n: Optional[int], n_from_dev: int = 0) -> List[Dict[str, Any]]:
    """Deterministically select up to `n` records from `records` (already
    filtered to one subtype). None => take all. When `n_from_dev` > 0,
    reserve up to that many slots for dev-split records (for calibration
    comparison against the same subtype's evaluation-split behavior), the
    rest from the evaluation split, each ordered by _stable_key()."""
    if n is None:
        return sorted(records, key=lambda r: _stable_key(r.get("notebook_execution_id")))

    dev_pool = sorted(
        (r for r in records if r.get("split") == "dev"),
        key=lambda r: _stable_key(r.get("notebook_execution_id")),
    )
    eval_pool = sorted(
        (r for r in records if r.get("split") == "evaluation"),
        key=lambda r: _stable_key(r.get("notebook_execution_id")),
    )

    dev_take = dev_pool[:n_from_dev]
    remaining = max(n - len(dev_take), 0)
    eval_take = eval_pool[:remaining]
    return dev_take + eval_take


def build_classifier_sample(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sample: List[Dict[str, Any]] = []
    for subtype, plan in SAMPLE_PLAN.items():
        subtype_records = [r for r in records if r.get("original_subtype") == subtype]
        selected = _select_stratum(subtype_records, plan["n"], plan.get("n_from_dev", 0))
        for record in selected:
            sample.append(
                {
                    "notebook_execution_id": record.get("notebook_execution_id"),
                    "split": record.get("split"),
                    "error_type": record.get("error_type"),
                    "error_message": record.get("error_message"),
                    "predicted_failing_module": record.get("failing_module"),
                    "predicted_scope_status": record.get("scope_status"),
                    "predicted_original_subtype": record.get("original_subtype"),
                    "predicted_subtype": record.get("refined_subtype"),
                    "predicted_confidence": record.get("confidence"),
                    "manual_scope_status": "",
                    "manual_subtype": "",
                    "manual_failing_module": "",
                    "notes": "",
                }
            )
    sample.sort(key=lambda r: r["notebook_execution_id"])
    return sample


CLASSIFIER_FIELDS = [
    "notebook_execution_id",
    "split",
    "error_type",
    "error_message",
    "predicted_failing_module",
    "predicted_scope_status",
    "predicted_original_subtype",
    "predicted_subtype",
    "predicted_confidence",
    "manual_scope_status",
    "manual_subtype",
    "manual_failing_module",
    "notes",
]


# --- PyPI distribution-resolution sample ------------------------------------

def build_pypi_resolution_sample(records: List[Dict[str, Any]], max_unmapped: int = 12) -> List[Dict[str, Any]]:
    """Every distinct import name among repair-eligible records that
    already resolves via config/package_mapping.yaml, plus the most
    frequently exercised import names that do NOT resolve (mapping_unknown
    at retrieval time) - both directions matter: correctness of existing
    mappings, and coverage gaps in the static table."""
    eligible = [r for r in records if r.get("scope_status") == "usable"]

    frequency: Dict[str, int] = {}
    example_record: Dict[str, Dict[str, Any]] = {}
    subtype_for: Dict[str, str] = {}
    for record in eligible:
        import_name = record.get("failing_module")
        if not import_name:
            continue
        frequency[import_name] = frequency.get(import_name, 0) + 1
        example_record.setdefault(import_name, record)
        subtype_for.setdefault(import_name, record.get("refined_subtype"))

    mapped_names = sorted(
        (name for name in frequency if resolve_distribution_name(name) is not None),
        key=lambda name: _stable_key(name),
    )
    unmapped_names = sorted(
        (name for name in frequency if resolve_distribution_name(name) is None),
        key=lambda name: (-frequency[name], _stable_key(name)),
    )[:max_unmapped]

    sample = []
    for import_name in mapped_names + unmapped_names:
        record = example_record[import_name]
        sample.append(
            {
                "import_name": import_name,
                "subtype_context": subtype_for[import_name],
                "example_notebook_execution_id": record.get("notebook_execution_id"),
                "frequency_in_dataset": frequency[import_name],
                "pipeline_resolved_distribution": resolve_distribution_name(import_name),
                "manual_correct_distribution": "",
                "notes": "",
            }
        )
    return sample


PYPI_FIELDS = [
    "import_name",
    "subtype_context",
    "example_notebook_execution_id",
    "frequency_in_dataset",
    "pipeline_resolved_distribution",
    "manual_correct_distribution",
    "notes",
]


def write_csv(rows: List[Dict[str, Any]], fields: List[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze the I8 manual ground-truth sample selections before the final evaluation run."
    )
    parser.add_argument("--i2", default=str(DEFAULT_I2_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    records = load_i2_records(Path(args.i2))
    output_dir = Path(args.output_dir)

    classifier_sample = build_classifier_sample(records)
    pypi_sample = build_pypi_resolution_sample(records)

    write_csv(classifier_sample, CLASSIFIER_FIELDS, output_dir / "classifier_ground_truth_sample.csv")
    write_csv(pypi_sample, PYPI_FIELDS, output_dir / "pypi_resolution_sample.csv")

    print(f"classifier ground-truth sample: {len(classifier_sample)} records -> {output_dir / 'classifier_ground_truth_sample.csv'}")
    print(f"PyPI resolution sample: {len(pypi_sample)} import names -> {output_dir / 'pypi_resolution_sample.csv'}")


if __name__ == "__main__":
    main()
