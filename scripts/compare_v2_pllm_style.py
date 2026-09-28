#!/usr/bin/env python3
"""Create a reproducible matched comparison of V2 and PLLM-style traces.

The two inputs must contain one JSON record for each notebook in the same
evaluation split.  The script deliberately reads only recorded outcomes: it
does not rerun a notebook or make a new package decision.
"""

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def completed_attempt(entry: Dict[str, Any], key: str) -> Dict[str, Any] | None:
    attempt = entry.get(key)
    return attempt if isinstance(attempt, dict) and attempt.get("status") == "completed" else None


def targeted_resolved(attempt: Dict[str, Any]) -> bool:
    return attempt.get("outcome") == "fixed" or (
        attempt.get("outcome") == "still_failing" and attempt.get("same_as_original_error") is False
    )


def normalise_trace(records: Iterable[Dict[str, Any]], attempt_key: str) -> Dict[int, Dict[str, Any]]:
    normalised: Dict[int, Dict[str, Any]] = {}
    for record in records:
        notebook_id = record.get("notebook_execution_id")
        if not isinstance(notebook_id, int) or notebook_id in normalised:
            raise ValueError("Each trace must contain one unique integer notebook_execution_id")

        rounds = record.get("rounds") or []
        attempts = [completed_attempt(round_entry, attempt_key) for round_entry in rounds]
        attempts = [attempt for attempt in attempts if attempt is not None]
        # The final category belongs to the terminal round.  A Round-2
        # abstention remains an abstention even when Round 1 reached Docker
        # and exposed a different dependency error.
        terminal_attempt = completed_attempt(rounds[-1], attempt_key) if rounds else None
        final_outcome = terminal_attempt.get("outcome") if terminal_attempt else "abstained"
        normalised[notebook_id] = {
            "notebook_execution_id": notebook_id,
            "docker_attempts": len(attempts),
            "targeted_error_resolved_attempts": sum(targeted_resolved(attempt) for attempt in attempts),
            "final_outcome": final_outcome,
            "fully_fixed": final_outcome == "fixed",
        }
    return normalised


def summarise(records: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    values = list(records.values())
    attempts = sum(item["docker_attempts"] for item in values)
    targeted = sum(item["targeted_error_resolved_attempts"] for item in values)
    fixed_ids = sorted(item["notebook_execution_id"] for item in values if item["fully_fixed"])
    return {
        "notebooks_processed": len(values),
        "docker_repair_attempts": attempts,
        "targeted_errors_resolved": targeted,
        "targeted_error_resolution_rate": targeted / attempts if attempts else None,
        "full_notebook_recoveries": len(fixed_ids),
        "full_notebook_recovery_rate": len(fixed_ids) / len(values) if values else None,
        "final_outcomes": dict(sorted(Counter(item["final_outcome"] for item in values).items())),
        "fully_recovered_notebook_execution_ids": fixed_ids,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v2-trace", type=Path, required=True)
    parser.add_argument("--pllm-trace", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    args = parser.parse_args()

    v2 = normalise_trace(load_jsonl(args.v2_trace), "i5_result")
    pllm = normalise_trace(load_jsonl(args.pllm_trace), "attempt")
    if set(v2) != set(pllm):
        raise ValueError("The traces do not cover the same notebook_execution_id set")

    paired_rows: List[Dict[str, Any]] = []
    for notebook_id in sorted(v2):
        paired_rows.append({
            "notebook_execution_id": notebook_id,
            "v2_final_outcome": v2[notebook_id]["final_outcome"],
            "v2_docker_attempts": v2[notebook_id]["docker_attempts"],
            "v2_targeted_error_resolved_attempts": v2[notebook_id]["targeted_error_resolved_attempts"],
            "pllm_style_final_outcome": pllm[notebook_id]["final_outcome"],
            "pllm_style_docker_attempts": pllm[notebook_id]["docker_attempts"],
            "pllm_style_targeted_error_resolved_attempts": pllm[notebook_id]["targeted_error_resolved_attempts"],
        })

    v2_summary = summarise(v2)
    pllm_summary = summarise(pllm)
    v2_fixed = set(v2_summary["fully_recovered_notebook_execution_ids"])
    pllm_fixed = set(pllm_summary["fully_recovered_notebook_execution_ids"])
    report = {
        "method": "matched descriptive comparison",
        "trace_integrity": {
            "v2_trace": str(args.v2_trace),
            "v2_trace_sha256": sha256(args.v2_trace),
            "pllm_style_trace": str(args.pllm_trace),
            "pllm_style_trace_sha256": sha256(args.pllm_trace),
            "shared_notebook_execution_ids": len(v2),
        },
        "v2_thesis_pipeline": v2_summary,
        "pllm_style_baseline": pllm_summary,
        "paired_full_recovery": {
            "both_methods": sorted(v2_fixed & pllm_fixed),
            "v2_only": sorted(v2_fixed - pllm_fixed),
            "pllm_style_only": sorted(pllm_fixed - v2_fixed),
        },
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with args.output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(paired_rows[0]))
        writer.writeheader()
        writer.writerows(paired_rows)


if __name__ == "__main__":
    main()
