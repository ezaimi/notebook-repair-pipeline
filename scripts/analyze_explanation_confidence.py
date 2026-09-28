#!/usr/bin/env python3
"""Describe LLM self-reported confidence against human-study Q6 ratings.

This script joins the frozen explanation records used to create the 12
human-study examples with the already reshaped survey responses.  Q6 is
perceived correctness, not an independently verified technical-correctness
measure.  The output is therefore descriptive and deliberately does not
claim to calibrate the model's confidence.
"""

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List


VALID_CONFIDENCE = {"high", "medium", "low"}


def median(values: List[int]) -> float:
    if not values:
        raise ValueError("cannot calculate a median for no ratings")
    return float(statistics.median(values))


def agreement_percentage(values: Iterable[int]) -> float:
    values = list(values)
    if not values:
        return 0.0
    return 100.0 * sum(value >= 4 for value in values) / len(values)


def load_examples(path: Path) -> Dict[str, Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = {
            row["notebook_execution_id"].strip(): row
            for row in csv.DictReader(handle)
        }
    if not rows:
        raise ValueError(f"no examples found in {path}")
    return rows


def load_confidence(trace_path: Path, expected_ids: Iterable[str]) -> Dict[str, str]:
    expected = set(expected_ids)
    confidence: Dict[str, str] = {}
    with trace_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            record = json.loads(line)
            notebook_id = str(record.get("notebook_execution_id", ""))
            if notebook_id not in expected:
                continue
            explanation = record.get("explanation") or {}
            result = explanation.get("explanation_result") or {}
            generated = result.get("explanation_json") or {}
            value = generated.get("explanation_confidence")
            if value not in VALID_CONFIDENCE:
                raise ValueError(
                    f"record {notebook_id} on trace line {line_number} has "
                    f"invalid explanation_confidence {value!r}"
                )
            confidence[notebook_id] = value
    missing = sorted(expected - set(confidence), key=int)
    if missing:
        raise ValueError(f"missing explanation confidence for notebook IDs: {missing}")
    return confidence


def load_q6_ratings(path: Path, expected_ids: Iterable[str]) -> Dict[str, List[int]]:
    expected = set(expected_ids)
    ratings: Dict[str, List[int]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            notebook_id = row["notebook_execution_id"].strip()
            if notebook_id not in expected:
                continue
            try:
                rating = int(row["q6_perceived_correctness"])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid Q6 rating on line {line_number}: "
                    f"{row['q6_perceived_correctness']!r}"
                ) from exc
            if rating < 1 or rating > 5:
                raise ValueError(f"Q6 rating out of range on line {line_number}: {rating}")
            ratings[notebook_id].append(rating)
    missing = sorted(expected - set(ratings), key=int)
    if missing:
        raise ValueError(f"missing Q6 ratings for notebook IDs: {missing}")
    return ratings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Describe LLM self-reported confidence versus human-study Q6 ratings."
    )
    parser.add_argument(
        "--examples",
        default="data/human-evaluation/human_evaluation_examples.csv",
    )
    parser.add_argument(
        "--responses",
        default="data/human-evaluation/human_evaluation_responses.csv",
    )
    parser.add_argument(
        "--trace",
        default=(
            "data/evaluation/i8-eval-final-rerun-20260913T113423Z/raw/"
            "pipeline-runs/i8-eval-final-rerun-20260913T113423Z.jsonl"
        ),
        help="Frozen Gemma explanation trace from which the study examples were drawn.",
    )
    parser.add_argument(
        "--out-dir",
        default="data/human-evaluation/analysis",
    )
    args = parser.parse_args()

    examples = load_examples(Path(args.examples))
    confidence = load_confidence(Path(args.trace), examples)
    ratings = load_q6_ratings(Path(args.responses), examples)

    per_example = []
    grouped_ratings: Dict[str, List[int]] = defaultdict(list)
    grouped_ids: Dict[str, List[str]] = defaultdict(list)
    grouped_subtypes: Dict[str, set] = defaultdict(set)
    for notebook_id in sorted(examples, key=int):
        values = ratings[notebook_id]
        level = confidence[notebook_id]
        subtype = examples[notebook_id]["subtype"]
        grouped_ratings[level].extend(values)
        grouped_ids[level].append(notebook_id)
        grouped_subtypes[level].add(subtype)
        per_example.append({
            "notebook_execution_id": notebook_id,
            "subtype": subtype,
            "llm_self_reported_confidence": level,
            "q6_ratings": len(values),
            "q6_median": median(values),
            "q6_pct_agree_or_strongly_agree": agreement_percentage(values),
        })

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    per_example_path = out_dir / "confidence_vs_perceived_correctness_per_example.csv"
    with per_example_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(per_example[0]))
        writer.writeheader()
        writer.writerows(per_example)

    summary = []
    for level in ("high", "medium", "low"):
        values = grouped_ratings[level]
        summary.append({
            "llm_self_reported_confidence": level,
            "subtypes_in_pool": "; ".join(sorted(grouped_subtypes[level])) or "none",
            "unique_explanations": len(grouped_ids[level]),
            "q6_ratings": len(values),
            "q6_median": median(values) if values else "",
            "q6_pct_agree_or_strongly_agree": agreement_percentage(values) if values else "",
        })
    summary_path = out_dir / "confidence_vs_perceived_correctness_summary.csv"
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)

    populated_levels = {level for level, ids in grouped_ids.items() if ids}
    subtype_to_levels: Dict[str, set] = defaultdict(set)
    for level in populated_levels:
        for subtype in grouped_subtypes[level]:
            subtype_to_levels[subtype].add(level)
    confidence_is_confounded = (
        all(len(grouped_subtypes[level]) == 1 for level in populated_levels)
        and all(len(levels) == 1 for levels in subtype_to_levels.values())
    )
    if populated_levels != VALID_CONFIDENCE or confidence_is_confounded:
        conclusion = (
            "The sample cannot establish confidence calibration: not all three "
            "confidence levels are represented and confidence is confounded with subtype."
        )
    else:
        conclusion = (
            "The descriptive comparison is not a calibration test and must not be "
            "interpreted as objective explanation correctness."
        )

    print("=== LLM self-reported confidence versus Q6 perceived correctness ===")
    for row in summary:
        print(
            f"  {row['llm_self_reported_confidence']}: "
            f"examples={row['unique_explanations']} Q6 ratings={row['q6_ratings']} "
            f"median={row['q6_median']} %4-5={row['q6_pct_agree_or_strongly_agree']} "
            f"subtypes={row['subtypes_in_pool']}"
        )
    print(conclusion)
    print(f"Wrote {per_example_path} and {summary_path}")


if __name__ == "__main__":
    main()
