import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_evaluation as re_
import evaluation_manifest as em


# --- pure argv construction -----------------------------------------------------

def test_build_pipeline_argv_shape():
    argv = re_.build_pipeline_argv(
        python_executable="python",
        split="dev",
        limit=13,
        max_rounds=2,
        run_id="i8-dev-001",
        database_path="data/evaluation/i8-dev-001/raw/repair_attempts.sqlite",
        output_dir="data/evaluation/i8-dev-001/raw/pipeline-runs",
        explainer_config="config/llm_explainer.yaml",
        repair_config="config/rag_repair.yaml",
        fix_config="config/fix_applicator.yaml",
    )
    assert argv[0] == "python"
    assert argv[1] == "scripts/run_pipeline.py"
    assert "--split" in argv and argv[argv.index("--split") + 1] == "dev"
    assert "--limit" in argv and argv[argv.index("--limit") + 1] == "13"
    assert "--max-rounds" in argv and argv[argv.index("--max-rounds") + 1] == "2"
    assert "--run-id" in argv and argv[argv.index("--run-id") + 1] == "i8-dev-001"
    assert "--overwrite" not in argv


def test_build_pipeline_argv_includes_overwrite_flag_when_set():
    argv = re_.build_pipeline_argv(
        python_executable="python",
        split="dev",
        limit=13,
        max_rounds=2,
        run_id="i8-dev-001",
        database_path="db.sqlite",
        output_dir="out",
        explainer_config="a",
        repair_config="b",
        fix_config="c",
        overwrite=True,
    )
    assert "--overwrite" in argv


# --- test fixtures: a fake repo root with the files build_manifest() reads ----

def _make_repo_fixture(tmp_path, i2_split_counts):
    (tmp_path / "config").mkdir()
    for name in ["package_mapping.yaml", "rag_repair.yaml", "llm_explainer.yaml", "fix_applicator.yaml"]:
        (tmp_path / "config" / name).write_text(f"# {name}", encoding="utf-8")
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "p.txt").write_text("prompt", encoding="utf-8")

    i2_dir = tmp_path / "data" / "context-classification"
    i2_dir.mkdir(parents=True)
    i2_path = i2_dir / "dependency_error_contexts.jsonl"
    with i2_path.open("w", encoding="utf-8") as f:
        counter = 0
        for split, count in i2_split_counts.items():
            for _ in range(count):
                f.write(json.dumps({"notebook_execution_id": counter, "split": split}) + "\n")
                counter += 1
    return tmp_path, i2_path.relative_to(tmp_path).as_posix()


def _fake_invoker_writing_n_trace_lines(n):
    def invoker(argv, cwd):
        run_id = argv[argv.index("--run-id") + 1]
        output_dir = Path(argv[argv.index("--output-dir") + 1])
        if not output_dir.is_absolute():
            output_dir = cwd / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        trace_path = output_dir / f"{run_id}.jsonl"
        with trace_path.open("w", encoding="utf-8") as f:
            for i in range(n):
                f.write(json.dumps({"notebook_execution_id": i, "rounds": []}) + "\n")
        return SimpleNamespace(returncode=0)

    return invoker


# --- end-to-end run_evaluation() with an injected fake pipeline invoker ------

def test_run_evaluation_dev_split_writes_manifest_and_reports_complete(tmp_path):
    root, i2_relpath = _make_repo_fixture(tmp_path, {"dev": 13, "evaluation": 187, "excluded": 14})
    result = re_.run_evaluation(
        split="dev",
        run_id="i8-dev-001",
        i2_path=i2_relpath,
        root=root,
        pipeline_invoker=_fake_invoker_writing_n_trace_lines(13),
        repository_metadata_db_path=None,
    )
    assert result["expected_record_count"] == 13
    assert result["actual_record_count"] == 13
    assert result["complete"] is True
    assert Path(result["manifest_path"]).is_file()


def test_run_evaluation_detects_incomplete_run(tmp_path):
    root, i2_relpath = _make_repo_fixture(tmp_path, {"dev": 13, "evaluation": 187, "excluded": 14})
    with pytest.raises(re_.EvaluationRunError, match="incomplete run"):
        re_.run_evaluation(
            split="dev",
            run_id="i8-dev-002",
            i2_path=i2_relpath,
            root=root,
            pipeline_invoker=_fake_invoker_writing_n_trace_lines(10),  # short of 13
            repository_metadata_db_path=None,
        )


def test_run_evaluation_raises_on_nonzero_pipeline_exit(tmp_path):
    root, i2_relpath = _make_repo_fixture(tmp_path, {"dev": 13})

    def failing_invoker(argv, cwd):
        return SimpleNamespace(returncode=1)

    with pytest.raises(re_.EvaluationRunError, match="exited with code 1"):
        re_.run_evaluation(
            split="dev",
            run_id="i8-dev-003",
            i2_path=i2_relpath,
            root=root,
            pipeline_invoker=failing_invoker,
            repository_metadata_db_path=None,
        )


