import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pllm_style_baseline as baseline


def record():
    return {
        "notebook_execution_id": 8,
        "repository_id": 14,
        "notebook_id": 27,
        "notebook_name": "example.ipynb",
        "repository_url": "https://example.invalid/repo",
        "split": "dev",
        "error_type": "ModuleNotFoundError",
        "error_message": "No module named 'sklearn'",
        "failing_module": "sklearn",
    }


def test_reference_distribution_uses_pllm_table_not_thesis_mapping():
    links = {"sklearn": {"ref": "scikit-learn"}}
    assert baseline.distribution_from_reference("sklearn.metrics", links) == "scikit-learn"
    assert baseline.distribution_from_reference("unmapped", links) == "unmapped"


def test_reference_distribution_list_comes_only_from_pllm_reference_table():
    links = {
        "sklearn": {"ref": "scikit-learn"},
        "sklearn_extra": {"ref": "scikit-learn"},
        "pandas": {"ref": "pandas"},
        "invalid": {"ref": "bad;name"},
    }
    assert baseline.reference_distributions(links) == ["pandas", "scikit-learn"]


def test_record_distributions_includes_unknown_import_roots(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text("\n".join([
        json.dumps({"split": "evaluation", "failing_module": "sklearn"}),
        json.dumps({"split": "evaluation", "failing_module": "pyrosm.network"}),
        json.dumps({"split": "dev", "failing_module": "pandas"}),
    ]) + "\n", encoding="utf-8")
    assert baseline.record_distributions(str(path), "evaluation", {"sklearn": {"ref": "scikit-learn"}}) == [
        "pyrosm", "scikit-learn"
    ]


def test_parse_proposal_is_lightweight_and_rejects_unsafe_tokens():
    proposal, error = baseline.parse_proposal(
        json.dumps({"package": "scikit-learn", "version": "1.5.2", "rationale": "matches import"})
    )
    assert error is None
    assert proposal["package"] == "scikit-learn"
    assert proposal["version"] == "1.5.2"

    proposal, error = baseline.parse_proposal('```json\n{"package":"pandas","version":null}\n```')
    assert error is None
    assert proposal["package"] == "pandas"

    proposal, error = baseline.parse_proposal('{"package": "bad;rm", "version": null}')
    assert proposal is None
    assert error == "invalid package name"


def test_fetch_pypi_project_uses_cached_metadata_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "ROOT", tmp_path)
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({
        "scikit-learn": {
            "payload": {
                "info": {"version": "1.5.2"},
                "releases": {
                    "1.5.1": [{"yanked": False}],
                    "1.5.2": [{"yanked": False}],
                },
            }
        }
    }), encoding="utf-8")

    result = baseline.fetch_pypi_project(
        "scikit-learn", {"cache_path": "cache.json", "allow_network": False}, "3.10"
    )
    assert result["status"] == "resolved"
    assert result["source"] == "cache"
    assert result["versions"] == ["1.5.1", "1.5.2"]


def test_fetch_pypi_project_uses_a_cached_negative_pypi_response(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "ROOT", tmp_path)
    (tmp_path / "cache.json").write_text(json.dumps({
        "not-a-project": {
            "result": {"status": "not_found", "distribution": "not-a-project", "versions": []}
        }
    }), encoding="utf-8")

    result = baseline.fetch_pypi_project(
        "not-a-project", {"cache_path": "cache.json", "allow_network": False}, "3.10"
    )
    assert result["status"] == "not_found"
    assert result["source"] == "cache"


def test_pypi_cache_is_loaded_once_per_runtime_config(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "ROOT", tmp_path)
    (tmp_path / "cache.json").write_text(json.dumps({
        "pandas": {"payload": {"info": {"version": "1.0"}, "releases": {"1.0": [{"yanked": False}]}}},
        "numpy": {"payload": {"info": {"version": "1.0"}, "releases": {"1.0": [{"yanked": False}]}}},
    }), encoding="utf-8")
    calls = []
    original_load = baseline._load_cache
    monkeypatch.setattr(baseline, "_load_cache", lambda path: calls.append(path) or original_load(path))

    config = {"cache_path": "cache.json", "allow_network": False}
    baseline.fetch_pypi_project("pandas", config, "3.10")
    baseline.fetch_pypi_project("numpy", config, "3.10")
    assert len(calls) == 1


def test_pypi_versions_are_filtered_for_the_pipeline_python_version():
    payload = {"info": {"version": "2.0"}, "releases": {
        "1.0": [{"yanked": False, "requires_python": ">=3.9"}],
        "2.0": [{"yanked": False, "requires_python": ">=3.11"}],
    }}
    result = baseline._pypi_result("example", payload, "test", "3.10")
    assert result["versions"] == ["1.0"]
    assert result["latest_version"] == "1.0"


def test_feedback_record_only_continues_for_a_new_dependency_error():
    first = {"outcome": "still_failing", "same_as_original_error": False,
             "new_error_type": "ModuleNotFoundError", "new_error_message": "No module named 'pandas'"}
    feedback = baseline.build_feedback_record(record(), first)
    assert feedback["failing_module"] == "pandas"

    unchanged = dict(first, same_as_original_error=True)
    assert baseline.build_feedback_record(record(), unchanged) is None

    non_dependency = dict(first, new_error_type="FileNotFoundError")
    assert baseline.build_feedback_record(record(), non_dependency) is None


def test_process_record_runs_at_most_two_feedback_driven_rounds(monkeypatch):
    config = {
        "baseline": {
            "runtime_python_version": "3.10",
            "repair": {"max_rounds": 2, "prompt_version": "test"},
            "pypi": {"candidate_version_limit": 3},
            "model": {},
        }
    }
    links = {"sklearn": {"ref": "scikit-learn"}, "pandas": {"ref": "pandas"}}

    monkeypatch.setattr(baseline, "fetch_pypi_project", lambda distribution, _config, _runtime: {
        "status": "resolved", "distribution": distribution, "latest_version": "1.0",
        "versions": ["1.0"], "source": "test",
    })

    model_responses = iter([
        (json.dumps({"package": "scikit-learn", "version": None, "rationale": "first"}), {}),
        (json.dumps({"package": "pandas", "version": None, "rationale": "second"}), {}),
    ])
    calls = []

    def fake_applier(i4_record, *_args, **kwargs):
        calls.append((i4_record, kwargs.get("prior_fix_argvs")))
        if len(calls) == 1:
            return {
                "outcome": "still_failing", "same_as_original_error": False,
                "new_error_type": "ModuleNotFoundError", "new_error_message": "No module named 'pandas'",
                "argv": i4_record["argv"], "command": " ".join(i4_record["argv"]),
            }
        return {"outcome": "fixed", "argv": i4_record["argv"], "command": " ".join(i4_record["argv"])}

    trace = baseline.process_record(
        record(), config, {}, {}, lambda _repo: None, links, "test-run",
        model_call=lambda *_args: next(model_responses), applier=fake_applier,
    )

    assert len(trace["rounds"]) == 2
    assert calls[0][0]["final_install_name"] == "scikit-learn"
    assert calls[1][0]["final_install_name"] == "pandas"
    assert calls[1][1] == [["python", "-m", "pip", "install", "scikit-learn"]]
