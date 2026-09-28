import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from requirements_evidence import (
    DECLARED_CONSTRAINT_ABSENT,
    DECLARED_CONSTRAINT_COMPATIBLE,
    DECLARED_CONSTRAINT_CONFLICT,
    DECLARED_CONSTRAINT_UNPARSABLE,
    assess_declared_constraint,
)


def retrieval(distribution="cana", versions=("1.2.0", "1.1.0")):
    return {
        "distribution_name": distribution,
        "python_version": "3.10",
        "candidate_versions": [{"version": value, "python_compatibility": "compatible"} for value in versions],
    }


def requirements_file(content, fetched=True, path="requirements.txt"):
    return {"path": path, "fetched": fetched, "ref": "abc123", "content": content if fetched else None}


def test_matching_requirement_with_a_verified_candidate_is_compatible():
    evidence = assess_declared_constraint(
        [requirements_file("cana>=1.1,<2\n")], retrieval()
    )

    assert evidence["status"] == DECLARED_CONSTRAINT_COMPATIBLE
    assert evidence["compatible_candidate_versions"] == ["1.2.0", "1.1.0"]
    assert evidence["matching_declarations"][0]["specifier"] == "<2,>=1.1"
    assert evidence["non_authoritative"] is True


def test_matching_requirement_that_excludes_every_verified_candidate_is_conflict():
    evidence = assess_declared_constraint(
        [requirements_file("cana<1.0\n")], retrieval()
    )

    assert evidence["status"] == DECLARED_CONSTRAINT_CONFLICT
    assert evidence["compatible_candidate_versions"] == []


def test_unrelated_requirement_is_absent_for_the_resolved_distribution():
    evidence = assess_declared_constraint(
        [requirements_file("pandas==2.2.0\n")], retrieval()
    )

    assert evidence["status"] == DECLARED_CONSTRAINT_ABSENT
    assert evidence["matching_declarations"] == []


def test_missing_requirements_metadata_is_absent_but_explicitly_limited():
    evidence = assess_declared_constraint([], retrieval())

    assert evidence["status"] == DECLARED_CONSTRAINT_ABSENT
    assert "no_requirements_file_metadata" in evidence["limitations"]


def test_unfetched_requirements_file_is_not_misreported_as_a_clean_absence():
    evidence = assess_declared_constraint(
        [requirements_file(None, fetched=False)], retrieval()
    )

    assert evidence["status"] == DECLARED_CONSTRAINT_UNPARSABLE
    assert "requirements_file_not_fetched" in evidence["limitations"]


def test_malformed_matching_requirement_is_unparsable():
    evidence = assess_declared_constraint(
        [requirements_file("cana==\n")], retrieval()
    )

    assert evidence["status"] == DECLARED_CONSTRAINT_UNPARSABLE
    assert evidence["matching_declarations"][0]["parse_status"] == "unparsable"


def test_marker_inactive_under_python_310_does_not_constrain_candidates():
    evidence = assess_declared_constraint(
        [requirements_file("cana<1.0; python_version < '3.10'\n")], retrieval()
    )

    assert evidence["status"] == DECLARED_CONSTRAINT_ABSENT
    assert evidence["matching_declarations"][0]["active_for_runtime"] is False


def test_name_comparison_uses_pep503_normalisation():
    evidence = assess_declared_constraint(
        [requirements_file("scikit_learn>=1.0\n")],
        retrieval(distribution="scikit-learn", versions=("1.4.0",)),
    )

    assert evidence["status"] == DECLARED_CONSTRAINT_COMPATIBLE


def test_known_import_alias_in_requirements_is_a_logged_declaration_conflict():
    evidence = assess_declared_constraint(
        [requirements_file("sklearn==0.0\n")],
        retrieval(distribution="scikit-learn", versions=("1.4.0",)),
        import_distribution_mapping={"sklearn": "scikit-learn"},
    )

    assert evidence["status"] == DECLARED_CONSTRAINT_CONFLICT
    assert evidence["alias_declarations"][0]["raw"] == "sklearn==0.0"
    assert evidence["alias_declarations"][0]["expected_distribution"] == "scikit-learn"
    assert "declared_import_alias_not_distribution" in evidence["limitations"]


def test_inactive_known_import_alias_does_not_create_a_runtime_conflict():
    evidence = assess_declared_constraint(
        [requirements_file("sklearn==0.0; python_version < '3.10'\n")],
        retrieval(distribution="scikit-learn", versions=("1.4.0",)),
        import_distribution_mapping={"sklearn": "scikit-learn"},
    )

    assert evidence["status"] == DECLARED_CONSTRAINT_ABSENT
    assert evidence["alias_declarations"] == []
