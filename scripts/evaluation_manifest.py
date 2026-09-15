#!/usr/bin/env python3

"""EvaluationManifest (i8): a reproducible record of exactly what an I8
evaluation run consists of, written before scripts/run_pipeline.py is ever
invoked.

Purpose: the frozen I8 methodology requires that metric definitions,
denominators, prompts, and package mappings never change between the dev
validation run and the final 187-record evaluation run. This module makes
that verifiable rather than assumed - it hashes the exact prompt/config
files a run depends on and records enough environment/CLI detail
(model, max_rounds, split, run_id, git commit, python version, expected
record count) that two manifests can be diffed to catch any accidental
drift before results are trusted.

This module never reads or embeds `.env` or any other secret material - it
only hashes named, non-secret prompt/config file paths and records
non-secret metadata (paths, versions, counts, timestamps).
"""

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_I2_PATH = "data/context-classification/dependency_error_contexts.jsonl"

# Paths hashed into every manifest. Directories are hashed by walking their
# files in sorted order (see hash_path()) so the hash is stable regardless
# of filesystem iteration order and changes if any file inside is added,
# removed, or edited.
DEFAULT_HASHED_PATHS = {
    "prompts_dir": "prompts",
    "package_mapping": "config/package_mapping.yaml",
    "rag_repair_config": "config/rag_repair.yaml",
    "llm_explainer_config": "config/llm_explainer.yaml",
    "fix_applicator_config": "config/fix_applicator.yaml",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- hashing ------------------------------------------------------------

def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def hash_path(path: Path) -> Optional[str]:
    """SHA-256 of a single file, or of a directory's files (sorted by
    relative path, each entry mixed in as "relpath\\0sha256\\n" so a rename
    changes the hash even if file contents are unchanged). Returns None if
    `path` does not exist - a missing prompt/config file is reported as
    None rather than raising, so manifest generation itself never fails
    because of an unrelated missing optional file; callers decide whether
    a None hash is acceptable."""
    if not path.exists():
        return None

    if path.is_file():
        return hash_file(path)

    digest = hashlib.sha256()
    for file_path in sorted(p for p in path.rglob("*") if p.is_file()):
        relpath = file_path.relative_to(path).as_posix()
        digest.update(relpath.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hash_file(file_path).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_config_hashes(
    root: Path, hashed_paths: Optional[Dict[str, str]] = None
) -> Dict[str, Optional[str]]:
    hashed_paths = hashed_paths or DEFAULT_HASHED_PATHS
    return {name: hash_path(root / relpath) for name, relpath in hashed_paths.items()}


# --- environment metadata -------------------------------------------------

def get_git_commit_sha(root: Path) -> Optional[str]:
    """Current HEAD commit SHA, or None if git is unavailable or this is
    not a git checkout - never fatal, since a manifest should still record
    everything else even outside a git working copy."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def get_python_version() -> str:
    return sys.version.split()[0]


# --- expected record count, derived from the actual dataset -------------

def count_records_in_split(i2_path: Path, split: str) -> int:
    """Count of i2 records whose own `split` field matches `split`. Derived
    from the real dataset file at manifest-build time rather than a
    hardcoded literal (13/187/14), so a manifest is self-verifying even if
    the dataset is ever regenerated - see docs/i8-evaluation-methodology.md
    "expected record count is data-derived, not hardcoded"."""
    if split == "all":
        count = 0
        with i2_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count

    count = 0
    with i2_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("split") == split:
                count += 1
    return count


# --- repository-commit metadata accessibility (informational only) -------

def check_repository_metadata_db(db_path: Optional[str]) -> Dict[str, Any]:
    """Report whether the upstream Docker pipeline's sqlite DB (the source
    of per-repository `commit`/`requirements`/`setups` metadata FixApplicator
    uses for exact-commit checkout) is actually reachable from this
    environment, and - when it is - its SHA-256, so the manifest records
    exactly which snapshot of that DB the run actually used, not merely
    that some file existed at the configured path. This is purely
    informational at manifest-build time - scripts/fix_applicator.py
    already degrades gracefully when this DB is absent (see
    config/fix_applicator.yaml) - but I8's exact-commit preflight check
    (docs/i8-evaluation-methodology.md) needs this recorded so a broken
    path, or an unexpectedly different DB snapshot, is visible in the
    manifest itself rather than only discovered mid-run."""
    if not db_path:
        return {"configured_path": None, "accessible": False, "reason": "no db_path configured", "sha256": None}

    resolved = Path(db_path).expanduser()
    if not resolved.is_file():
        return {
            "configured_path": db_path,
            "resolved_path": str(resolved),
            "accessible": False,
            "reason": "file not found at resolved path",
            "sha256": None,
        }
    return {
        "configured_path": db_path,
        "resolved_path": str(resolved),
        "accessible": True,
        "reason": None,
        "sha256": hash_file(resolved),
    }


# --- manifest construction ------------------------------------------------

def build_manifest(
    *,
    run_id: str,
    split: str,
    max_rounds: int,
    model: str,
    prompt_strategy: str,
    explanation_prompt_version: str,
    repair_prompt_version: str,
    database_path: str,
    output_dir: str,
    explainer_config_path: str,
    repair_config_path: str,
    fix_config_path: str,
    repository_metadata_db_path: Optional[str],
    i2_path: str = DEFAULT_I2_PATH,
    root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Assemble one evaluation manifest. Pure with respect to global state
    except for reading files under `root` (default: repo root, two levels
    up from this file) to compute hashes/counts/git SHA - never reads
    `.env` or any file outside `root`."""
    root = root or Path(__file__).resolve().parent.parent
    i2_full_path = root / i2_path

    # Hash the config files this run actually loads, not always the
    # hardcoded defaults: rag_repair_config/llm_explainer_config/
    # fix_applicator_config are overridden to explainer_config_path/
    # repair_config_path/fix_config_path (e.g. a sibling config/*.kiste.yaml
    # for the LLM model-sensitivity experiment) so config_hashes never
    # misreports which config a run used. prompts_dir and package_mapping
    # stay at DEFAULT_HASHED_PATHS's fixed locations - neither prompts nor
    # the package mapping are ever provider-specific. When
    # explainer_config_path/repair_config_path/fix_config_path equal
    # today's defaults (as every existing Gemma call site still does),
    # this dict is byte-identical to DEFAULT_HASHED_PATHS, so every
    # already-produced manifest (including the frozen I8 final-evaluation
    # ones) remains exactly reproducible.
    hashed_paths = dict(DEFAULT_HASHED_PATHS)
    hashed_paths["rag_repair_config"] = repair_config_path
    hashed_paths["llm_explainer_config"] = explainer_config_path
    hashed_paths["fix_applicator_config"] = fix_config_path

    return {
        "run_id": run_id,
        "split": split,
        "expected_record_count": count_records_in_split(i2_full_path, split),
        "max_rounds": max_rounds,
        "model": model,
        "prompt_strategy": prompt_strategy,
        "explanation_prompt_version": explanation_prompt_version,
        "repair_prompt_version": repair_prompt_version,
        "config_paths": {
            "explainer_config": explainer_config_path,
            "repair_config": repair_config_path,
            "fix_config": fix_config_path,
        },
        "python_version": get_python_version(),
        "git_commit_sha": get_git_commit_sha(root),
        "created_at": utc_now(),
        "database_path": database_path,
        "output_dir": output_dir,
        "repository_metadata_db": check_repository_metadata_db(repository_metadata_db_path),
        "config_hashes": build_config_hashes(root, hashed_paths),
        "i2_path": i2_path,
    }


def write_manifest(manifest: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_manifest(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# --- consistency checking (resume / dev-vs-final drift detection) --------

# Fields whose change between two manifests for the *same* run_id indicates
# an accidental configuration drift (e.g. someone edited a prompt or the
# package mapping between a resumed run's earlier and later invocations, or
# between the dev validation manifest and the final evaluation manifest).
# `created_at` and `git_commit_sha` are deliberately excluded: a commit made
# purely to add unrelated files (not touching any hashed path) should not
# by itself block a resume.
CONSISTENCY_FIELDS = [
    "split",
    "max_rounds",
    "model",
    "prompt_strategy",
    "explanation_prompt_version",
    "repair_prompt_version",
    "expected_record_count",
    "config_hashes",
]


def diff_manifests(previous: Dict[str, Any], current: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable descriptions of every
    CONSISTENCY_FIELDS mismatch between `previous` and `current`. An empty
    list means the two manifests are consistent enough to safely resume
    under the same run_id."""
    mismatches: List[str] = []
    for field in CONSISTENCY_FIELDS:
        prev_value = previous.get(field)
        curr_value = current.get(field)
        if prev_value != curr_value:
            mismatches.append(f"{field}: previous={prev_value!r} current={curr_value!r}")
    return mismatches


def verify_manifest_consistency(previous: Dict[str, Any], current: Dict[str, Any]) -> None:
    """Raise ManifestConsistencyError if `current` drifted from `previous`
    on any CONSISTENCY_FIELDS entry. Used before resuming a run under an
    existing run_id."""
    mismatches = diff_manifests(previous, current)
    if mismatches:
        raise ManifestConsistencyError(
            "evaluation configuration changed since the previous manifest for this run_id:\n  "
            + "\n  ".join(mismatches)
        )


class ManifestConsistencyError(Exception):
    """Raised when a resumed run's manifest disagrees with the
    already-persisted manifest for the same run_id on a field that must
    stay fixed for results to remain comparable."""
