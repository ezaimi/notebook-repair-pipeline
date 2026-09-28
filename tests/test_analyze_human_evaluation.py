import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_human_evaluation as ahs  # noqa: E402
import analyze_human_explanation_evaluation as ahe  # noqa: E402


# --- fixtures: a tiny two-variant, real-shaped raw export pair ---------------

RATING_HEADER_PREFIX = "Please rate the explanation above.  1 = Strongly disagree · 2 = Disagree · 3 = Neither agree nor disagree · 4 = Agree · 5 = Strongly agree"

CONSENT_COL = "I have read the information above and agree to take part in this study."
BACKGROUND_COLS = [
    "How would you describe your general programming experience?",
    "How familiar are you with Python specifically?",
    "How familiar are you with Jupyter Notebooks?",
    'How often have you personally run into a "missing package" or "package version" error while programming?',
]
FEEDBACK_COLS = [
    "Was anything about the explanations you just read unclear or missing?",
    "What would make explanations like these more helpful to you?",
]


def _header():
    meta = ["Response ID", "Date submitted", "Last page", "Start language", "Seed", CONSENT_COL]
    meta += BACKGROUND_COLS
    meta.append("instructions text (blank)")
    rating_cols = [f"{RATING_HEADER_PREFIX}  [item {i}]" for i in range(1, 37)]
    return meta + rating_cols + FEEDBACK_COLS


def _write_survey(path, data_rows):
    header = _header()
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for row in data_rows:
            writer.writerow(row)


def _complete_row(response_id, ratings=None, feedback=("", "")):
    ratings = ratings or [4] * 36
    assert len(ratings) == 36
    return (
        [response_id, "1980-01-01 00:00:00", "10", "en", "1", "Yes"]
        + ["Intermediate", "Use it regularly", "Used them a few times", "Occasionally"]
        + [""]
        + [str(r) for r in ratings]
        + list(feedback)
    )


def _incomplete_row(response_id, last_page=""):
    return (
        [response_id, "", last_page, "en", "1", "N/A"]
        + [""] * 4
        + [""]
        + [""] * 36
        + ["", ""]
    )


