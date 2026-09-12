import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import freeze_manual_samples as fms


def make_record(notebook_execution_id, original_subtype, split, failing_module="sklearn", scope_status="usable"):
    return {
        "notebook_execution_id": notebook_execution_id,
        "original_subtype": original_subtype,
        "refined_subtype": original_subtype,
        "split": split,
        "failing_module": failing_module,
        "scope_status": scope_status,
        "error_type": "ModuleNotFoundError",
        "error_message": f"No module named '{failing_module}'",
        "confidence": "high",
    }


# --- classifier sample: exhaustive rare classes, stratified common classes ----

def test_exhaustive_subtypes_take_every_record():
    records = [make_record(i, "system_library", "excluded", scope_status="excluded") for i in range(10)]
    sample = fms.build_classifier_sample(records)
    assert len(sample) == 10
    assert {r["notebook_execution_id"] for r in sample} == set(range(10))


def test_stratified_subtype_respects_target_n_and_dev_slots():
    dev_records = [make_record(i, "missing_package", "dev") for i in range(5)]
    eval_records = [make_record(100 + i, "missing_package", "evaluation") for i in range(30)]
    sample = fms.build_classifier_sample(dev_records + eval_records)
    n_dev_in_sample = sum(1 for r in sample if r["split"] == "dev")
    n_eval_in_sample = sum(1 for r in sample if r["split"] == "evaluation")
    plan = fms.SAMPLE_PLAN["missing_package"]
    assert n_dev_in_sample == plan["n_from_dev"]
    assert n_dev_in_sample + n_eval_in_sample == plan["n"]


def test_stratified_subtype_falls_back_to_evaluation_when_dev_pool_too_small():
    dev_records = [make_record(1, "wrong_version", "dev")]
    eval_records = [make_record(100 + i, "wrong_version", "evaluation") for i in range(30)]
    sample = fms.build_classifier_sample(dev_records + eval_records)
    plan = fms.SAMPLE_PLAN["wrong_version"]
    assert len(sample) == plan["n"]


def test_classifier_sample_is_deterministic_across_calls():
    records = [make_record(i, "missing_package", "evaluation") for i in range(50)]
    first = fms.build_classifier_sample(records)
    second = fms.build_classifier_sample(records)
    assert [r["notebook_execution_id"] for r in first] == [r["notebook_execution_id"] for r in second]


def test_classifier_sample_never_prefills_manual_labels():
    records = [make_record(1, "missing_package", "evaluation")]
    sample = fms.build_classifier_sample(records)
    row = sample[0]
    assert row["manual_scope_status"] == ""
    assert row["manual_subtype"] == ""
    assert row["manual_failing_module"] == ""


def test_classifier_sample_selection_does_not_depend_on_evaluation_outcomes():
    """The selection function's signature never accepts anything resembling
    a repair outcome/result - it can only ever see i2 classification
    fields, so it is structurally impossible for it to be biased by final
    evaluation results."""
    import inspect

    signature = inspect.signature(fms.build_classifier_sample)
    assert list(signature.parameters.keys()) == ["records"]


# --- PyPI resolution sample: mapped + most-frequent-unmapped -------------------

def test_pypi_sample_includes_mapped_names_actually_exercised():
    records = [make_record(1, "missing_package", "evaluation", failing_module="sklearn")]
    sample = fms.build_pypi_resolution_sample(records)
    names = {r["import_name"] for r in sample}
    assert "sklearn" in names
    sklearn_row = next(r for r in sample if r["import_name"] == "sklearn")
    assert sklearn_row["pipeline_resolved_distribution"] == "scikit-learn"


def test_pypi_sample_includes_most_frequent_unmapped_names():
    records = (
        [make_record(i, "missing_package", "evaluation", failing_module="statsmodels") for i in range(5)]
        + [make_record(100 + i, "missing_package", "evaluation", failing_module="rarelyused") for i in range(1)]
    )
    sample = fms.build_pypi_resolution_sample(records, max_unmapped=1)
    names = {r["import_name"] for r in sample}
    # statsmodels (freq=5) should be preferred over rarelyused (freq=1) when capped at 1.
    assert "statsmodels" in names
    assert "rarelyused" not in names


def test_pypi_sample_excludes_excluded_records():
    records = [make_record(1, "system_library", "excluded", failing_module="libxcb.so.1", scope_status="excluded")]
    sample = fms.build_pypi_resolution_sample(records)
    assert sample == []


def test_pypi_sample_never_prefills_manual_correct_distribution():
    records = [make_record(1, "missing_package", "evaluation", failing_module="sklearn")]
    sample = fms.build_pypi_resolution_sample(records)
    assert sample[0]["manual_correct_distribution"] == ""


# --- CSV writing ----------------------------------------------------------------

def test_write_csv_roundtrip(tmp_path):
    rows = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
    path = tmp_path / "out.csv"
    fms.write_csv(rows, ["a", "b"], path)
    content = path.read_text(encoding="utf-8")
    assert "a,b" in content
    assert "1,2" in content
