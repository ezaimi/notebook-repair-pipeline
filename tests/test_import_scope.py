import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from import_scope import classify_import_scope


def test_statistics_is_classified_as_standard_library():
    result = classify_import_scope("statistics")

    assert result == {"status": "standard_library", "reason": "python_standard_library"}


def test_relative_import_is_confirmed_as_local_only_with_source_evidence():
    record = {"prompt_context": {"failing_cell_source": "from .utils import load_data\n"}}

    result = classify_import_scope("utils", record)

    assert result["status"] == "local_import_path"


def test_ambiguous_short_import_is_not_falsely_called_local():
    result = classify_import_scope("utils", {"prompt_context": {}})

    assert result["status"] == "classification_uncertain"


def test_ordinary_import_is_sent_to_the_third_party_resolution_path():
    result = classify_import_scope("pandas")

    assert result["status"] == "third_party_dependency"