@pytest.fixture()
def two_variant_setup(tmp_path):
    """A minimal but real-shaped fixture: two survey files (variants A and
    B), a tiny examples.csv (2 notebook ids) and variants.csv covering
    exactly the 6 example_order_slots each file's rows reference."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    # Variant A: one complete participant, one incomplete.
    _write_survey(raw_dir / "results-survey739486.csv", [
        _complete_row("1", ratings=[5] * 36, feedback=("unclear bit", "more detail please")),
        _incomplete_row("2", last_page="3"),
    ])
    # Variant B: one complete participant.
    _write_survey(raw_dir / "results-survey776483.csv", [
        _complete_row("1", ratings=[3] * 36),
    ])
    # The other two variants' files still need to exist (the loader always
    # looks for all four); make them present but empty of data rows.
    _write_survey(raw_dir / "results-survey238126.csv", [])
    _write_survey(raw_dir / "results-survey297823.csv", [])

    examples_path = tmp_path / "examples.csv"
    with examples_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["example_id", "notebook_execution_id", "subtype"])
        for example_id, notebook_id, subtype in [
            ("1", "62", "missing_package"),
            ("2", "79", "missing_package"),
            ("3", "94", "missing_package"),
            ("4", "118", "missing_package"),
            ("5", "172", "missing_package"),
            ("6", "211", "missing_package"),
            ("7", "252", "missing_package"),
            ("10", "163", "wrong_version"),
            ("11", "175", "wrong_version"),
        ]:
            writer.writerow([example_id, notebook_id, subtype])

    # Mirrors the real Variant A / Variant B design (mini-scale): every one
    # of A's 6 example ids reappears in B for 3 of the 6 slots (62, 79, 94),
    # so a real reshape's "some notebooks rated by both variants' complete
    # participants" case is actually exercised, and no notebook repeats
    # *within* one participant's own 6 slots (which would never happen in
    # the real, non-repeating per-participant example assignment).
    variants_path = tmp_path / "variants.csv"
    with variants_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["survey_variant", "example_order_slot", "example_id", "notebook_execution_id"])
        variant_a_slots = [("1", "62"), ("2", "79"), ("3", "94"), ("4", "118"), ("5", "172"), ("10", "163")]
        variant_b_slots = [("1", "62"), ("2", "79"), ("3", "94"), ("6", "211"), ("7", "252"), ("11", "175")]
        for slot_idx, (example_id, notebook_id) in enumerate(variant_a_slots, start=1):
            writer.writerow(["A", str(slot_idx), example_id, notebook_id])
        for slot_idx, (example_id, notebook_id) in enumerate(variant_b_slots, start=1):
            writer.writerow(["B", str(slot_idx), example_id, notebook_id])

    return {"raw_dir": raw_dir, "examples_path": examples_path, "variants_path": variants_path}


# --- is_complete --------------------------------------------------------------

def test_is_complete_true_for_full_row():
    header = _header()
    rating_cols = [c for c in header if c.startswith(ahs.RATING_COLUMN_PREFIX)]
    row = dict(zip(header, _complete_row("1")))
    assert ahs.is_complete(row, rating_cols) is True


def test_is_complete_false_without_consent():
    header = _header()
    rating_cols = [c for c in header if c.startswith(ahs.RATING_COLUMN_PREFIX)]
    row = dict(zip(header, _complete_row("1")))
    row[CONSENT_COL] = "N/A"
    assert ahs.is_complete(row, rating_cols) is False


def test_is_complete_false_with_early_last_page():
    header = _header()
    rating_cols = [c for c in header if c.startswith(ahs.RATING_COLUMN_PREFIX)]
    row = dict(zip(header, _incomplete_row("2", last_page="3")))
    assert ahs.is_complete(row, rating_cols) is False


def test_is_complete_ignores_blank_optional_feedback():
    """A response with both free-text fields blank is still complete -
    those two questions are explicitly optional."""
    header = _header()
    rating_cols = [c for c in header if c.startswith(ahs.RATING_COLUMN_PREFIX)]
    row = dict(zip(header, _complete_row("1", feedback=("", ""))))
    assert ahs.is_complete(row, rating_cols) is True


def test_is_complete_false_with_one_blank_rating():
    header = _header()
    rating_cols = [c for c in header if c.startswith(ahs.RATING_COLUMN_PREFIX)]
    ratings = [4] * 36
    row = dict(zip(header, _complete_row("1", ratings=ratings)))
    row[rating_cols[0]] = ""
    assert ahs.is_complete(row, rating_cols) is False


# --- reshape --------------------------------------------------------------------

def test_reshape_counts_and_excludes_incomplete(two_variant_setup):
    response_rows, participant_rows, verification = ahs.reshape(
        two_variant_setup["raw_dir"], two_variant_setup["variants_path"], two_variant_setup["examples_path"]
    )
    assert verification["total_raw_responses"] == 3  # 2 in variant A + 1 in variant B
    assert verification["total_complete_participants"] == 2
    assert verification["total_excluded_responses"] == 1
    assert verification["per_variant"]["A"] == {"raw_responses": 2, "complete_responses": 1, "excluded_responses": 1}
    assert verification["per_variant"]["B"] == {"raw_responses": 1, "complete_responses": 1, "excluded_responses": 0}
    # 2 complete participants x 6 examples = 12 explanation evaluations
    assert len(response_rows) == 12
    assert len(participant_rows) == 2


def test_reshape_maps_slot_to_correct_example_and_subtype(two_variant_setup):
    response_rows, _, _ = ahs.reshape(
        two_variant_setup["raw_dir"], two_variant_setup["variants_path"], two_variant_setup["examples_path"]
    )
    # P01 is variant A's complete participant: slots 1-5 are missing_package
    # notebooks, slot 6 (163) is wrong_version.
    p01_rows = [r for r in response_rows if r["participant_id"] == "P01"]
    assert len(p01_rows) == 6
    assert [r["notebook_execution_id"] for r in p01_rows] == ["62", "79", "94", "118", "172", "163"]
    assert p01_rows[5]["subtype"] == "wrong_version"
    for row in p01_rows[:5]:
        assert row["subtype"] == "missing_package"

    # P02 is variant B's complete participant: slots 1-3 overlap with A
    # (62, 79, 94), slots 4-6 are variant-B-only notebooks.
    p02_rows = [r for r in response_rows if r["participant_id"] == "P02"]
    assert [r["notebook_execution_id"] for r in p02_rows] == ["62", "79", "94", "211", "252", "175"]


def test_reshape_preserves_ratings_per_participant(two_variant_setup):
    response_rows, _, _ = ahs.reshape(
        two_variant_setup["raw_dir"], two_variant_setup["variants_path"], two_variant_setup["examples_path"]
    )
    p01_rows = [r for r in response_rows if r["participant_id"] == "P01"]
    p02_rows = [r for r in response_rows if r["participant_id"] == "P02"]
    assert all(row["q1_understanding"] == "5" for row in p01_rows)
    assert all(row["q1_understanding"] == "3" for row in p02_rows)


def test_reshape_captures_background_and_feedback(two_variant_setup):
    _, participant_rows, _ = ahs.reshape(
        two_variant_setup["raw_dir"], two_variant_setup["variants_path"], two_variant_setup["examples_path"]
    )
    p01 = participant_rows[0]
    assert p01["survey_variant"] == "A"
    assert p01["prog_experience"] == "Intermediate"
    assert p01["open_feedback_1"] == "unclear bit"
    assert p01["open_feedback_2"] == "more detail please"


# --- end-to-end: reshape -> ahe.load_responses -> ahe.build_report -----------

def test_reshaped_csv_round_trips_through_existing_analysis_module(two_variant_setup, tmp_path):
    response_rows, participant_rows, verification = ahs.reshape(
        two_variant_setup["raw_dir"], two_variant_setup["variants_path"], two_variant_setup["examples_path"]
    )
    out_csv = tmp_path / "responses.csv"
    ahs.write_csv(response_rows, ahs.RESPONSE_FIELDNAMES, out_csv)

    parsed = ahe.load_responses(out_csv)
    report = ahe.build_report(parsed)
    assert report["n_response_rows"] == 12  # 2 complete participants x 6 examples
    assert report["n_distinct_participants"] == 2
    assert report["composite_score"] is None


# --- summarize_per_notebook / summarize_background / summarize_qualitative ---

def test_summarize_per_notebook_counts_participants_not_rows(two_variant_setup):
    response_rows, _, _ = ahs.reshape(
        two_variant_setup["raw_dir"], two_variant_setup["variants_path"], two_variant_setup["examples_path"]
    )
    parsed = [
        {**row, **{item: int(row[item]) for item in ahe.ITEMS}}
        for row in response_rows
    ]
    per_notebook = ahs.summarize_per_notebook(parsed)
    # notebook 62 was rated by both P01 (variant A) and P02 (variant B),
    # once each -> 2 participants, 12 pooled Q1-Q6 ratings
    assert per_notebook["62"]["n_participants"] == 2
    assert per_notebook["62"]["n_ratings"] == 12
    # notebook 163 only appears in variant A -> rated by P01 only
    assert per_notebook["163"]["n_participants"] == 1


def test_summarize_background_counts_and_percentages():
    rows = [
        {"prog_experience": "Intermediate", "python_familiarity": "Use it regularly",
         "jupyter_familiarity": "Used them a few times", "dependency_error_familiarity": "Occasionally"},
        {"prog_experience": "Intermediate", "python_familiarity": "Used it a little",
         "jupyter_familiarity": "Used them a few times", "dependency_error_familiarity": "Frequently"},
    ]
    summary = ahs.summarize_background(rows)
    assert summary["n_participants"] == 2
    assert summary["questions"]["prog_experience"]["counts"] == {"Intermediate": 2}
    assert summary["questions"]["prog_experience"]["percentages"]["Intermediate"] == 100.0
    assert summary["questions"]["dependency_error_familiarity"]["counts"] == {"Occasionally": 1, "Frequently": 1}


def test_summarize_qualitative_ignores_blank_and_no_answers():
    rows = [
        {"participant_id": "P01", "open_feedback_1": "", "open_feedback_2": ""},
        {"participant_id": "P02", "open_feedback_1": "No", "open_feedback_2": "more detail please"},
    ]
    q = ahs.summarize_qualitative(rows)
    assert q["n_non_empty_comments"] == 1  # "No" is filtered out as a non-answer
    assert q["n_participants_with_any_comment"] == 1
    assert q["theme_counts"]["wants_more_detail"]["n_comments"] == 1


def test_reconciliation_matches_for_real_pipeline_output(two_variant_setup, tmp_path):
    response_rows, participant_rows, verification = ahs.reshape(
        two_variant_setup["raw_dir"], two_variant_setup["variants_path"], two_variant_setup["examples_path"]
    )
    out_csv = tmp_path / "responses.csv"
    ahs.write_csv(response_rows, ahs.RESPONSE_FIELDNAMES, out_csv)
    parsed = ahe.load_responses(out_csv)
    report = ahs.build_final_report(parsed, participant_rows, verification)
    rec = report["reconciliation"]
    assert rec["explanation_evaluations_match"] is True
    assert rec["likert_ratings_match"] is True
    assert rec["complete_participants_times_6"] == 12
    assert rec["total_likert_ratings"] == 72
