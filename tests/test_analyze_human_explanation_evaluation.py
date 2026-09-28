import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_human_explanation_evaluation as ah


# --- rating parsing / validation ---------------------------------------------

def test_parse_rating_accepts_1_to_5():
    assert ah._parse_rating("1") == 1
    assert ah._parse_rating("5") == 5
    assert ah._parse_rating(3) == 3


def test_parse_rating_blank_is_missing_not_zero():
    assert ah._parse_rating(None) is None
    assert ah._parse_rating("") is None
    assert ah._parse_rating("   ") is None


def test_parse_rating_rejects_out_of_range():
    with pytest.raises(ValueError):
        ah._parse_rating("0")
    with pytest.raises(ValueError):
        ah._parse_rating("6")


def test_parse_rating_rejects_non_integer():
    with pytest.raises(ValueError):
        ah._parse_rating("agree")


def _write_response_csv(path, rows):
    fieldnames = ah.REQUIRED_COLUMNS
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _base_row(**overrides):
    row = {
        "participant_id": "P01",
        "survey_variant": "A",
        "example_id": "1",
        "notebook_execution_id": "62",
        "subtype": "missing_package",
        "q1_understanding": "4",
        "q2_satisfaction": "4",
        "q3_detail": "3",
        "q4_completeness": "4",
        "q5_usefulness": "5",
        "q6_perceived_correctness": "4",
    }
    row.update(overrides)
    return row


def test_load_responses_parses_valid_rows(tmp_path):
    path = tmp_path / "responses.csv"
    _write_response_csv(path, [_base_row()])
    rows = ah.load_responses(path)
    assert len(rows) == 1
    assert rows[0]["q1_understanding"] == 4
    assert rows[0]["q3_detail"] == 3


def test_load_responses_keeps_blank_rating_as_none(tmp_path):
    path = tmp_path / "responses.csv"
    _write_response_csv(path, [_base_row(q5_usefulness="")])
    rows = ah.load_responses(path)
    assert rows[0]["q5_usefulness"] is None


def test_load_responses_raises_with_line_number_on_bad_rating(tmp_path):
    path = tmp_path / "responses.csv"
    _write_response_csv(path, [_base_row(), _base_row(q2_satisfaction="9")])
    with pytest.raises(ValueError, match="line 3"):
        ah.load_responses(path)


def test_load_responses_raises_on_missing_column(tmp_path):
    path = tmp_path / "responses.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["participant_id"])
        writer.writeheader()
        writer.writerow({"participant_id": "P01"})
    with pytest.raises(ValueError, match="missing required column"):
        ah.load_responses(path)


def test_load_responses_empty_file_returns_empty_list(tmp_path):
    path = tmp_path / "responses.csv"
    _write_response_csv(path, [])
    assert ah.load_responses(path) == []


# --- item_summary -------------------------------------------------------------

def test_item_summary_basic_stats():
    summary = ah.item_summary([1, 2, 3, 4, 5])
    assert summary["n"] == 5
    assert summary["median"] == 3
    assert summary["iqr"] == 2.0
    assert summary["distribution"] == {"1": 1, "2": 1, "3": 1, "4": 1, "5": 1}
    assert summary["pct_agree_or_strongly_agree"] == 40.0  # ratings 4 and 5 -> 2/5


def test_item_summary_all_high_ratings():
    summary = ah.item_summary([4, 4, 4, 5, 5])
    assert summary["median"] == 4
    assert summary["iqr"] == 1.0
    assert summary["pct_agree_or_strongly_agree"] == 100.0


