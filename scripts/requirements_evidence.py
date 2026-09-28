"""Read non-authoritative requirement constraints for the V2 repair path.

The resolver establishes whether a PyPI distribution provides an import.
This module deliberately does not do that job.  It only reports whether an
already verified distribution is declared in a fetched requirements file and
whether that declaration admits one of the verified candidate versions.
"""

import re
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Optional

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


DECLARED_CONSTRAINT_ABSENT = "declared_constraint_absent"
DECLARED_CONSTRAINT_COMPATIBLE = "declared_constraint_compatible"
DECLARED_CONSTRAINT_CONFLICT = "declared_constraint_conflict"
DECLARED_CONSTRAINT_UNPARSABLE = "declared_constraint_unparsable"


def _is_requirements_file(path: Any) -> bool:
    """Recognise conventional requirements-file paths without reading files."""
    if not isinstance(path, str) or not path.strip():
        return False
    name = PurePosixPath(path.replace("\\", "/")).name.lower()
    return name.endswith(".txt") and "requirement" in name


def _strip_requirement_comment(line: str) -> str:
    """Remove a comment only when ``#`` starts after whitespace.

    A hash can legally occur in a URL fragment, so blindly splitting on every
    hash would silently alter a declaration.
    """
    return re.split(r"\s+#", line, maxsplit=1)[0].strip()


def _potential_requirement_name(line: str) -> Optional[str]:
    """Return a conservative name hint solely for reporting malformed lines."""
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9_.-]*)", line)
    return canonicalize_name(match.group(1)) if match else None


def _active_for_python(requirement: Requirement, python_version: Optional[str]) -> bool:
    if requirement.marker is None:
        return True
    environment = default_environment()
    if python_version:
        parsed = Version(python_version)
        environment["python_version"] = f"{parsed.major}.{parsed.minor}"
        environment["python_full_version"] = str(parsed)
    return requirement.marker.evaluate(environment)


def _candidate_versions(retrieval_result: Dict[str, Any]) -> List[str]:
    versions = []
    for candidate in retrieval_result.get("candidate_versions") or []:
        value = candidate.get("version") if isinstance(candidate, dict) else None
        try:
            if value is not None:
                Version(str(value))
                versions.append(str(value))
        except InvalidVersion:
            continue
    return versions


def _base_evidence(retrieval_result: Dict[str, Any]) -> Dict[str, Any]:
    distribution_name = retrieval_result.get("distribution_name")
    return {
        "status": None,
        "distribution_name": distribution_name,
        "normalized_distribution_name": (
            canonicalize_name(distribution_name) if isinstance(distribution_name, str) else None
        ),
        "comparison_basis": "verified_candidate_versions",
        "candidate_versions": _candidate_versions(retrieval_result),
        "matching_declarations": [],
        "alias_declarations": [],
        "files_considered": [],
        "limitations": [],
        "non_authoritative": True,
    }


