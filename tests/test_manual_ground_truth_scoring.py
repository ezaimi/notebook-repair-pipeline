import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import manual_ground_truth_scoring as gts


# --- binary scope-status metrics -----------------------------------------------

def test_binary_confusion_and_metrics():
    rows = [
        {"predicted_scope_status": "usable", "manual_scope_status": "usable"},  # TP
        {"predicted_scope_status": "usable", "manual_scope_status": "excluded"},  # FP
        {"predicted_scope_status": "excluded", "manual_scope_status": "usable"},  # FN
        {"predicted_scope_status": "excluded", "manual_scope_status": "excluded"},  # TN
    ]
    confusion = gts.binary_confusion(rows, "predicted_scope_status", "manual_scope_status")
    assert confusion == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}
    metrics = gts.binary_metrics(confusion)
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["accuracy"] == 0.5


def test_split_filled_rows_skips_blank_manual_field():
    rows = [
        {"manual_scope_status": "usable"},
        {"manual_scope_status": ""},
        {"manual_scope_status": None},
        {},
    ]
    filled, skipped = gts.split_filled_rows(rows, "manual_scope_status")
    assert len(filled) == 1
    assert skipped == 3


# --- subtype confusion matrix / per-class metrics ------------------------------

def test_confusion_matrix_and_per_class_metrics():
    rows = [
        {"predicted_subtype": "missing_package", "manual_subtype": "missing_package"},
        {"predicted_subtype": "missing_package", "manual_subtype": "missing_package"},
        {"predicted_subtype": "missing_package", "manual_subtype": "wrong_version"},  # misclassified
        {"predicted_subtype": "wrong_version", "manual_subtype": "wrong_version"},
    ]
    matrix = gts.confusion_matrix(rows, "predicted_subtype", "manual_subtype")
    assert matrix["missing_package"]["missing_package"] == 2
    assert matrix["wrong_version"]["missing_package"] == 1
    assert matrix["wrong_version"]["wrong_version"] == 1

    per_class = gts.per_class_precision_recall_f1(matrix)
    # missing_package: tp=2 (both correctly predicted); fp=1 (the
    # actually-wrong_version row was predicted missing_package); fn=0
    # (every actual missing_package row was predicted correctly).
    assert per_class["missing_package"]["tp"] == 2
    assert per_class["missing_package"]["fp"] == 1
    assert per_class["missing_package"]["fn"] == 0
    # wrong_version: tp=1; fn=1 (the actual wrong_version row that was
    # mispredicted as missing_package).
    assert per_class["wrong_version"]["tp"] == 1
    assert per_class["wrong_version"]["fn"] == 1


def test_overall_accuracy():
    matrix = {"a": {"a": 3, "b": 1}, "b": {"b": 2}}
    assert gts.overall_accuracy(matrix) == 5 / 6


def test_overall_accuracy_empty_matrix_returns_none():
    assert gts.overall_accuracy({}) is None


# --- prevalence-weighted overall accuracy (deliberately oversampled rare classes) --

def test_prevalence_weighted_accuracy_reweights_by_true_population_share():
    # Sample deliberately oversamples "rare" (10 rows, 100% accurate) relative
    # to "common" (2 rows, 50% accurate) - a naive overall accuracy would be
    # dominated by the oversampled rare class (11/12 = 91.6%), but the true
    # population is 90% common / 10% rare, so the weighted estimate should be
    # much closer to the common class's own accuracy.
    matrix = {
        "common": {"common": 1, "rare": 1},  # 1/2 = 50% accurate
        "rare": {"rare": 10},  # 10/10 = 100% accurate
    }
    population_weights = {"common": 0.9, "rare": 0.1}
    weighted = gts.prevalence_weighted_accuracy(matrix, population_weights)
    assert weighted == pytest.approx(0.9 * 0.5 + 0.1 * 1.0)


def test_prevalence_weighted_accuracy_returns_none_for_empty_weights():
    matrix = {"a": {"a": 1}}
    assert gts.prevalence_weighted_accuracy(matrix, {}) is None


# --- failing-module exact match (not a classification metric) -----------------

def test_failing_module_exact_match_accuracy():
    rows = [
        {"predicted_failing_module": "sklearn", "manual_failing_module": "sklearn"},
        {"predicted_failing_module": "cv2", "manual_failing_module": "opencv"},
    ]
    assert gts.failing_module_exact_match_accuracy(rows, "predicted_failing_module", "manual_failing_module") == 0.5