def test_item_summary_zero_responses_returns_nulls_not_crash():
    summary = ah.item_summary([])
    assert summary["n"] == 0
    assert summary["median"] is None
    assert summary["iqr"] is None
    assert summary["pct_agree_or_strongly_agree"] is None
    assert summary["distribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}


def test_item_summary_single_response_iqr_is_zero():
    summary = ah.item_summary([3])
    assert summary["n"] == 1
    assert summary["median"] == 3
    assert summary["iqr"] == 0.0


# --- summarize / build_report --------------------------------------------------

def test_summarize_groups_by_item_only():
    rows = [_normalize(_base_row()), _normalize(_base_row(q1_understanding="2"))]
    summary = ah.summarize(rows)
    assert set(summary.keys()) == set(ah.ITEMS)
    assert summary["q1_understanding"]["n"] == 2


def _normalize(row):
    """Turn a raw string-valued fixture row into the parsed-rating shape
    load_responses() would produce."""
    parsed = dict(row)
    for item in ah.ITEMS:
        parsed[item] = ah._parse_rating(row[item])
    return parsed


def test_build_report_structure_and_subtype_grouping():
    rows = [
        _normalize(_base_row(participant_id="P01", example_id="1", subtype="missing_package")),
        _normalize(_base_row(participant_id="P02", example_id="10", subtype="wrong_version", q1_understanding="2")),
    ]
    report = ah.build_report(rows)
    assert report["n_response_rows"] == 2
    assert report["n_distinct_participants"] == 2
    assert set(report["by_subtype"].keys()) == {"missing_package", "wrong_version"}
    assert report["by_subtype"]["missing_package"]["q1_understanding"]["n"] == 1
    assert report["by_subtype"]["wrong_version"]["q1_understanding"]["n"] == 1
    assert set(report["per_example"].keys()) == {"1", "10"}
    # never a default composite score
    assert report["composite_score"] is None
    # the subtype-imbalance caveat is always present, regardless of the data passed in
    assert "descriptive only" in report["note_on_subtype_comparison"]


# --- Cronbach's alpha -----------------------------------------------------------

def test_cronbachs_alpha_perfectly_correlated_items_is_one():
    # Every item within a row takes the same value; across rows the values
    # differ (5, 3, 1) - items are perfectly correlated with each other.
    rows = [
        _normalize(_base_row(**{item: "5" for item in ah.ITEMS})),
        _normalize(_base_row(**{item: "3" for item in ah.ITEMS})),
        _normalize(_base_row(**{item: "1" for item in ah.ITEMS})),
    ]
    alpha = ah.cronbachs_alpha(rows)
    assert alpha == pytest.approx(1.0)


def test_cronbachs_alpha_none_with_fewer_than_two_complete_rows():
    rows = [_normalize(_base_row())]
    assert ah.cronbachs_alpha(rows) is None


def test_cronbachs_alpha_none_with_zero_variance():
    rows = [
        _normalize(_base_row(**{item: "3" for item in ah.ITEMS})),
        _normalize(_base_row(**{item: "3" for item in ah.ITEMS})),
    ]
    assert ah.cronbachs_alpha(rows) is None


def test_cronbachs_alpha_ignores_incomplete_rows():
    complete = [
        _normalize(_base_row(**{item: "5" for item in ah.ITEMS})),
        _normalize(_base_row(**{item: "1" for item in ah.ITEMS})),
    ]
    incomplete = _normalize(_base_row(q6_perceived_correctness=""))
    alpha_without_incomplete = ah.cronbachs_alpha(complete)
    alpha_with_incomplete = ah.cronbachs_alpha(complete + [incomplete])
    assert alpha_with_incomplete == alpha_without_incomplete


# --- CLI: graceful no-data behaviour -------------------------------------------

def test_main_with_zero_rows_does_not_crash(tmp_path, capsys):
    responses = tmp_path / "responses.csv"
    _write_response_csv(responses, [])
    out_dir = tmp_path / "analysis"

    import argparse

    original_argv = sys.argv
    sys.argv = ["analyze_human_explanation_evaluation.py", "--responses", str(responses), "--out-dir", str(out_dir)]
    try:
        ah.main()
    finally:
        sys.argv = original_argv

    captured = capsys.readouterr()
    assert "has not been conducted yet" in captured.out
    assert not out_dir.exists()
