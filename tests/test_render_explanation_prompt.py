import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from render_explanation_prompt import build_template_values, render_prompt


def sample_record():
    return {
        "notebook_execution_id": 8,
        "error_type": "ModuleNotFoundError",
        "error_message": "No module named 'sklearn'",
        "original_subtype": "missing_package",
        "refined_subtype": "missing_package",
        "confidence": "high",
        "root_cause_hint": "import_distribution_name_mismatch",
        "failing_module": "sklearn",
        "context_status": "metadata_only",
        "error_cell_index": "5",
        "prompt_context": {
            "failing_cell_source": None,
            "import_cells": [],
            "surrounding_cells": [],
            "dependency_files": []
        },
        "legacy_traceback_hint": None
    }


def test_missing_context_renders_not_available():
    values = build_template_values(sample_record())

    assert values["failing_cell_source"] == "Not available"
    assert values["import_cells"] == "Not available"
    assert values["surrounding_cells"] == "Not available"
    assert values["dependency_files"] == "Not available"


def test_template_placeholders_are_replaced():
    template = "error_type={{error_type}}\nfailing_module={{failing_module}}"
    values = build_template_values(sample_record())

    rendered = render_prompt(template, values)

    assert "ModuleNotFoundError" in rendered
    assert "sklearn" in rendered
    assert "{{" not in rendered


def test_unknown_placeholder_raises_keyerror():
    values = build_template_values(sample_record())

    try:
        render_prompt("unknown={{unknown_field}}", values)
    except KeyError as e:
        assert "unknown_field" in str(e)
    else:
        raise AssertionError("Expected KeyError")


def test_single_pass_replacement_does_not_replace_injected_template_text():
    record = sample_record()
    record["prompt_context"]["failing_cell_source"] = "render({{root_cause_hint}})"
    values = build_template_values(record)

    rendered = render_prompt("cell={{failing_cell_source}}", values)

    assert "render({{root_cause_hint}})" in rendered

import json


def test_real_i2_jsonl_row_maps_confidence_to_classifier_confidence():
    path = ROOT / "data" / "context-classification" / "dependency_error_contexts.jsonl"

    with path.open(encoding="utf-8") as f:
        record = json.loads(next(f))

    values = build_template_values(record)

    assert values["classifier_confidence"] == record["confidence"]
    assert values["refined_subtype"] == record["refined_subtype"]
    assert values["failing_module"] == record["failing_module"]


def test_legacy_traceback_hint_dict_unwraps_raw_traceback():
    record = sample_record()
    record["legacy_traceback_hint"] = {
        "accepted": True,
        "raw_traceback": "Traceback text here"
    }

    values = build_template_values(record)

    assert values["legacy_traceback_hint"] == "Traceback text here"


def test_iter_rendered_prompts_preserves_record_on_render_failure(tmp_path):
    from render_explanation_prompt import iter_rendered_prompts

    input_path = tmp_path / "input.jsonl"
    template_path = tmp_path / "template.txt"

    record = sample_record()
    input_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    template_path.write_text("unknown={{unknown_field}}", encoding="utf-8")

    items = list(iter_rendered_prompts(str(input_path), str(template_path)))

    assert len(items) == 1
    assert items[0]["prompt"] is None
    assert items[0]["record"]["notebook_execution_id"] == 8
    assert "Unknown template placeholder" in items[0]["error"]