def test_run_evaluation_refuses_evaluation_split_without_explicit_guard(tmp_path):
    root, i2_relpath = _make_repo_fixture(tmp_path, {"dev": 13, "evaluation": 187})
    with pytest.raises(re_.EvaluationRunError, match="refusing to run --split evaluation"):
        re_.run_evaluation(
            split="evaluation",
            run_id="i8-eval-001",
            i2_path=i2_relpath,
            root=root,
            pipeline_invoker=_fake_invoker_writing_n_trace_lines(187),
            repository_metadata_db_path=None,
        )


def test_run_evaluation_resume_with_identical_config_succeeds(tmp_path):
    root, i2_relpath = _make_repo_fixture(tmp_path, {"dev": 13})
    kwargs = dict(
        split="dev",
        run_id="i8-dev-resume",
        i2_path=i2_relpath,
        root=root,
        repository_metadata_db_path=None,
    )
    re_.run_evaluation(pipeline_invoker=_fake_invoker_writing_n_trace_lines(13), **kwargs)
    # Resuming with the exact same configuration must not raise.
    re_.run_evaluation(pipeline_invoker=_fake_invoker_writing_n_trace_lines(13), **kwargs)


def test_run_evaluation_resume_rejects_changed_config(tmp_path):
    root, i2_relpath = _make_repo_fixture(tmp_path, {"dev": 13})
    re_.run_evaluation(
        split="dev",
        run_id="i8-dev-resume-2",
        i2_path=i2_relpath,
        root=root,
        pipeline_invoker=_fake_invoker_writing_n_trace_lines(13),
        repository_metadata_db_path=None,
        model="gemma2:9b",
    )
    with pytest.raises(em.ManifestConsistencyError):
        re_.run_evaluation(
            split="dev",
            run_id="i8-dev-resume-2",
            i2_path=i2_relpath,
            root=root,
            pipeline_invoker=_fake_invoker_writing_n_trace_lines(13),
            repository_metadata_db_path=None,
            model="a-completely-different-model",
        )


def test_run_evaluation_resume_rejects_changed_prompt_hash(tmp_path):
    root, i2_relpath = _make_repo_fixture(tmp_path, {"dev": 13})
    re_.run_evaluation(
        split="dev",
        run_id="i8-dev-resume-3",
        i2_path=i2_relpath,
        root=root,
        pipeline_invoker=_fake_invoker_writing_n_trace_lines(13),
        repository_metadata_db_path=None,
    )
    (root / "prompts" / "p.txt").write_text("a different prompt entirely", encoding="utf-8")
    with pytest.raises(em.ManifestConsistencyError):
        re_.run_evaluation(
            split="dev",
            run_id="i8-dev-resume-3",
            i2_path=i2_relpath,
            root=root,
            pipeline_invoker=_fake_invoker_writing_n_trace_lines(13),
            repository_metadata_db_path=None,
        )


def test_run_evaluation_raises_when_expected_count_is_zero(tmp_path):
    root, i2_relpath = _make_repo_fixture(tmp_path, {"evaluation": 187})  # no dev records at all
    with pytest.raises(re_.EvaluationRunError, match="expected_record_count"):
        re_.run_evaluation(
            split="dev",
            run_id="i8-dev-empty",
            i2_path=i2_relpath,
            root=root,
            pipeline_invoker=_fake_invoker_writing_n_trace_lines(0),
            repository_metadata_db_path=None,
        )


# --- --fix-config / --repository-metadata-db-path CLI wiring -----------------

def test_cli_fix_config_and_metadata_db_path_default_match_function_defaults():
    """Backward compatibility: omitting both flags must produce exactly the
    same values run_evaluation()'s own keyword defaults use."""
    args = re_.parse_args(["--split", "dev", "--run-id", "test-id"])
    assert args.fix_config == re_.DEFAULT_FIX_CONFIG
    assert args.repository_metadata_db_path == re_.DEFAULT_REPOSITORY_METADATA_DB_PATH


def test_cli_fix_config_and_metadata_db_path_accept_overrides():
    args = re_.parse_args(
        [
            "--split", "dev",
            "--run-id", "test-id",
            "--fix-config", "config/fix_applicator.evaluation.local.yaml",
            "--repository-metadata-db-path", "/mnt/c/Users/zaimi/i8-eval-local-cache/upstream_pmc_docker_db.sqlite",
        ]
    )
    assert args.fix_config == "config/fix_applicator.evaluation.local.yaml"
    assert args.repository_metadata_db_path == "/mnt/c/Users/zaimi/i8-eval-local-cache/upstream_pmc_docker_db.sqlite"


