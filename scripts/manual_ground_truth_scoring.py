#!/usr/bin/env python3

"""ManualGroundTruthScoring (i8): score ErrorClassifier and PyPI
distribution-resolution output against manually filled ground-truth
labels.

This module never invents, infers, or defaults a "correct" label from the
pipeline's own prediction - every function here only reads a `manual_*`
field a human has already filled in (scripts/freeze_manual_samples.py
produces the empty template; a human fills it in later, entirely outside
this codebase). A row whose manual field is still blank/None is skipped
and counted separately, never silently treated as either correct or
incorrect.
"""

from typing import Any, Dict, Iterable, List, Optional, Tuple


def _is_filled(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


# --- generic classification scoring (scope status / subtype) --------------

def split_filled_rows(
    rows: List[Dict[str, Any]], manual_field: str
) -> Tuple[List[Dict[str, Any]], int]:
    """Return (rows with manual_field filled in, count skipped because it
    was blank)."""
    filled = [r for r in rows if _is_filled(r.get(manual_field))]
    return filled, len(rows) - len(filled)


def binary_confusion(
    rows: List[Dict[str, Any]],
    predicted_field: str,
    manual_field: str,
    positive_value: str = "usable",
) -> Dict[str, int]:
    """TP/FP/FN/TN for a binary field (default: scope_status, positive
    class "usable"), per the frozen methodology §2: TP = predicted
    positive, manually confirmed positive; FP = predicted positive,
    manually negative; FN = predicted negative, manually positive; TN =
    predicted negative, manually negative."""
    tp = fp = fn = tn = 0
    for row in rows:
        predicted_positive = row.get(predicted_field) == positive_value
        actual_positive = row.get(manual_field) == positive_value
        if predicted_positive and actual_positive:
            tp += 1
        elif predicted_positive and not actual_positive:
            fp += 1
        elif not predicted_positive and actual_positive:
            fn += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def binary_metrics(confusion: Dict[str, int]) -> Dict[str, Optional[float]]:
    tp, fp, fn, tn = confusion["tp"], confusion["fp"], confusion["fn"], confusion["tn"]
    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)) if (precision and recall and (precision + recall)) else None
    accuracy = (tp + tn) / total if total else None
    return {"precision": precision, "recall": recall, "f1": f1, "accuracy": accuracy}


def confusion_matrix(
    rows: List[Dict[str, Any]], predicted_field: str, manual_field: str
) -> Dict[str, Dict[str, int]]:
    """{actual_label: {predicted_label: count}} multi-class confusion
    matrix, over the union of labels actually observed in either field -
    never assumes a fixed label set, so an unexpected label is still
    visible rather than silently dropped."""
    matrix: Dict[str, Dict[str, int]] = {}
    for row in rows:
        actual = str(row.get(manual_field))
        predicted = str(row.get(predicted_field))
        matrix.setdefault(actual, {})
        matrix[actual][predicted] = matrix[actual].get(predicted, 0) + 1
    return matrix


def per_class_precision_recall_f1(matrix: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, Optional[float]]]:
    """Per-class precision/recall/F1 from a confusion_matrix() result. A
    class is any label appearing as either an actual or predicted value."""
    labels = set(matrix.keys())
    for predictions in matrix.values():
        labels.update(predictions.keys())

    result: Dict[str, Dict[str, Optional[float]]] = {}
    for label in labels:
        tp = matrix.get(label, {}).get(label, 0)
        fp = sum(matrix.get(other, {}).get(label, 0) for other in labels if other != label)
        fn = sum(count for predicted, count in matrix.get(label, {}).items() if predicted != label)
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        f1 = (2 * precision * recall / (precision + recall)) if (precision and recall and (precision + recall)) else None
        result[label] = {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}
    return result


def overall_accuracy(matrix: Dict[str, Dict[str, int]]) -> Optional[float]:
    """Naive, sample-level overall accuracy. Only meaningful when the
    scored rows ARE (or are a simple random sample of) the population -
    NEVER report this for a stratified sample that deliberately
    oversampled rare classes (methodology §D option B); use
    prevalence_weighted_accuracy() instead in that case."""
    correct = sum(matrix.get(label, {}).get(label, 0) for label in matrix)
    total = sum(sum(predictions.values()) for predictions in matrix.values())
    return correct / total if total else None


