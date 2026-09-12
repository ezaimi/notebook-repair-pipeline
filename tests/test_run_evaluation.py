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