def test_main_passes_cli_fix_config_and_metadata_db_path_into_run_evaluation(tmp_path, monkeypatch):
    """CLI values must actually reach run_evaluation() - captured via a
    monkeypatched run_evaluation rather than exercising the real pipeline."""
    captured = {}

    def fake_run_evaluation(**kwargs):
        captured.update(kwargs)
        return {"run_id": kwargs["run_id"], "complete": True}

    monkeypatch.setattr(re_, "run_evaluation", fake_run_evaluation)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_evaluation.py",
            "--split", "dev",
            "--run-id", "test-id",
            "--fix-config", "config/fix_applicator.evaluation.local.yaml",
            "--repository-metadata-db-path", "/mnt/c/Users/zaimi/i8-eval-local-cache/upstream_pmc_docker_db.sqlite",
        ],
    )
    re_.main()
    assert captured["fix_config"] == "config/fix_applicator.evaluation.local.yaml"
    assert captured["repository_metadata_db_path"] == "/mnt/c/Users/zaimi/i8-eval-local-cache/upstream_pmc_docker_db.sqlite"


def test_run_evaluation_threads_fix_config_into_manifest_and_pipeline_argv(tmp_path):
    """End-to-end (via the fake pipeline invoker): a non-default fix_config
    must reach both the manifest and the actual scripts/run_pipeline.py argv."""
    root, i2_relpath = _make_repo_fixture(tmp_path, {"dev": 13})
    (root / "config" / "fix_applicator.evaluation.local.yaml").write_text("# local override", encoding="utf-8")

    captured_argv = {}

    def capturing_invoker(argv, cwd):
        captured_argv["argv"] = argv
        return _fake_invoker_writing_n_trace_lines(13)(argv, cwd)

    result = re_.run_evaluation(
        split="dev",
        run_id="i8-dev-fixconfig",
        i2_path=i2_relpath,
        root=root,
        pipeline_invoker=capturing_invoker,
        fix_config="config/fix_applicator.evaluation.local.yaml",
        repository_metadata_db_path=None,
    )

    manifest = em.load_manifest(Path(result["manifest_path"]))
    assert manifest["config_paths"]["fix_config"] == "config/fix_applicator.evaluation.local.yaml"

    argv = captured_argv["argv"]
    assert argv[argv.index("--fix-config") + 1] == "config/fix_applicator.evaluation.local.yaml"


def test_run_evaluation_manifest_uses_supplied_metadata_db_path_and_records_sha256(tmp_path):
    root, i2_relpath = _make_repo_fixture(tmp_path, {"dev": 13})
    local_db = tmp_path / "upstream_pmc_docker_db.sqlite"
    local_db.write_bytes(b"pretend sqlite bytes for hashing")

    result = re_.run_evaluation(
        split="dev",
        run_id="i8-dev-metadatadb",
        i2_path=i2_relpath,
        root=root,
        pipeline_invoker=_fake_invoker_writing_n_trace_lines(13),
        repository_metadata_db_path=str(local_db),
    )

    manifest = em.load_manifest(Path(result["manifest_path"]))
    metadata_db = manifest["repository_metadata_db"]
    assert metadata_db["configured_path"] == str(local_db)
    assert metadata_db["accessible"] is True
    assert metadata_db["sha256"] == em.hash_file(local_db)


def test_run_evaluation_manifest_metadata_db_sha256_is_none_when_inaccessible(tmp_path):
    root, i2_relpath = _make_repo_fixture(tmp_path, {"dev": 13})

    result = re_.run_evaluation(
        split="dev",
        run_id="i8-dev-metadatadb-missing",
        i2_path=i2_relpath,
        root=root,
        pipeline_invoker=_fake_invoker_writing_n_trace_lines(13),
        repository_metadata_db_path=str(tmp_path / "does_not_exist.sqlite"),
    )

    manifest = em.load_manifest(Path(result["manifest_path"]))
    metadata_db = manifest["repository_metadata_db"]
    assert metadata_db["accessible"] is False
    assert metadata_db["sha256"] is None


def test_run_evaluation_default_fix_config_and_metadata_db_path_unchanged(tmp_path):
    """Backward compatibility: not passing fix_config/repository_metadata_db_path
    at all must still produce the same manifest config_paths.fix_config as
    before this change."""
    root, i2_relpath = _make_repo_fixture(tmp_path, {"dev": 13})

    result = re_.run_evaluation(
        split="dev",
        run_id="i8-dev-defaults",
        i2_path=i2_relpath,
        root=root,
        pipeline_invoker=_fake_invoker_writing_n_trace_lines(13),
    )

    manifest = em.load_manifest(Path(result["manifest_path"]))
    assert manifest["config_paths"]["fix_config"] == re_.DEFAULT_FIX_CONFIG
    assert manifest["repository_metadata_db"]["configured_path"] == re_.DEFAULT_REPOSITORY_METADATA_DB_PATH
