#!/usr/bin/env python3

"""AnalyzeHumanExplanationEvaluation: descriptive analysis of the human
explanation-quality study defined in
docs/human-explanation-evaluation-questionnaire.md and
data/human-evaluation/.

This script analyzes participant responses collected against the frozen
12-example pool (data/human-evaluation/human_evaluation_examples.csv),
selected by diversity-constrained stratified sampling from the final
evaluation run's explanation records using random.Random(seed=42): 9
missing_package examples, one per distinct failing module, plus 3
wrong_version examples, one per distinct (failing_module, error_message)
signature, since the eligible wrong_version population contains only 3
such signatures in total. The exact selection procedure is recorded in
scripts/select_human_evaluation_pool.py and in
docs/human-explanation-evaluation-questionnaire.md Appendix C. This
script only analyzes responses - it does not regenerate explanations,
does not call an LLM, and does not touch any I1-I8 pipeline output; it
only reads a response CSV shaped like
human_evaluation_response_template.csv.

Every reported metric is descriptive (n, median, IQR, 1-5 frequency
distribution, % rating 4-5). No inferential significance test is computed.
Cronbach's alpha is reported only as a supplementary internal-consistency
statistic - see cronbachs_alpha()'s docstring for what it does and does
not mean. No composite "explanation quality score" is computed by
default; item-level results are always the primary output.
"""

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional

ITEMS = [
    "q1_understanding",
    "q2_satisfaction",
    "q3_detail",
    "q4_completeness",
    "q5_usefulness",
    "q6_perceived_correctness",
]

REQUIRED_COLUMNS = [
    "participant_id",
    "survey_variant",
    "example_id",
    "notebook_execution_id",
    "subtype",
] + ITEMS


# --- loading and validation --------------------------------------------------

def _parse_rating(raw: Any) -> Optional[int]:
    """A single Likert cell: None/''/whitespace means "not answered" and is
    kept as None (excluded from that item's n, never imputed - see
    docs/human-explanation-evaluation-questionnaire.md's missing-value
    handling). Anything else must parse as an integer 1-5; any other value
    is a data-entry error, not a value to silently coerce or drop."""
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    try:
        value = int(text)
    except ValueError:
        raise ValueError(f"rating value {raw!r} is not an integer or blank")
    if value < 1 or value > 5:
        raise ValueError(f"rating value {value} is out of the valid 1-5 range")
    return value


def load_responses(path: Path) -> List[Dict[str, Any]]:
    """Load and validate a response CSV shaped like
    human_evaluation_response_template.csv. Raises ValueError, naming the
    exact row and column, on any rating that is present but not a valid
    1-5 integer - never silently drops or coerces a bad value. A blank
    rating is valid (participant skipped that item) and is kept as None."""
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing_columns = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing_columns:
            raise ValueError(f"response file is missing required column(s): {missing_columns}")

        rows = []
        for line_number, raw_row in enumerate(reader, start=2):  # header is line 1
            row = dict(raw_row)
            for item in ITEMS:
                try:
                    row[item] = _parse_rating(row.get(item))
                except ValueError as exc:
                    raise ValueError(f"line {line_number}, column {item!r}: {exc}") from exc
            rows.append(row)
    return rows


# --- per-item descriptive statistics -----------------------------------------

def item_summary(values: List[int]) -> Dict[str, Any]:
    """n, median, IQR, the full 1-5 frequency distribution, and % rating
    4 or 5 ("Agree"/"Strongly agree"), for one item's non-missing ratings.
    Returns nulls throughout when there are zero non-missing ratings,
    rather than raising or reporting a misleading 0."""
    n = len(values)
    distribution = {str(k): values.count(k) for k in range(1, 6)}
    if n == 0:
        return {
            "n": 0,
            "median": None,
            "iqr": None,
            "distribution": distribution,
            "pct_agree_or_strongly_agree": None,
        }

    median = statistics.median(values)
    if n >= 2:
        quartiles = statistics.quantiles(values, n=4, method="inclusive")
        iqr = quartiles[2] - quartiles[0]
    else:
        iqr = 0.0
    pct_4_5 = 100.0 * sum(1 for v in values if v >= 4) / n

    return {
        "n": n,
        "median": median,
        "iqr": iqr,
        "distribution": distribution,
        "pct_agree_or_strongly_agree": pct_4_5,
    }


