#!/usr/bin/env python3

"""AnalyzeHumanEvaluation: reproducible pipeline from the four raw
LimeSurvey/BPS CSV exports of the completed human explanation-quality
study to the final descriptive report used in the thesis.

This script is the "load raw survey exports" half of the analysis; the
"compute descriptive statistics over a long-format response table" half
already existed in analyze_human_explanation_evaluation.py (written while
the study was still only designed, before any response existed) and is
reused here unmodified rather than re-implemented. Concretely, this
script:

  1. Loads the four de-identified raw survey exports from
     data/human-evaluation/raw/ (this script only reads them).
  2. Maps each raw export file to its survey variant (A/B/C/D), a fixed
     assignment recorded in docs/human-explanation-evaluation-questionnaire.md
     and mirrored in VARIANT_BY_FILENAME below.
  3. Determines, per response row, whether it is "complete" (see
     is_complete()'s docstring for the exact rule) and excludes incomplete
     rows from the main analysis - never silently, always counted and
     reported.
  4. Maps every response position ("block" N of 6 in a participant's
     export row) through that participant's survey_variant and
     data/human-evaluation/human_evaluation_variants.csv's
     example_order_slot column to the correct example_id and
     notebook_execution_id - never assumed to line up across variants.
  5. Writes two derived, long-format artefacts under data/human-evaluation/:
     human_evaluation_responses.csv (one row per participant per rated
     example, shaped like human_evaluation_response_template.csv) and
     human_evaluation_participants.csv (self-reported background plus the
     two optional free-text answers, one row per complete participant, no
     name/email/other identifying field).
  6. Feeds the reshaped responses through
     analyze_human_explanation_evaluation.py's load_responses()/
     build_report()/cronbachs_alpha() - the exact functions and exact
     methodological caveats (Cronbach's alpha as supplementary only, no
     default composite score, subtype-imbalance note) already written
     into that module - and adds the additional breakdowns the thesis
     needs on top: background-question counts, a per-notebook (not
     per-internal-example-id) table, an overall pooled Q1-Q6 distribution,
     and a light qualitative pass over the two free-text questions.
  7. Writes a Likert-distribution figure (thesis/human-eval-likert-
     distribution.png) and table-ready CSV/JSON outputs under
     data/human-evaluation/analysis/.

Every number this script reports is recomputed from the raw CSVs on each
run; nothing here reads or copies any previously written placeholder
value from the thesis.
"""

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze_human_explanation_evaluation as ahe  # noqa: E402

# --- fixed study design (see docs/human-explanation-evaluation-questionnaire.md) --

# Which raw export file is which survey variant. Fixed by how the four
# LimeSurvey instances were built - never inferred from file content.
VARIANT_BY_FILENAME = {
    "results-survey739486.csv": "A",
    "results-survey776483.csv": "B",
    "results-survey238126.csv": "C",
    "results-survey297823.csv": "D",
}

CONSENT_COLUMN = "I have read the information above and agree to take part in this study."
LAST_PAGE_COLUMN = "Last page"
RATING_COLUMN_PREFIX = "Please rate the explanation above"

BACKGROUND_COLUMNS = {
    "prog_experience": "How would you describe your general programming experience?",
    "python_familiarity": "How familiar are you with Python specifically?",
    "jupyter_familiarity": "How familiar are you with Jupyter Notebooks?",
    "dependency_error_familiarity": (
        'How often have you personally run into a "missing package" or '
        '"package version" error while programming?'
    ),
}
FEEDBACK_COLUMNS = {
    "open_feedback_1": "Was anything about the explanations you just read unclear or missing?",
    "open_feedback_2": "What would make explanations like these more helpful to you?",
}

RESPONSE_FIELDNAMES = [
    "participant_id",
    "survey_variant",
    "example_id",
    "notebook_execution_id",
    "subtype",
] + ahe.ITEMS

