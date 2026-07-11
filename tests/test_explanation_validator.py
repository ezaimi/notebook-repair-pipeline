import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from explanation_validator import parse_and_validate, parse_model_response


SCHEMA = str(ROOT / "schemas" / "explanation.schema.json")


def valid_response():
    return {
        "summary": "The notebook failed because sklearn is missing.",
        "root_cause": "Python could not import sklearn in the execution environment.",
        "evidence": ["The error type is ModuleNotFoundError."],
        "failing_module": "sklearn",
        "explanation_confidence": "high",
        "limitations": "Only metadata is available."
    }


def test_valid_response_passes_schema():
    raw = json.dumps(valid_response())
    valid, explanation, errors = parse_and_validate(raw, SCHEMA)

    assert valid is True
    assert explanation["failing_module"] == "sklearn"
    assert errors == []


def test_markdown_fenced_response_with_extra_text_is_parsed():
    raw = "Here is the answer:\n```json\n" + json.dumps(valid_response()) + "\n```\nDone."
    valid, explanation, errors = parse_and_validate(raw, SCHEMA)

    assert valid is True
    assert explanation["explanation_confidence"] == "high"
    assert errors == []


def test_missing_required_field_fails_schema():
    data = valid_response()
    del data["failing_module"]

    valid, explanation, errors = parse_and_validate(json.dumps(data), SCHEMA)

    assert valid is False
    assert any("failing_module" in error for error in errors)


def test_non_object_json_is_rejected():
    try:
        parse_model_response("[1, 2, 3]")
    except ValueError as e:
        assert "non_object_json" in str(e)
    else:
        raise AssertionError("Expected ValueError")


def test_extra_repair_field_is_rejected():
    data = valid_response()
    data["suggested_fix"] = "pip install sklearn"

    valid, explanation, errors = parse_and_validate(json.dumps(data), SCHEMA)

    assert valid is False
    assert any("Additional properties" in error for error in errors)


def test_empty_evidence_is_allowed():
    data = valid_response()
    data["evidence"] = []

    valid, explanation, errors = parse_and_validate(json.dumps(data), SCHEMA)

    assert valid is True
    assert explanation["evidence"] == []
    assert errors == []


def test_empty_limitations_is_rejected():
    data = valid_response()
    data["limitations"] = ""

    valid, explanation, errors = parse_and_validate(json.dumps(data), SCHEMA)

    assert valid is False
    assert any("limitations" in error for error in errors)


def test_invalid_explanation_confidence_is_rejected():
    data = valid_response()
    data["explanation_confidence"] = "certain"

    valid, explanation, errors = parse_and_validate(json.dumps(data), SCHEMA)

    assert valid is False
    assert any("explanation_confidence" in error for error in errors)


def test_json_object_embedded_in_plain_text_is_extracted():
    raw = "Here is the result: " + json.dumps(valid_response()) + " Done."

    valid, explanation, errors = parse_and_validate(raw, SCHEMA)

    assert valid is True
    assert explanation["failing_module"] == "sklearn"
    assert errors == []