PREVALENCE_WEIGHTED_ACCURACY_CAVEAT = (
    "This re-weighting is only a valid population-level estimate if `population_weights` comes "
    "from a source INDEPENDENT of the classifier being evaluated. Subtype counts derived from the "
    "same pipeline's own classification of the full 214-record dataset (e.g. missing_package=179, "
    "wrong_version=21, system_library=10, mapping_unknown=4) are NOT independent ground truth - "
    "using them as weights implicitly assumes the pipeline's population-wide classification is "
    "already correct, which is exactly what this metric is trying to measure. Do not present the "
    "resulting number as population-wide classifier accuracy in a thesis or report unless the "
    "population weights are independently known (e.g. from a full manual audit of all 214 records) "
    "or a properly justified design-based estimator is used instead. See "
    "docs/i8-evaluation-methodology.md."
)


def prevalence_weighted_accuracy(
    matrix: Dict[str, Dict[str, int]], population_weights: Dict[str, float]
) -> Optional[float]:
    """Population-level accuracy estimate from a deliberately class-
    oversampled confusion matrix: each class's own observed accuracy
    (within the sample) is re-weighted by its TRUE population share
    (`population_weights`, e.g. {"missing_package": 179/214, ...}) rather
    than by its inflated sample share. Classes missing from `matrix` (never
    sampled) are simply not represented in the weighted sum - the caller
    is responsible for making sure every class with nonzero population
    weight was actually sampled, or documenting the gap.

    CAUTION - see PREVALENCE_WEIGHTED_ACCURACY_CAVEAT: this is only a valid
    population estimate when `population_weights` is independently known,
    not derived from the same classifier's own predictions over the
    population."""
    weighted_sum = 0.0
    total_weight = 0.0
    for label, predictions in matrix.items():
        class_total = sum(predictions.values())
        if class_total == 0:
            continue
        class_correct = predictions.get(label, 0)
        class_accuracy = class_correct / class_total
        weight = population_weights.get(label)
        if weight is None:
            continue
        weighted_sum += class_accuracy * weight
        total_weight += weight
    if total_weight == 0:
        return None
    # Re-normalize by the weight actually covered, so a class missing from
    # population_weights (not sampled) does not silently shrink the result
    # toward zero instead of being excluded from the average.
    return weighted_sum / total_weight


# --- failing-module extraction accuracy (exact match, not a classifier) ---

def failing_module_exact_match_accuracy(
    rows: List[Dict[str, Any]], predicted_field: str, manual_field: str
) -> Optional[float]:
    """Exact-string-match accuracy only - deliberately NOT a
    precision/recall/F1/confusion-matrix metric (methodology §2:
    failing-module extraction has an unbounded label space, so those
    metrics would be meaningless here)."""
    if not rows:
        return None
    correct = sum(
        1 for r in rows if str(r.get(predicted_field) or "").strip() == str(r.get(manual_field) or "").strip()
    )
    return correct / len(rows)


# --- classifier scoring entry point ----------------------------------------