PARTICIPANT_FIELDNAMES = [
    "participant_id",
    "survey_variant",
    "prog_experience",
    "python_familiarity",
    "jupyter_familiarity",
    "dependency_error_familiarity",
    "open_feedback_1",
    "open_feedback_2",
]


# --- lookups --------------------------------------------------------------

def load_variant_lookup(path: Path) -> Dict[Tuple[str, int], Dict[str, str]]:
    """{(survey_variant, example_order_slot): {example_id, notebook_execution_id}}
    from human_evaluation_variants.csv. This is the *only* place survey
    position is turned into a real example identity - never assumed equal
    across variants (Variant A's block 5 and Variant D's block 1 are both
    notebook_execution_id 172, for instance; nothing about block position
    alone tells you that)."""
    lookup: Dict[Tuple[str, int], Dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            key = (row["survey_variant"].strip(), int(row["example_order_slot"]))
            lookup[key] = {
                "example_id": row["example_id"].strip(),
                "notebook_execution_id": row["notebook_execution_id"].strip(),
            }
    return lookup


def load_subtype_lookup(path: Path) -> Dict[str, str]:
    """{notebook_execution_id: subtype} from human_evaluation_examples.csv."""
    lookup: Dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            lookup[row["notebook_execution_id"].strip()] = row["subtype"].strip()
    return lookup


# --- raw survey loading -----------------------------------------------------

def _rating_columns(fieldnames: List[str]) -> List[str]:
    cols = [c for c in fieldnames if c.startswith(RATING_COLUMN_PREFIX)]
    if len(cols) != 36:
        raise ValueError(
            f"expected 36 rating columns (6 examples x 6 items), found {len(cols)}"
        )
    return cols


def is_complete(raw_row: Dict[str, str], rating_cols: List[str]) -> bool:
    """A response row is "complete" iff: (a) consent was given, (b) the
    survey's own Last page marker shows the final page (10) was reached,
    and (c) all 36 rating cells (6 examples x 6 items) are non-blank. In
    the four exported files these three conditions coincide exactly for
    every one of the 18 raw rows - the 3 excluded rows all have a blank
    Last page or an early Last page (1 or 3) *and* zero filled rating
    cells, never a partially-filled participant. This function checks all
    three anyway, rather than relying on that coincidence, so a
    differently-shaped future export (e.g. a participant who reached page
    10 but skipped one rating item) is still handled by an explicit rule
    instead of silently included or excluded. This function never inspects
    the two optional free-text columns - an empty free-text answer does
    not make a response incomplete."""
    if raw_row.get(CONSENT_COLUMN, "").strip().lower() != "yes":
        return False
    if raw_row.get(LAST_PAGE_COLUMN, "").strip() != "10":
        return False
    for col in rating_cols:
        if raw_row.get(col, "").strip() == "":
            return False
    return True


def load_raw_survey(path: Path) -> Tuple[List[str], List[str], List[Dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rating_cols = _rating_columns(fieldnames)
        rows = [dict(r) for r in reader]
    return fieldnames, rating_cols, rows


# --- reshaping ---------------------------------------------------------------

def reshape(
    raw_dir: Path,
    variants_path: Path,
    examples_path: Path,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """Load all four raw exports, keep only complete responses, and reshape
    them into (response_rows, participant_rows, verification). response_rows
    is long-format, one row per participant per rated example (shaped like
    human_evaluation_response_template.csv, ratings still as raw strings -
    validated/parsed later by ahe.load_responses() on the written CSV, so
    there is exactly one place a bad rating value is checked, not two).
    verification records raw/complete/excluded counts per variant and
    overall, for the reconciliation checks in main()."""
    variant_lookup = load_variant_lookup(variants_path)
    subtype_lookup = load_subtype_lookup(examples_path)

    response_rows: List[Dict[str, Any]] = []
    participant_rows: List[Dict[str, Any]] = []
    per_variant: Dict[str, Dict[str, int]] = {}

    participant_counter = 0
    for filename, variant in VARIANT_BY_FILENAME.items():
        path = raw_dir / filename
        fieldnames, rating_cols, raw_rows = load_raw_survey(path)
        n_raw = len(raw_rows)
        n_complete = 0

        for raw_row in raw_rows:
            if not is_complete(raw_row, rating_cols):
                continue
            n_complete += 1
            participant_counter += 1
            participant_id = f"P{participant_counter:02d}"

            participant_rows.append({
                "participant_id": participant_id,
                "survey_variant": variant,
                "prog_experience": raw_row[BACKGROUND_COLUMNS["prog_experience"]].strip(),
                "python_familiarity": raw_row[BACKGROUND_COLUMNS["python_familiarity"]].strip(),
                "jupyter_familiarity": raw_row[BACKGROUND_COLUMNS["jupyter_familiarity"]].strip(),
                "dependency_error_familiarity": raw_row[
                    BACKGROUND_COLUMNS["dependency_error_familiarity"]
                ].strip(),
                "open_feedback_1": raw_row[FEEDBACK_COLUMNS["open_feedback_1"]].strip(),
                "open_feedback_2": raw_row[FEEDBACK_COLUMNS["open_feedback_2"]].strip(),
            })

            # 36 rating columns = 6 blocks of 6 items, in on-page order;
            # block index (0-based) + 1 is the example_order_slot.
            for slot in range(1, 7):
                block = rating_cols[(slot - 1) * 6: slot * 6]
                info = variant_lookup.get((variant, slot))
                if info is None:
                    raise ValueError(
                        f"no variants.csv entry for variant {variant!r} slot {slot}"
                    )
                notebook_execution_id = info["notebook_execution_id"]
                subtype = subtype_lookup.get(notebook_execution_id)
                if subtype is None:
                    raise ValueError(
                        f"no examples.csv entry for notebook_execution_id "
                        f"{notebook_execution_id!r}"
                    )
                row = {
                    "participant_id": participant_id,
                    "survey_variant": variant,
                    "example_id": info["example_id"],
                    "notebook_execution_id": notebook_execution_id,
                    "subtype": subtype,
                }
                for item, col in zip(ahe.ITEMS, block):
                    row[item] = raw_row[col].strip()
                response_rows.append(row)

        per_variant[variant] = {
            "raw_responses": n_raw,
            "complete_responses": n_complete,
            "excluded_responses": n_raw - n_complete,
        }

    verification = {
        "per_variant": per_variant,
        "total_raw_responses": sum(v["raw_responses"] for v in per_variant.values()),
        "total_complete_participants": sum(v["complete_responses"] for v in per_variant.values()),
        "total_excluded_responses": sum(v["excluded_responses"] for v in per_variant.values()),
    }
    return response_rows, participant_rows, verification


def write_csv(rows: List[Dict[str, Any]], fieldnames: List[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# --- background-question summary ---------------------------------------------

def summarize_background(participant_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts and percentages for each background question, over the
    complete participants only. Purely descriptive - no cross-tabulation,
    no claim of representativeness (this is a 15-participant convenience
    sample, see docs/human-explanation-evaluation-questionnaire.md
    Appendix C)."""
    n = len(participant_rows)
    result: Dict[str, Any] = {"n_participants": n, "questions": {}}
    for field in [
        "prog_experience",
        "python_familiarity",
        "jupyter_familiarity",
        "dependency_error_familiarity",
    ]:
        counts: Dict[str, int] = {}
        for row in participant_rows:
            value = row[field] or "(blank)"
            counts[value] = counts.get(value, 0) + 1
        result["questions"][field] = {
            "counts": counts,
            "percentages": {
                k: round(100.0 * v / n, 1) if n else None for k, v in counts.items()
            },
        }
    return result


# --- per-notebook (per-example) summary ---------------------------------------

def summarize_per_notebook(response_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-example results keyed by notebook_execution_id (the identifier
    used throughout the rest of the thesis and in
    Cref{tab:v-human-eval-variants}), not by the internal 1-12 example_id.
    For each of the 12 frozen examples: subtype, number of participants who
    rated it, median across all its pooled Q1-Q6 ratings, and the percentage
    of its Q1-Q6 ratings that are 4 or 5."""
    by_notebook: Dict[str, List[Dict[str, Any]]] = {}
    for row in response_rows:
        by_notebook.setdefault(row["notebook_execution_id"], []).append(row)

    result: Dict[str, Any] = {}
    for notebook_id, rows in sorted(by_notebook.items(), key=lambda kv: int(kv[0])):
        pooled: List[int] = []
        for row in rows:
            for item in ahe.ITEMS:
                if row[item] is not None:
                    pooled.append(row[item])
        n_participants = len(rows)
        if pooled:
            median = statistics.median(pooled)
            pct_4_5 = 100.0 * sum(1 for v in pooled if v >= 4) / len(pooled)
        else:
            median = None
            pct_4_5 = None
        result[notebook_id] = {
            "subtype": rows[0]["subtype"] if rows else None,
            "n_participants": n_participants,
            "n_ratings": len(pooled),
            "median_all_items": median,
            "pct_agree_or_strongly_agree": pct_4_5,
        }
    return result


# --- overall pooled Q1-Q6 distribution -----------------------------------------

def summarize_overall_pooled(response_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """All Q1-Q6 ratings pooled into one distribution - "the overall
    picture" requested alongside the six item-level breakdowns. Reuses
    ahe.item_summary on the concatenation of all six items' values."""
    pooled: List[int] = []
    for row in response_rows:
        for item in ahe.ITEMS:
            if row[item] is not None:
                pooled.append(row[item])
    return ahe.item_summary(pooled)


# --- qualitative free-text pass ------------------------------------------------

_THEME_KEYWORDS = {
    "clear_or_useful": ["clear", "useful", "helpful", "nothing", "everything is clear"],
    "wants_more_detail": ["more detail", "detailed", "more context", "not enough"],
    "repeats_error_without_cause": ["repeat", "restat", "just repeat", "same as the error"],
    "wants_package_or_version_info": [
        "package name", "correct package", "version", "which package", "specific"
    ],
}


def summarize_qualitative(participant_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A short, keyword-driven pass over the two optional free-text
    questions - not a thematic analysis (the study was not designed as a
    qualitative one; see docs/human-explanation-evaluation-questionnaire.md
    Section 6). Only counts comments that actually contain each keyword
    family; never infers a theme from a comment that does not mention it."""
    comments: List[Dict[str, str]] = []
    for row in participant_rows:
        for field in ("open_feedback_1", "open_feedback_2"):
            text = (row.get(field) or "").strip()
            if text and text.lower() not in {"no", "n/a", "none"}:
                comments.append({
                    "participant_id": row["participant_id"],
                    "field": field,
                    "text": text,
                })

    theme_hits: Dict[str, int] = {theme: 0 for theme in _THEME_KEYWORDS}
    theme_participants: Dict[str, set] = {theme: set() for theme in _THEME_KEYWORDS}
    for c in comments:
        lowered = c["text"].lower()
        for theme, keywords in _THEME_KEYWORDS.items():
            if any(kw in lowered for kw in keywords):
                theme_hits[theme] += 1
                theme_participants[theme].add(c["participant_id"])

    return {
        "n_non_empty_comments": len(comments),
        "n_participants_with_any_comment": len({c["participant_id"] for c in comments}),
        "comments": comments,
        "theme_counts": {
            theme: {
                "n_comments": theme_hits[theme],
                "n_participants": len(theme_participants[theme]),
            }
            for theme in _THEME_KEYWORDS
        },
    }


# --- Likert distribution figure ------------------------------------------------

# 5-step diverging palette (blue<->red poles, neutral gray midpoint), each
# arm validated as a 2-step ordinal ramp with
# dataviz/scripts/validate_palette.js (--ordinal --mode light): both arms
# pass lightness-monotone, adjacent-step, light-end-contrast and
# single-hue checks. The neutral midpoint is deliberately low-chroma (that
# is what "neutral" means in a diverging scale) and is not run through the
# categorical chroma-floor check, which does not apply to a diverging
# midpoint.
LIKERT_COLORS = {
    1: "#c62e2d",  # Strongly disagree
    2: "#e2918f",  # Disagree
    3: "#c9c8c2",  # Neither agree nor disagree
    4: "#86b6ef",  # Agree
    5: "#1c5cab",  # Strongly agree
}
LIKERT_LABELS = {
    1: "Strongly disagree",
    2: "Disagree",
    3: "Neither agree nor disagree",
    4: "Agree",
    5: "Strongly agree",
}
ITEM_SHORT_LABELS = {
    "q1_understanding": "Q1. Understand why it failed",
    "q2_satisfaction": "Q2. Satisfying",
    "q3_detail": "Q3. Enough detail",
    "q4_completeness": "Q4. Complete",
    "q5_usefulness": "Q5. Useful",
    "q6_perceived_correctness": "Q6. Seems correct (perceived)",
}


def generate_likert_figure(overall_by_item: Dict[str, Dict[str, Any]], out_path: Path) -> None:
    """Horizontal diverging stacked bar chart, one row per Q1-Q6, showing
    the percentage of ratings in each of the five response categories.
    Disagree-side categories are drawn to the left of a zero line
    (Strongly disagree fully left, Disagree stacked onto it), Neutral is
    split evenly across the zero line, and Agree/Strongly agree stack to
    the right - the standard diverging-stacked-bar construction for Likert
    data, so the reader can compare "how far left/right" items sit at a
    glance instead of only reading raw stacked percentages left-to-right."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    items = list(ahe.ITEMS)
    items_top_to_bottom = list(reversed(items))  # Q1 drawn at the top

    fig, ax = plt.subplots(figsize=(8.6, 3.6), dpi=300)

    for row_idx, item in enumerate(items_top_to_bottom):
        dist = overall_by_item[item]["distribution"]
        n = overall_by_item[item]["n"] or 1
        pct = {k: 100.0 * dist[str(k)] / n for k in range(1, 6)}

        left_stack = -(pct[1] + pct[2] + pct[3] / 2.0)
        cursor = left_stack
        for k in (1, 2, 3, 4, 5):
            width = pct[k]
            ax.barh(
                row_idx, width, left=cursor, height=0.62,
                color=LIKERT_COLORS[k], edgecolor="white", linewidth=0.8,
            )
            if width >= 6:
                ax.text(
                    cursor + width / 2.0, row_idx, f"{width:.0f}%",
                    ha="center", va="center", fontsize=8,
                    color="white" if k in (1, 5) else "#1a1a19",
                )
            cursor += width

    ax.set_yticks(range(len(items_top_to_bottom)))
    ax.set_yticklabels([ITEM_SHORT_LABELS[i] for i in items_top_to_bottom], fontsize=9)
    ax.axvline(0, color="#52514e", linewidth=0.8)
    ax.set_xlabel("Share of ratings (%)", fontsize=9)
    max_extent = 100
    ax.set_xlim(-max_extent, max_extent)
    xticks = list(range(-100, 101, 25))
    ax.set_xticks(xticks)
    ax.set_xticklabels([str(abs(t)) for t in xticks], fontsize=8)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.set_axisbelow(True)
    ax.grid(axis="x", color="#e5e4df", linewidth=0.6, zorder=0)

    legend_handles = [
        Patch(facecolor=LIKERT_COLORS[k], edgecolor="white", label=LIKERT_LABELS[k])
        for k in (1, 2, 3, 4, 5)
    ]
    ax.legend(
        handles=legend_handles, loc="upper center", bbox_to_anchor=(0.5, -0.18),
        ncol=5, frameon=False, fontsize=8, handlelength=1.2, columnspacing=1.2,
    )

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


# --- top-level report ----------------------------------------------------------

def build_final_report(
    response_rows_parsed: List[Dict[str, Any]],
    participant_rows: List[Dict[str, Any]],
    verification: Dict[str, Any],
) -> Dict[str, Any]:
    base_report = ahe.build_report(response_rows_parsed)
    overall_pooled = summarize_overall_pooled(response_rows_parsed)
    per_notebook = summarize_per_notebook(response_rows_parsed)
    background = summarize_background(participant_rows)
    qualitative = summarize_qualitative(participant_rows)

    total_likert_ratings = sum(v["n_ratings"] for v in per_notebook.values())
    reconciliation = {
        "complete_participants_times_6": verification["total_complete_participants"] * 6,
        "n_explanation_evaluations": base_report["n_response_rows"],
        "explanation_evaluations_match": (
            verification["total_complete_participants"] * 6 == base_report["n_response_rows"]
        ),
        "n_explanation_evaluations_times_6": base_report["n_response_rows"] * 6,
        "total_likert_ratings": total_likert_ratings,
        "likert_ratings_match": (
            base_report["n_response_rows"] * 6 == total_likert_ratings
        ),
    }

    return {
        "verification": verification,
        "reconciliation": reconciliation,
        "n_complete_participants": verification["total_complete_participants"],
        "n_explanation_evaluations": base_report["n_response_rows"],
        "n_likert_ratings": total_likert_ratings,
        "background": background,
        "overall_by_item": base_report["overall"],
        "overall_pooled": overall_pooled,
        "by_subtype": base_report["by_subtype"],
        "per_notebook": per_notebook,
        "reliability": base_report["reliability"],
        "qualitative": qualitative,
        "note_on_subtype_comparison": base_report["note_on_subtype_comparison"],
        "composite_score": None,
    }


def write_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def write_per_notebook_csv(per_notebook: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "notebook_execution_id", "subtype", "n_participants", "n_ratings",
            "median_all_items", "pct_agree_or_strongly_agree",
        ])
        for notebook_id, stats in per_notebook.items():
            writer.writerow([
                notebook_id, stats["subtype"], stats["n_participants"], stats["n_ratings"],
                stats["median_all_items"], stats["pct_agree_or_strongly_agree"],
            ])


# --- CLI ------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Load the four raw LimeSurvey CSV exports of the human "
            "explanation-quality study, map them onto the frozen "
            "example/variant design, exclude incomplete responses, and "
            "compute the final descriptive report."
        )
    )
    parser.add_argument(
        "--raw-dir", default="data/human-evaluation/raw",
        help="Directory containing the four raw results-survey*.csv exports.",
    )
    parser.add_argument(
        "--variants", default="data/human-evaluation/human_evaluation_variants.csv",
    )
    parser.add_argument(
        "--examples", default="data/human-evaluation/human_evaluation_examples.csv",
    )
    parser.add_argument(
        "--out-dir", default="data/human-evaluation",
        help="Directory to write the reshaped responses/participants CSVs into.",
    )
    parser.add_argument(
        "--analysis-dir", default="data/human-evaluation/analysis",
        help="Directory to write summary CSV/JSON outputs into.",
    )
    parser.add_argument(
        "--figure", default="thesis/human-eval-likert-distribution.png",
        help="Path to write the Likert distribution figure to.",
    )
    parser.add_argument(
        "--no-figure", action="store_true",
        help="Skip generating the Likert figure (e.g. if matplotlib is unavailable).",
    )
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    out_dir = Path(args.out_dir)
    analysis_dir = Path(args.analysis_dir)

    response_rows, participant_rows, verification = reshape(
        raw_dir, Path(args.variants), Path(args.examples)
    )

    responses_csv = out_dir / "human_evaluation_responses.csv"
    participants_csv = out_dir / "human_evaluation_participants.csv"
    write_csv(response_rows, RESPONSE_FIELDNAMES, responses_csv)
    write_csv(participant_rows, PARTICIPANT_FIELDNAMES, participants_csv)

    # Re-load through ahe.load_responses() so rating values are validated
    # and parsed to int exactly the way that module already does, with a
    # single shared code path for that check.
    response_rows_parsed = ahe.load_responses(responses_csv)

    report = build_final_report(response_rows_parsed, participant_rows, verification)

    write_json(report, analysis_dir / "human_evaluation_final_report.json")
    write_csv(
        [{"participant_id": r["participant_id"], **{k: r[k] for k in PARTICIPANT_FIELDNAMES if k != "participant_id"}}
         for r in participant_rows],
        PARTICIPANT_FIELDNAMES,
        analysis_dir / "participants_with_background.csv",
    )
    ahe.write_summary_csv({"overall": report["overall_by_item"]}, analysis_dir / "summary_overall_by_item.csv", key_column="scope")
    ahe.write_summary_csv(report["by_subtype"], analysis_dir / "summary_by_subtype.csv", key_column="subtype")
    write_per_notebook_csv(report["per_notebook"], analysis_dir / "summary_per_notebook.csv")

    if not args.no_figure:
        generate_likert_figure(report["overall_by_item"], Path(args.figure))

    # --- console verification report (item 18) ---
    print("=== Raw / complete responses per variant ===")
    for variant, v in verification["per_variant"].items():
        print(f"  Variant {variant}: raw={v['raw_responses']} complete={v['complete_responses']} excluded={v['excluded_responses']}")
    print(f"  TOTAL: raw={verification['total_raw_responses']} complete={verification['total_complete_participants']} excluded={verification['total_excluded_responses']}")

    print("\n=== Reconciliation ===")
    rec = report["reconciliation"]
    print(f"  complete_participants x 6 = {rec['complete_participants_times_6']}  vs  explanation_evaluations = {rec['n_explanation_evaluations']}  -> {'OK' if rec['explanation_evaluations_match'] else 'MISMATCH'}")
    print(f"  explanation_evaluations x 6 = {rec['n_explanation_evaluations_times_6']}  vs  total_likert_ratings = {rec['total_likert_ratings']}  -> {'OK' if rec['likert_ratings_match'] else 'MISMATCH'}")

    print("\n=== Q1-Q6 (overall) ===")
    for item in ahe.ITEMS:
        s = report["overall_by_item"][item]
        print(f"  {item}: n={s['n']} median={s['median']} IQR={s['iqr']} %4-5={s['pct_agree_or_strongly_agree']:.1f}" if s["n"] else f"  {item}: n=0")

    print("\n=== Overall pooled (all Q1-Q6 combined) ===")
    op = report["overall_pooled"]
    print(f"  n={op['n']} median={op['median']} IQR={op['iqr']} distribution={op['distribution']} %4-5={op['pct_agree_or_strongly_agree']:.1f}")

    print("\n=== Subtype ===")
    for subtype, per_item in report["by_subtype"].items():
        n_evals = len({(r["participant_id"], r["notebook_execution_id"]) for r in response_rows_parsed if r["subtype"] == subtype})
        print(f"  {subtype}: n_evaluations={n_evals}")
        for item in ahe.ITEMS:
            s = per_item[item]
            print(f"    {item}: n={s['n']} median={s['median']} IQR={s['iqr']} %4-5={s['pct_agree_or_strongly_agree']:.1f}")

    print(f"\n=== Cronbach's alpha (Q1-Q6, supplementary only) ===\n  alpha={report['reliability']['cronbachs_alpha']}")

    print(f"\nWrote reshaped data to {responses_csv} and {participants_csv}")
    print(f"Wrote analysis outputs to {analysis_dir}")
    if not args.no_figure:
        print(f"Wrote Likert figure to {args.figure}")


if __name__ == "__main__":
    main()