def test_failing_module_exact_match_accuracy_empty_returns_none():
    assert gts.failing_module_exact_match_accuracy([], "predicted_failing_module", "manual_failing_module") is None


# --- classifier scoring entry point ---------------------------------------------

def test_score_classifier_sample_skips_unfilled_rows():
    rows = [
        {
            "predicted_scope_status": "usable",
            "manual_scope_status": "usable",
            "predicted_subtype": "missing_package",
            "manual_subtype": "missing_package",
            "predicted_failing_module": "sklearn",
            "manual_failing_module": "sklearn",
        },
        {
            "predicted_scope_status": "usable",
            "manual_scope_status": "",
            "predicted_subtype": "missing_package",
            "manual_subtype": "",
            "predicted_failing_module": "numpy",
            "manual_failing_module": "",
        },
    ]
    result = gts.score_classifier_sample(rows)
    assert result["n_rows"] == 2
    assert result["scope_status"]["n_scored"] == 1
    assert result["scope_status"]["n_skipped_unfilled"] == 1
    assert result["subtype"]["n_scored"] == 1
    assert result["failing_module"]["n_scored"] == 1


def test_score_classifier_sample_with_population_weights():
    rows = [
        {"predicted_subtype": "missing_package", "manual_subtype": "missing_package"},
        {"predicted_subtype": "wrong_version", "manual_subtype": "wrong_version"},
    ]
    result = gts.score_classifier_sample(rows, population_weights={"missing_package": 0.85, "wrong_version": 0.15})
    assert result["subtype"]["prevalence_weighted_overall_accuracy"] == 1.0


def test_score_classifier_sample_flags_naive_accuracy_representativeness():
    rows = [{"predicted_subtype": "missing_package", "manual_subtype": "missing_package"}]
    result_sample = gts.score_classifier_sample(rows, treat_as_full_population=False)
    assert result_sample["subtype"]["naive_overall_accuracy_is_population_representative"] is False
    result_full = gts.score_classifier_sample(rows, treat_as_full_population=True)
    assert result_full["subtype"]["naive_overall_accuracy_is_population_representative"] is True


# --- PyPI distribution-resolution scoring ---------------------------------------

def test_score_distribution_resolution_sample_correct_and_incorrect():
    rows = [
        {"import_name": "sklearn", "pipeline_resolved_distribution": "scikit-learn", "manual_correct_distribution": "scikit-learn"},
        {"import_name": "cv2", "pipeline_resolved_distribution": "opencv-python", "manual_correct_distribution": "opencv-python-headless"},
        {"import_name": "pandas", "pipeline_resolved_distribution": "pandas", "manual_correct_distribution": "pandas"},
        {"import_name": "unfilled", "pipeline_resolved_distribution": None, "manual_correct_distribution": ""},
    ]
    result = gts.score_distribution_resolution_sample(rows)
    assert result["n_rows"] == 4
    assert result["n_checked"] == 3
    assert result["n_skipped_unfilled"] == 1
    assert result["n_correct"] == 2
    assert result["distribution_resolution_accuracy"] == 2 / 3


def test_score_distribution_resolution_sample_pipeline_abstention_with_real_answer_counts_incorrect():
    """A pipeline abstention (mapping_unknown -> no resolved distribution)
    that a human confirms DOES have a real PyPI distribution must count as
    incorrect - this is the honest way to surface static-mapping-table
    coverage gaps, never explained away as "not applicable"."""
    rows = [{"import_name": "statsmodels", "pipeline_resolved_distribution": None, "manual_correct_distribution": "statsmodels"}]
    result = gts.score_distribution_resolution_sample(rows)
    assert result["n_checked"] == 1
    assert result["n_correct"] == 0
    assert result["distribution_resolution_accuracy"] == 0.0


def test_score_distribution_resolution_sample_normalizes_name_variants():
    rows = [{"import_name": "x", "pipeline_resolved_distribution": "scikit_learn", "manual_correct_distribution": "Scikit-Learn"}]
    result = gts.score_distribution_resolution_sample(rows)
    assert result["n_correct"] == 1


def test_score_distribution_resolution_sample_no_ranking_metrics_present():
    """Explicitly confirms Precision@k/Recall@k/MRR/nDCG are never computed
    here - the retriever does not rank candidates by relevance."""
    result = gts.score_distribution_resolution_sample([])
    forbidden = {"precision_at_k", "recall_at_k", "mrr", "ndcg"}
    assert forbidden.isdisjoint(result.keys())