def assess_declared_constraint(
    dependency_file_metadata: Optional[Iterable[Dict[str, Any]]],
    retrieval_result: Dict[str, Any],
    import_distribution_mapping: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Compare fetched requirement declarations with verified candidates.

    The result is evidence for logging/prompt context only.  It cannot add a
    mapping, add candidate versions, or veto a Docker experiment.  A conflict
    means no *retrieved* candidate satisfies all active declarations; it does
    not claim that the repository declaration is objectively wrong.
    """
    evidence = _base_evidence(retrieval_result)
    target = evidence["normalized_distribution_name"]
    # A requirement line normally names a distribution, not a Python import.
    # If it instead uses a known import alias (``sklearn``), record the
    # mismatch as a conflict. This mapping is evidence for reporting only;
    # the code never rewrites the repository declaration or creates a new
    # resolver candidate from it.
    alias_names = {
        canonicalize_name(import_name)
        for import_name, distribution_name in (import_distribution_mapping or {}).items()
        if canonicalize_name(distribution_name) == target
    }
    if not target:
        evidence["status"] = DECLARED_CONSTRAINT_UNPARSABLE
        evidence["limitations"].append("no_resolved_distribution")
        return evidence

    files = [
        item for item in (dependency_file_metadata or [])
        if isinstance(item, dict) and _is_requirements_file(item.get("path"))
    ]
    if not files:
        evidence["status"] = DECLARED_CONSTRAINT_ABSENT
        evidence["limitations"].append("no_requirements_file_metadata")
        return evidence

    active_requirements: List[Requirement] = []
    malformed_match = False
    unavailable_file = False
    python_version = retrieval_result.get("python_version")

    for file_info in files:
        path = file_info.get("path")
        fetched = file_info.get("fetched") is True
        evidence["files_considered"].append({"path": path, "fetched": fetched, "ref": file_info.get("ref")})
        if not fetched or not isinstance(file_info.get("content"), str):
            unavailable_file = True
            continue

        for line_number, raw_line in enumerate(file_info["content"].splitlines(), start=1):
            line = _strip_requirement_comment(raw_line)
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            try:
                requirement = Requirement(line)
            except InvalidRequirement:
                if _potential_requirement_name(line) in {target, *alias_names}:
                    malformed_match = True
                    evidence["matching_declarations"].append({
                        "path": path,
                        "line_number": line_number,
                        "raw": raw_line,
                        "parse_status": "unparsable",
                    })
                continue

            declared_name = canonicalize_name(requirement.name)
            if declared_name not in {target, *alias_names}:
                continue

            try:
                active = _active_for_python(requirement, python_version)
            except (InvalidVersion, ValueError):
                malformed_match = True
                evidence["matching_declarations"].append({
                    "path": path,
                    "line_number": line_number,
                    "raw": raw_line,
                    "parse_status": "unparsable_marker",
                })
                continue

            declaration = {
                "path": path,
                "line_number": line_number,
                "raw": raw_line,
                "requirement": str(requirement),
                "specifier": str(requirement.specifier),
                "marker": str(requirement.marker) if requirement.marker is not None else None,
                "active_for_runtime": active,
                "parse_status": "parsed",
            }
            if declared_name in alias_names:
                declaration["parse_status"] = "known_import_alias_not_distribution"
                declaration["expected_distribution"] = retrieval_result.get("distribution_name")
                if active:
                    evidence["alias_declarations"].append(declaration)
                continue

            evidence["matching_declarations"].append(declaration)
            if active:
                # A direct URL names a distribution but has no PyPI version
                # constraint to compare against the retriever's evidence.
                if requirement.url:
                    malformed_match = True
                    declaration["parse_status"] = "uncomparable_direct_url"
                else:
                    active_requirements.append(requirement)

    if evidence["alias_declarations"]:
        evidence["status"] = DECLARED_CONSTRAINT_CONFLICT
        evidence["limitations"].append("declared_import_alias_not_distribution")
        return evidence
    if malformed_match:
        evidence["status"] = DECLARED_CONSTRAINT_UNPARSABLE
        evidence["limitations"].append("matching_declaration_could_not_be_compared")
        return evidence
    if unavailable_file:
        evidence["status"] = DECLARED_CONSTRAINT_UNPARSABLE
        evidence["limitations"].append("requirements_file_not_fetched")
        return evidence
    if not active_requirements:
        evidence["status"] = DECLARED_CONSTRAINT_ABSENT
        return evidence

    candidate_versions = evidence["candidate_versions"]
    compatible_versions = []
    for value in candidate_versions:
        parsed = Version(value)
        if all(parsed in requirement.specifier for requirement in active_requirements):
            compatible_versions.append(value)
    evidence["compatible_candidate_versions"] = compatible_versions
    evidence["status"] = (
        DECLARED_CONSTRAINT_COMPATIBLE if compatible_versions else DECLARED_CONSTRAINT_CONFLICT
    )
    return evidence