def score_classifier_sample(
    rows: List[Dict[str, Any]],
    population_weights: Optional[Dict[str, float]] = None,
    treat_as_full_population: bool = False,
) -> Dict[str, Any]:
    """Score one manually-labeled classifier ground-truth sample (see
    scripts/freeze_manual_samples.py for the expected column names:
    predicted_scope_status/manual_scope_status,
    predicted_subtype/manual_subtype,
    predicted_failing_module/manual_failing_module).

    `treat_as_full_population=True` (methodology §D option A: all 214
    labeled) enables plain overall_accuracy(). Otherwise
    (methodology §D option B: stratified oversample) overall_accuracy() is
    still returned for transparency but flagged not-population-
    representative, and prevalence_weighted_accuracy() is computed if
    `population_weights` is supplied - see PREVALENCE_WEIGHTED_ACCURACY_CAVEAT
    (also attached to the result as
    subtype.prevalence_weighted_overall_accuracy_caveat): that number is
    only a valid population estimate when `population_weights` is
    independently known, not derived from the same classifier's own
    predictions over the population. Report `naive_overall_accuracy` as
    "manual validation sample accuracy", never as population-wide accuracy,
    unless treat_as_full_population is True."""
    scope_rows, scope_skipped = split_filled_rows(rows, "manual_scope_status")
    subtype_rows, subtype_skipped = split_filled_rows(rows, "manual_subtype")
    module_rows, module_skipped = split_filled_rows(rows, "manual_failing_module")

    scope_confusion = binary_confusion(scope_rows, "predicted_scope_status", "manual_scope_status")
    subtype_matrix = confusion_matrix(subtype_rows, "predicted_subtype", "manual_subtype")

    weighted_accuracy = None
    if population_weights is not None:
        weighted_accuracy = prevalence_weighted_accuracy(subtype_matrix, population_weights)

    return {
        "n_rows": len(rows),
        "scope_status": {
            "n_scored": len(scope_rows),
            "n_skipped_unfilled": scope_skipped,
            "confusion": scope_confusion,
            "metrics": binary_metrics(scope_confusion),
        },
        "subtype": {
            "n_scored": len(subtype_rows),
            "n_skipped_unfilled": subtype_skipped,
            "confusion_matrix": subtype_matrix,
            "per_class": per_class_precision_recall_f1(subtype_matrix),
            "naive_overall_accuracy": overall_accuracy(subtype_matrix),
            "naive_overall_accuracy_is_population_representative": treat_as_full_population,
            "naive_overall_accuracy_label": (
                f"Manual validation sample accuracy (n={len(subtype_rows)})"
                if not treat_as_full_population
                else f"Population accuracy (all {len(subtype_rows)} records manually labeled)"
            ),
            "prevalence_weighted_overall_accuracy": weighted_accuracy,
            "prevalence_weighted_overall_accuracy_caveat": (
                PREVALENCE_WEIGHTED_ACCURACY_CAVEAT if weighted_accuracy is not None else None
            ),
        },
        "failing_module": {
            "n_scored": len(module_rows),
            "n_skipped_unfilled": module_skipped,
            "exact_match_accuracy": failing_module_exact_match_accuracy(
                module_rows, "predicted_failing_module", "manual_failing_module"
            ),
        },
    }


# --- PyPI distribution-resolution scoring ----------------------------------

def _normalize_distribution_name(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None
    return str(name).strip().lower().replace("_", "-").replace(".", "-")


def score_distribution_resolution_sample(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Distribution Resolution Accuracy = correct import-name ->
    PyPI-distribution resolutions / manually checked resolutions. Expects
    columns `pipeline_resolved_distribution` (may be blank/None if the
    pipeline abstained as mapping_unknown) and `manual_correct_distribution`
    (filled by a human independently). A pipeline abstention with a
    human-confirmed real distribution counts as INCORRECT - this is the
    honest way to surface static-mapping-table coverage gaps, not a
    metric artifact to explain away.

    NO ranking metric (Precision@k/Recall@k/MRR/nDCG) is computed here: the
    retriever returns candidates sorted newest-first, not ranked by
    relevance (scripts/pypi_retriever.py retrieve()), so there is nothing
    to rank-evaluate."""
    rows_with_labels, skipped = split_filled_rows(rows, "manual_correct_distribution")

    correct = 0
    per_row = []
    for row in rows_with_labels:
        predicted = _normalize_distribution_name(row.get("pipeline_resolved_distribution"))
        manual = _normalize_distribution_name(row.get("manual_correct_distribution"))
        is_correct = predicted is not None and predicted == manual
        if is_correct:
            correct += 1
        per_row.append(
            {
                "import_name": row.get("import_name"),
                "pipeline_resolved_distribution": row.get("pipeline_resolved_distribution"),
                "manual_correct_distribution": row.get("manual_correct_distribution"),
                "correct": is_correct,
            }
        )

    n_checked = len(rows_with_labels)
    return {
        "n_rows": len(rows),
        "n_checked": n_checked,
        "n_skipped_unfilled": skipped,
        "n_correct": correct,
        "distribution_resolution_accuracy": (correct / n_checked) if n_checked else None,
        "per_row": per_row,
    }