def _non_missing(rows: List[Dict[str, Any]], item: str) -> List[int]:
    return [r[item] for r in rows if r.get(item) is not None]


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{item: item_summary(...)} over exactly the rows passed in - the
    caller decides the grouping (overall / one subtype / one example)."""
    return {item: item_summary(_non_missing(rows, item)) for item in ITEMS}


# --- reliability (supplementary only) ----------------------------------------

def cronbachs_alpha(rows: List[Dict[str, Any]]) -> Optional[float]:
    """Cronbach's alpha across the six items, computed only over rows with
    a non-missing rating on all six (a "complete" row) - alpha is not
    defined for a row with a missing item, and silently substituting a
    value for it would fabricate data.

    This is a SUPPLEMENTARY internal-consistency statistic only: it
    describes whether the six adapted items tended to move together *in
    this dataset*. It is NOT an inter-rater agreement statistic (it says
    nothing about whether different participants agree with each other),
    it does NOT prove the six items measure one single construct, and it
    must never be used to decide whether the study itself is valid.
    Reporting it, at any value, does not by itself justify computing a
    composite "explanation quality score" - see this module's docstring
    and docs/human-explanation-evaluation-questionnaire.md Appendix D.

    Returns None if fewer than 2 complete rows exist (alpha is undefined
    with fewer than 2 observations) or if every item has zero variance
    across the complete rows (a degenerate, uninformative case)."""
    complete_rows = [r for r in rows if all(r.get(item) is not None for item in ITEMS)]
    n = len(complete_rows)
    if n < 2:
        return None

    item_values = {item: [r[item] for r in complete_rows] for item in ITEMS}
    item_variances = [statistics.variance(item_values[item]) for item in ITEMS]
    total_scores = [sum(r[item] for item in ITEMS) for r in complete_rows]
    total_variance = statistics.variance(total_scores)

    if total_variance == 0:
        return None

    k = len(ITEMS)
    alpha = (k / (k - 1)) * (1 - sum(item_variances) / total_variance)
    return alpha


# --- top-level report ---------------------------------------------------------

def build_report(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Assemble the full descriptive report from validated response rows.
    Every section is descriptive only; see this module's docstring for
    what is deliberately not computed (no significance tests, no default
    composite score, no rater-agreement statistic)."""
    by_subtype: Dict[str, List[Dict[str, Any]]] = {}
    by_example: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_subtype.setdefault(r["subtype"], []).append(r)
        by_example.setdefault(r["example_id"], []).append(r)

    return {
        "n_response_rows": len(rows),
        "n_distinct_participants": len({r["participant_id"] for r in rows}),
        "overall": summarize(rows),
        "by_subtype": {subtype: summarize(subset) for subtype, subset in sorted(by_subtype.items())},
        "per_example": {
            example_id: summarize(subset)
            for example_id, subset in sorted(by_example.items(), key=lambda kv: str(kv[0]))
        },
        "reliability": {
            "cronbachs_alpha": cronbachs_alpha(rows),
            "note": (
                "Supplementary internal-consistency statistic only - not an "
                "inter-rater agreement measure, not proof the six items form "
                "one construct, and not a validity check on the study itself. "
                "See this module's cronbachs_alpha() docstring."
            ),
        },
        "note_on_subtype_comparison": (
            "The example pool contains 9 distinct missing_package cases but "
            "only 3 distinct wrong_version cases (the eligible wrong_version "
            "population had only 3 genuinely distinct error signatures - see "
            "docs/human-explanation-evaluation-questionnaire.md Appendix C). "
            "Any by-subtype comparison above is descriptive only and must not "
            "be read as comparing two equally diverse samples."
        ),
        "composite_score": None,
    }


# --- CLI ----------------------------------------------------------------------

def write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def write_summary_csv(summary: Dict[str, Dict[str, Any]], path: Path, key_column: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([key_column, "item", "n", "median", "iqr", "pct_agree_or_strongly_agree"])
        for key, per_item in summary.items():
            for item, stats in per_item.items():
                writer.writerow([key, item, stats["n"], stats["median"], stats["iqr"], stats["pct_agree_or_strongly_agree"]])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Descriptive analysis of collected human explanation-evaluation responses."
    )
    parser.add_argument(
        "--responses",
        default="data/human-evaluation/human_evaluation_response_template.csv",
        help="Path to a response CSV shaped like human_evaluation_response_template.csv.",
    )
    parser.add_argument(
        "--out-dir",
        default="data/human-evaluation/analysis",
        help="Directory to write summary CSV/JSON files into.",
    )
    args = parser.parse_args()

    responses_path = Path(args.responses)
    rows = load_responses(responses_path)

    if not rows:
        print(
            f"No participant response rows found in {responses_path}. "
            "The human evaluation has not been conducted yet, so there is "
            "nothing to analyze. Run this script again once real responses "
            "have been collected."
        )
        return

    report = build_report(rows)
    out_dir = Path(args.out_dir)

    write_json(report, out_dir / "human_evaluation_summary.json")
    # report["overall"] is a flat {item: item_summary} dict (a single
    # scope), unlike report["by_subtype"]/report["per_example"] which are
    # {key: {item: item_summary}}; write_summary_csv expects the latter
    # shape, so wrap the single overall scope under one explicit key.
    write_summary_csv({"overall": report["overall"]}, out_dir / "summary_overall.csv", key_column="scope")
    write_summary_csv(report["by_subtype"], out_dir / "summary_by_subtype.csv", key_column="subtype")
    write_summary_csv(report["per_example"], out_dir / "summary_per_example.csv", key_column="example_id")

    print(f"Analyzed {report['n_response_rows']} response rows from {report['n_distinct_participants']} participants.")
    print(f"Wrote summaries to {out_dir}")


if __name__ == "__main__":
    main()
