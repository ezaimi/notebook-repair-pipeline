import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluation_manifest as em


# --- hashing -----------------------------------------------------------------

def test_hash_file_changes_when_content_changes(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text("one", encoding="utf-8")
    first = em.hash_file(path)
    path.write_text("two", encoding="utf-8")
    second = em.hash_file(path)
    assert first != second


def test_hash_file_stable_for_same_content(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text("same", encoding="utf-8")
    assert em.hash_file(path) == em.hash_file(path)


def test_hash_path_missing_file_returns_none(tmp_path):
    assert em.hash_path(tmp_path / "does_not_exist.yaml") is None


def test_hash_path_directory_changes_when_a_file_is_added(tmp_path):
    directory = tmp_path / "prompts"
    directory.mkdir()
    (directory / "a.txt").write_text("a", encoding="utf-8")
    before = em.hash_path(directory)
    (directory / "b.txt").write_text("b", encoding="utf-8")
    after = em.hash_path(directory)
    assert before != after


def test_hash_path_directory_changes_on_rename_even_with_same_content(tmp_path):
    directory = tmp_path / "prompts"
    directory.mkdir()
    (directory / "a.txt").write_text("same content", encoding="utf-8")
    before = em.hash_path(directory)
    (directory / "a.txt").rename(directory / "b.txt")
    after = em.hash_path(directory)
    assert before != after


def test_build_config_hashes_returns_one_entry_per_named_path(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "package_mapping.yaml").write_text("sklearn: scikit-learn", encoding="utf-8")
    hashes = em.build_config_hashes(tmp_path, {"package_mapping": "config/package_mapping.yaml"})
    assert set(hashes.keys()) == {"package_mapping"}
    assert hashes["package_mapping"] is not None


# --- expected record count, data-derived --------------------------------------

def _write_i2(tmp_path, splits):
    path = tmp_path / "i2.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for i, split in enumerate(splits):
            f.write(json.dumps({"notebook_execution_id": i, "split": split}) + "\n")
    return path


def test_count_records_in_split_dev(tmp_path):
    path = _write_i2(tmp_path, ["dev", "evaluation", "dev", "excluded", "dev"])
    assert em.count_records_in_split(path, "dev") == 3


def test_count_records_in_split_evaluation(tmp_path):
    path = _write_i2(tmp_path, ["dev", "evaluation", "dev", "excluded", "dev"])
    assert em.count_records_in_split(path, "evaluation") == 1


def test_count_records_in_split_all(tmp_path):
    path = _write_i2(tmp_path, ["dev", "evaluation", "dev", "excluded", "dev"])
    assert em.count_records_in_split(path, "all") == 5


def test_count_records_in_split_never_hardcoded_13_or_187(tmp_path):
    """A dataset with a different dev-split size must produce a different
    expected_record_count - the manifest must never silently assume 13/187."""
    path = _write_i2(tmp_path, ["dev"] * 7 + ["evaluation"] * 2)
    assert em.count_records_in_split(path, "dev") == 7
    assert em.count_records_in_split(path, "evaluation") == 2


# --- repository metadata DB accessibility check --------------------------------

def test_check_repository_metadata_db_missing_path_reports_inaccessible():
    result = em.check_repository_metadata_db(None)
    assert result["accessible"] is False


def test_check_repository_metadata_db_nonexistent_file_reports_inaccessible(tmp_path):
    result = em.check_repository_metadata_db(str(tmp_path / "does_not_exist.sqlite"))
    assert result["accessible"] is False


def test_check_repository_metadata_db_existing_file_reports_accessible(tmp_path):
    db_file = tmp_path / "db.sqlite"
    db_file.write_text("not a real db but a real file", encoding="utf-8")
    result = em.check_repository_metadata_db(str(db_file))
    assert result["accessible"] is True


def test_check_repository_metadata_db_records_sha256_when_accessible(tmp_path):
    db_file = tmp_path / "db.sqlite"
    db_file.write_bytes(b"some real db bytes")
    result = em.check_repository_metadata_db(str(db_file))
    assert result["sha256"] == em.hash_file(db_file)


def test_check_repository_metadata_db_sha256_changes_with_content(tmp_path):
    db_file = tmp_path / "db.sqlite"
    db_file.write_bytes(b"version one")
    first = em.check_repository_metadata_db(str(db_file))["sha256"]
    db_file.write_bytes(b"version two")
    second = em.check_repository_metadata_db(str(db_file))["sha256"]
    assert first != second


def test_check_repository_metadata_db_sha256_is_none_when_missing():
    assert em.check_repository_metadata_db(None)["sha256"] is None


def test_check_repository_metadata_db_sha256_is_none_when_nonexistent(tmp_path):
    result = em.check_repository_metadata_db(str(tmp_path / "does_not_exist.sqlite"))
    assert result["sha256"] is None


# --- manifest construction / round-trip ----------------------------------------

def _make_repo_fixture(tmp_path):
    (tmp_path / "config").mkdir()
    for name in ["package_mapping.yaml", "rag_repair.yaml", "llm_explainer.yaml", "fix_applicator.yaml"]:
        (tmp_path / "config" / name).write_text(f"# {name}", encoding="utf-8")
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "dependency_explanation_v1.txt").write_text("prompt", encoding="utf-8")
    return tmp_path


def test_build_manifest_has_all_required_fields(tmp_path):
    root = _make_repo_fixture(tmp_path)
    i2_path = _write_i2(tmp_path, ["dev"] * 13)
    manifest = em.build_manifest(
        run_id="i8-test-001",
        split="dev",
        max_rounds=2,
        model="gemma2:9b",
        prompt_strategy="few_shot",
        explanation_prompt_version="i3_prompt_v1",
        repair_prompt_version="i4_prompt_v1",
        database_path="data/x.sqlite",
        output_dir="data/pipeline-runs",
        explainer_config_path="config/llm_explainer.yaml",
        repair_config_path="config/rag_repair.yaml",
        fix_config_path="config/fix_applicator.yaml",
        repository_metadata_db_path=None,
        i2_path=str(i2_path.relative_to(tmp_path)),
        root=root,
    )
    required_fields = {
        "run_id", "split", "expected_record_count", "max_rounds", "model", "prompt_strategy",
        "explanation_prompt_version", "repair_prompt_version", "config_paths", "python_version",
        "git_commit_sha", "created_at", "database_path", "output_dir", "repository_metadata_db",
        "config_hashes",
    }
    assert required_fields.issubset(manifest.keys())
    assert manifest["expected_record_count"] == 13
    assert manifest["split"] == "dev"


def test_manifest_never_stores_env_contents(tmp_path):
    root = _make_repo_fixture(tmp_path)
    (root / ".env").write_text("GITLAB_TOKEN=super-secret-value", encoding="utf-8")
    i2_path = _write_i2(tmp_path, ["dev"] * 13)
    manifest = em.build_manifest(
        run_id="i8-test-001",
        split="dev",
        max_rounds=2,
        model="gemma2:9b",
        prompt_strategy="few_shot",
        explanation_prompt_version="i3_prompt_v1",
        repair_prompt_version="i4_prompt_v1",
        database_path="data/x.sqlite",
        output_dir="data/pipeline-runs",
        explainer_config_path="config/llm_explainer.yaml",
        repair_config_path="config/rag_repair.yaml",
        fix_config_path="config/fix_applicator.yaml",
        repository_metadata_db_path=None,
        i2_path=str(i2_path.relative_to(tmp_path)),
        root=root,
    )
    serialized = json.dumps(manifest)
    assert "super-secret-value" not in serialized
    assert ".env" not in json.dumps(em.DEFAULT_HASHED_PATHS)


def test_write_and_load_manifest_roundtrip(tmp_path):
    manifest = {"run_id": "i8-test-001", "split": "dev"}
    path = tmp_path / "manifest.json"
    em.write_manifest(manifest, path)
    loaded = em.load_manifest(path)
    assert loaded == manifest


# --- config_hashes reflects the config actually used (LLM model-sensitivity --
# supplementary experiment: a sibling config/*.kiste.yaml must never be
# silently reported under the default Gemma config's hash) -------------------

def test_build_manifest_hashes_the_actual_explainer_and_repair_config_paths_used(tmp_path):
    root = _make_repo_fixture(tmp_path)
    (root / "config" / "llm_explainer.kiste.yaml").write_text(
        "# a genuinely different kiste sibling config", encoding="utf-8"
    )
    (root / "config" / "rag_repair.kiste.yaml").write_text(
        "# a genuinely different kiste sibling repair config", encoding="utf-8"
    )
    i2_path = _write_i2(tmp_path, ["dev"] * 13)

    manifest = em.build_manifest(
        run_id="i8-test-kiste",
        split="dev",
        max_rounds=2,
        model="Qwen3.6-35B-A3B-MLX-8bit",
        prompt_strategy="few_shot",
        explanation_prompt_version="i3_prompt_v1",
        repair_prompt_version="i4_prompt_v1",
        database_path="data/x.sqlite",
        output_dir="data/pipeline-runs",
        explainer_config_path="config/llm_explainer.kiste.yaml",
        repair_config_path="config/rag_repair.kiste.yaml",
        fix_config_path="config/fix_applicator.yaml",
        repository_metadata_db_path=None,
        i2_path=str(i2_path.relative_to(tmp_path)),
        root=root,
    )

    expected_explainer_hash = em.hash_file(root / "config" / "llm_explainer.kiste.yaml")
    expected_repair_hash = em.hash_file(root / "config" / "rag_repair.kiste.yaml")
    default_explainer_hash = em.hash_file(root / "config" / "llm_explainer.yaml")
    default_repair_hash = em.hash_file(root / "config" / "rag_repair.yaml")

    assert manifest["config_hashes"]["llm_explainer_config"] == expected_explainer_hash
    assert manifest["config_hashes"]["rag_repair_config"] == expected_repair_hash
    # never silently falls back to (or coincides with) the default Gemma files
    assert manifest["config_hashes"]["llm_explainer_config"] != default_explainer_hash
    assert manifest["config_hashes"]["rag_repair_config"] != default_repair_hash


def test_build_manifest_default_config_paths_match_pre_existing_hash_behavior(tmp_path):
    """Backward compatibility: every existing call site (Gemma runs) passes
    exactly today's default paths, so config_hashes must come out
    byte-identical to build_config_hashes(root) with no override - the
    already-produced frozen I8 manifests remain exactly reproducible."""
    root = _make_repo_fixture(tmp_path)
    i2_path = _write_i2(tmp_path, ["dev"] * 13)

    manifest = em.build_manifest(
        run_id="i8-test-default",
        split="dev",
        max_rounds=2,
        model="gemma2:9b",
        prompt_strategy="few_shot",
        explanation_prompt_version="i3_prompt_v1",
        repair_prompt_version="i4_prompt_v1",
        database_path="data/x.sqlite",
        output_dir="data/pipeline-runs",
        explainer_config_path="config/llm_explainer.yaml",
        repair_config_path="config/rag_repair.yaml",
        fix_config_path="config/fix_applicator.yaml",
        repository_metadata_db_path=None,
        i2_path=str(i2_path.relative_to(tmp_path)),
        root=root,
    )

    assert manifest["config_hashes"] == em.build_config_hashes(root)


def test_manifest_never_stores_kiste_token(tmp_path):
    root = _make_repo_fixture(tmp_path)
    (root / ".env").write_text("KISTE_API_TOKEN=super-secret-kiste-value", encoding="utf-8")
    i2_path = _write_i2(tmp_path, ["dev"] * 13)
    manifest = em.build_manifest(
        run_id="i8-test-002",
        split="dev",
        max_rounds=2,
        model="Qwen3.6-35B-A3B-MLX-8bit",
        prompt_strategy="few_shot",
        explanation_prompt_version="i3_prompt_v1",
        repair_prompt_version="i4_prompt_v1",
        database_path="data/x.sqlite",
        output_dir="data/pipeline-runs",
        explainer_config_path="config/llm_explainer.yaml",
        repair_config_path="config/rag_repair.yaml",
        fix_config_path="config/fix_applicator.yaml",
        repository_metadata_db_path=None,
        i2_path=str(i2_path.relative_to(tmp_path)),
        root=root,
    )
    serialized = json.dumps(manifest)
    assert "super-secret-kiste-value" not in serialized
    assert ".env" not in json.dumps(em.DEFAULT_HASHED_PATHS)


# --- consistency checking (resume) ---------------------------------------------

def _base_manifest(**overrides):
    manifest = {
        "split": "dev",
        "max_rounds": 2,
        "model": "gemma2:9b",
        "prompt_strategy": "few_shot",
        "explanation_prompt_version": "i3_prompt_v1",
        "repair_prompt_version": "i4_prompt_v1",
        "expected_record_count": 13,
        "config_hashes": {"package_mapping": "abc123"},
        "created_at": "2026-01-01T00:00:00+00:00",
        "git_commit_sha": "aaaa",
    }
    manifest.update(overrides)
    return manifest


def test_diff_manifests_identical_configuration_has_no_mismatches():
    previous = _base_manifest()
    current = _base_manifest(created_at="2026-01-02T00:00:00+00:00", git_commit_sha="bbbb")
    assert em.diff_manifests(previous, current) == []


def test_diff_manifests_detects_changed_config_hash():
    previous = _base_manifest()
    current = _base_manifest(config_hashes={"package_mapping": "different"})
    mismatches = em.diff_manifests(previous, current)
    assert any("config_hashes" in m for m in mismatches)


def test_diff_manifests_detects_changed_max_rounds():
    previous = _base_manifest()
    current = _base_manifest(max_rounds=1)
    mismatches = em.diff_manifests(previous, current)
    assert any("max_rounds" in m for m in mismatches)


def test_verify_manifest_consistency_passes_silently_for_identical_config():
    em.verify_manifest_consistency(_base_manifest(), _base_manifest(created_at="later"))


def test_verify_manifest_consistency_raises_for_changed_config():
    with pytest.raises(em.ManifestConsistencyError):
        em.verify_manifest_consistency(_base_manifest(), _base_manifest(model="a-different-model"))
