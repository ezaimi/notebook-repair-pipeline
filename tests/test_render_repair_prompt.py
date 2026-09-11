import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from render_repair_prompt import build_repair_template_values, render_repair_prompt


TEMPLATE_PATH = ROOT / "prompts" / "dependency_repair_v1.txt"


def sample_record():
    return {
        "notebook_execution_id": 174,
        "error_type": "ImportError",
        "error_message": "cannot import name 'cumtrapz' from 'scipy.integrate'",
        "refined_subtype": "wrong_version",
        "root_cause_hint": "version_or_api_incompatibility",
        "failing_module": "scipy",
        "context_status": "metadata_only",
        "prompt_context": {
            "failing_cell_source": None,
            "import_cells": [],
            "surrounding_cells": [],
        },
    }


def wrong_version_retrieval_result():
    return {
        "distribution_name": "scipy",
        "python_version": "3.10",
        "candidate_versions": [
            {"version": "1.13.1", "python_compatibility": "compatible"},
            {"version": "1.13.0", "python_compatibility": "compatible"},
        ],
        "compatibility_evidence": {
            "status": "resolved",
            "compatible_specifier": "<1.14.0",
            "evidence": {
                "summary": "SciPy 1.14.0 removed cumtrapz.",
                "source_url": "https://docs.scipy.org/doc/scipy/release/1.14.0-notes.html",
            },
        },
        "warnings": [],
    }


def missing_package_retrieval_result():
    return {
        "distribution_name": "scikit-learn",
        "python_version": "3.10",
        "candidate_versions": [
            {"version": "1.7.2", "python_compatibility": "compatible"},
        ],
        "compatibility_evidence": None,
        "warnings": [],
    }


def test_template_contains_grounded_candidate_versions():
    values = build_repair_template_values(sample_record(), wrong_version_retrieval_result(), "wrong_version")

    assert "1.13.1" in values["candidate_versions"]
    assert "1.13.0" in values["candidate_versions"]


def test_template_contains_compatibility_evidence_for_wrong_version():
    values = build_repair_template_values(sample_record(), wrong_version_retrieval_result(), "wrong_version")

    assert values["compatibility_constraint"] == "<1.14.0"
    assert "cumtrapz" in values["compatibility_evidence_summary"]
    assert "docs.scipy.org" in values["compatibility_evidence_summary"]


def test_missing_values_render_as_not_available():
    values = build_repair_template_values(sample_record(), missing_package_retrieval_result(), "missing_package")

    assert values["compatibility_constraint"] == "Not available"
    assert values["compatibility_evidence_summary"] == "Not available"


def test_no_candidates_renders_as_not_available():
    empty_result = {
        "distribution_name": None,
        "python_version": "3.10",
        "candidate_versions": [],
        "compatibility_evidence": None,
        "warnings": [],
    }
    values = build_repair_template_values(sample_record(), empty_result, "missing_package")

    assert values["candidate_versions"] == "Not available"
    assert values["distribution_name"] == "Not available"


def test_rendered_prompt_never_asks_for_a_command_field():
    """The prompt may (and does) explicitly forbid a "command" field, but no
    example JSON output block may show the model actually producing one."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    prompt = render_repair_prompt(sample_record(), wrong_version_retrieval_result(), "wrong_version", template)

    assert "shell command" in prompt.lower() or "pip command" in prompt.lower()

    # every example "Output:" JSON block must be exactly the 4-field shape
    for block in prompt.split("Output:\n")[1:]:
        json_text = block.split("\n\n")[0]
        example = json.loads(json_text)
        assert set(example.keys()) == {"action", "install_name", "version", "rationale"}


def test_rendered_prompt_contains_only_supplied_candidates_not_arbitrary_ones():
    """The rendered prompt must not contain any version string beyond what
    was actually supplied in candidate_versions - guards against a future
    template change accidentally leaking unfiltered PyPI data."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    prompt = render_repair_prompt(sample_record(), wrong_version_retrieval_result(), "wrong_version", template)

    # 1.14.0 was excluded by the compatibility intersection - it must never
    # appear in the rendered prompt's own candidate-version listing.
    candidate_section = prompt.split("candidate_versions:")[1].split("compatibility constraint:")[0]
    assert "1.14.0" not in candidate_section


def test_render_repair_prompt_fills_every_placeholder():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    prompt = render_repair_prompt(sample_record(), wrong_version_retrieval_result(), "wrong_version", template)

    assert "{{" not in prompt


# --- warning-noise regression (real pandas pilot failure) --------------------
#
# A real distribution (e.g. "pandas") can carry hundreds of "unparseable
# PyPI filename" warnings from legacy Windows .exe/.egg release artifacts.
# Joining all of them unbounded into the prompt was observed, in a real i7
# pilot run, to produce a prompt so dominated by that noise that gemma2:9b
# echoed it back as a malformed proposal instead of proposing a fix. These
# tests guard the fix: the prompt-facing summary must be bounded, while the
# underlying retrieval_result (provenance) must stay completely untouched.


def many_warnings_retrieval_result(n=250):
    return {
        "distribution_name": "pandas",
        "python_version": "3.10",
        "candidate_versions": [
            {"version": "2.2.0", "python_compatibility": "compatible"},
        ],
        "compatibility_evidence": None,
        "warnings": [
            f"Skipping unparseable PyPI filename: 'pandas-0.{i}.0.win32-py2.7.exe'" for i in range(n)
        ],
    }


def test_format_warnings_bounds_large_warning_lists_for_the_prompt():
    values = build_repair_template_values(sample_record(), many_warnings_retrieval_result(250), "missing_package")

    rendered_warnings = values["retrieval_warnings"]
    assert "250 warning(s)" in rendered_warnings
    assert rendered_warnings.count("Skipping unparseable PyPI filename") <= 3
    assert "more omitted" in rendered_warnings
    # nowhere near the ~250-line original (~9000+ chars unbounded)
    assert len(rendered_warnings) < 1000


def test_format_warnings_never_mutates_or_discards_the_original_retrieval_result():
    """Provenance requirement: the full warnings list must survive untouched
    in retrieval_result (and therefore in the persisted i4 record and
    repair_attempts.pypi_evidence) - only the rendered prompt text is
    bounded."""
    result = many_warnings_retrieval_result(250)
    original_warnings = list(result["warnings"])

    build_repair_template_values(sample_record(), result, "missing_package")

    assert result["warnings"] == original_warnings
    assert len(result["warnings"]) == 250


def test_format_warnings_shows_every_warning_when_the_list_is_small():
    result = missing_package_retrieval_result()
    result["warnings"] = ["one warning", "two warning"]

    values = build_repair_template_values(sample_record(), result, "missing_package")

    assert "one warning" in values["retrieval_warnings"]
    assert "two warning" in values["retrieval_warnings"]
    assert "omitted" not in values["retrieval_warnings"]


def test_format_warnings_is_none_when_there_are_no_warnings():
    values = build_repair_template_values(sample_record(), missing_package_retrieval_result(), "missing_package")
    assert values["retrieval_warnings"] == "none"
