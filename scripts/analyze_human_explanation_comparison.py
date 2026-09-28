"""Describe the blinded LLM-versus-resolver-template comparison.

The comparison is intentionally descriptive: four ratings are nested within
each participant and no inferential test is calculated. Empty rows created by
the Google Forms destination sheet are excluded only when they have no
participant code and no ratings.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


QUESTIONS = (
    "q1_understanding",
    "q2_satisfaction",
    "q3_detail",
    "q4_completeness",
    "q5_usefulness",
    "q6_perceived_correctness",
)
METHODS = ("llm", "resolver_template")


def median(values: list[float]) -> float:
    return float(statistics.median(values))


def iqr(values: list[float]) -> float:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        lower, upper = ordered[:midpoint], ordered[midpoint + 1 :]
    else:
        lower, upper = ordered[:midpoint], ordered[midpoint:]
    return median(upper) - median(lower)


def describe(values: list[int | float]) -> dict[str, float | int]:
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 2),
        "median": median(values),
        "iqr": iqr(values),
        "agree_4_5_percent": round(100 * sum(value >= 4 for value in values) / len(values), 1),
        **{f"rating_{rating}": values.count(rating) for rating in range(1, 6)},
    }


def describe_continuous(values: list[float]) -> dict[str, float | int]:
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 2),
        "median": median(values),
        "iqr": iqr(values),
    }


def main(path_argument: str) -> None:
    input_path = Path(path_argument)
    output_dir = input_path.parent / "analysis"
    output_dir.mkdir(exist_ok=True)
    with input_path.open(encoding="utf-8-sig", newline="") as handle:
        raw_rows = list(csv.DictReader(handle))

    valid_rows: list[dict[str, str]] = []
    excluded_empty_rows = 0
    for row in raw_rows:
        if not row.get("participant_id", "").strip():
            if any(row.get(question, "").strip() for question in QUESTIONS):
                raise ValueError("A row has ratings but no participant code.")
            excluded_empty_rows += 1
            continue
        if row.get("explanation_method") not in METHODS:
            raise ValueError(f"Unknown method in participant {row['participant_id']!r}.")
        for question in QUESTIONS:
            try:
                rating = int(row[question])
            except (TypeError, ValueError) as error:
                raise ValueError(f"Missing or non-numeric {question} for participant {row['participant_id']!r}.") from error
            if rating not in range(1, 6):
                raise ValueError(f"Invalid {question} rating {rating} for participant {row['participant_id']!r}.")
        valid_rows.append(row)

    by_participant: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in valid_rows:
        by_participant[row["participant_id"]].append(row)
    incomplete = {identifier: len(rows) for identifier, rows in by_participant.items() if len(rows) != 4}
    if incomplete:
        raise ValueError(f"Participants without exactly four ratings: {incomplete}")

    summary_rows: list[dict[str, str | float | int]] = []
    for method in METHODS:
        method_rows = [row for row in valid_rows if row["explanation_method"] == method]
        for question in QUESTIONS:
            values = [int(row[question]) for row in method_rows]
            summary_rows.append({"scope": "all_examples", "method": method, "question": question, **describe(values)})
        all_values = [int(row[question]) for row in method_rows for question in QUESTIONS]
        summary_rows.append({"scope": "all_items", "method": method, "question": "all_items", **describe(all_values)})
        for subtype in ("missing_package", "wrong_version"):
            subtype_values = [
                int(row[question])
                for row in method_rows
                if row["subtype"] == subtype
                for question in QUESTIONS
            ]
            summary_rows.append({"scope": subtype, "method": method, "question": "all_items", **describe(subtype_values)})

    participant_means: list[dict[str, str | float]] = []
    for participant, rows in sorted(by_participant.items()):
        for method in METHODS:
            values = [int(row[question]) for row in rows if row["explanation_method"] == method for question in QUESTIONS]
            participant_means.append({"participant_id": participant, "method": method, "mean_rating": round(statistics.fmean(values), 3)})

    participant_method_summary = []
    for method in METHODS:
        values = [row["mean_rating"] for row in participant_means if row["method"] == method]
        participant_method_summary.append({"method": method, **describe_continuous(values)})
    participant_lookup = {
        (row["participant_id"], row["method"]): row["mean_rating"]
        for row in participant_means
    }
    differences = [
        participant_lookup[(participant, "llm")] - participant_lookup[(participant, "resolver_template")]
        for participant in sorted(by_participant)
    ]
    paired_difference_summary = {
        "direction": "llm_minus_template",
        **describe_continuous(differences),
        "llm_higher": sum(value > 0 for value in differences),
        "same": sum(value == 0 for value in differences),
        "resolver_template_higher": sum(value < 0 for value in differences),
    }

    audit = {
        "input_file": str(input_path),
        "raw_rows": len(raw_rows),
        "excluded_empty_rows": excluded_empty_rows,
        "valid_rating_rows": len(valid_rows),
        "participants": len(by_participant),
        "rows_per_participant": sorted(Counter(len(rows) for rows in by_participant.values()).items()),
        "ratings_per_method": {method: sum(row["explanation_method"] == method for row in valid_rows) for method in METHODS},
        "responses_per_variant": dict(Counter(row["survey_variant"] for row in valid_rows)),
        "note": "Descriptive comparison only. Repeated ratings from the same participant are not treated as independent observations.",
    }
    with (output_dir / "comparison_audit.json").open("w", encoding="utf-8") as handle:
        json.dump(audit, handle, indent=2)
    with (output_dir / "comparison_summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)
    with (output_dir / "comparison_participant_means.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("participant_id", "method", "mean_rating"))
        writer.writeheader()
        writer.writerows(participant_means)
    with (output_dir / "comparison_participant_method_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "condition_means": participant_method_summary,
                "within_participant_difference": paired_difference_summary,
            },
            handle,
            indent=2,
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: analyze_human_explanation_comparison.py PATH_TO_NORMALISED_CSV")
    main(sys.argv[1])
