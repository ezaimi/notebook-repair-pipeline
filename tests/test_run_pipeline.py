import json
import sqlite3
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import docker_runner
import fix_applicator
import pypi_retriever
import rag_repair_agent
import result_logger
import run_llm_explainer
import run_pipeline
from pypi_retriever import load_rag_repair_config
from run_pipeline import (
    build_excluded_repair_stub,
    build_round2_record,
    evaluate_round2_trigger,
    load_all_records,
    make_run_id,
    open_repair_attempts_db,
    parse_args,
    process_record,
    run_repair_round,
    select_records,
)
from run_pipeline import _reset_repair_attempts_table


# --- shared fixtures / fakes --------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_pypi_cache(monkeypatch):
    pypi_retriever.clear_pypi_cache()
    pypi_retriever.reset_pypi_rate_limiter()
    monkeypatch.setattr(pypi_retriever.time, "sleep", lambda seconds: None)
    yield
    pypi_retriever.clear_pypi_cache()
    pypi_retriever.reset_pypi_rate_limiter()


@pytest.fixture
def repair_config():
    return load_rag_repair_config()


@pytest.fixture
def fix_config():
    return {"execution": {}}


@pytest.fixture
def explainer_config():
    return {
        "models": {"primary": "gemma2:9b", "fallback": None},
        "generation": {"temperature": 0.1, "top_p": 0.9, "max_tokens": 700, "timeout_seconds": 5},
        "retry": {"max_retries": 0, "retry_on": []},
        "prompt": {"strategy": "few_shot", "template": "dependency_explanation_v1", "version": "i3_prompt_v1"},
        "output": {"schema": "schemas/explanation.schema.json"},
    }


@pytest.fixture
def explainer_template():
    return (ROOT / "prompts" / "dependency_explanation_v1.txt").read_text(encoding="utf-8")


# --- load_configs(): provider-aware --model override (LLM model----------
# sensitivity supplementary experiment) ---------------------------------

def test_load_configs_model_override_defaults_to_ollama_when_provider_absent():
    """Backward compatibility: the real config/*.yaml files declare no
    provider key, so --model must land exactly where it always has -
    repair_agent.ollama.model - unchanged by the provider-aware rewrite."""
    args = SimpleNamespace(
        explainer_config=str(ROOT / "config" / "llm_explainer.yaml"),
        repair_config=str(ROOT / "config" / "rag_repair.yaml"),
        fix_config=str(ROOT / "config" / "fix_applicator.yaml"),
        model="override-model",
        prompt_strategy=None,
    )

    explainer_cfg, repair_cfg, _fix_cfg = run_pipeline.load_configs(args)

    assert explainer_cfg["models"]["primary"] == "override-model"
    assert repair_cfg["repair_agent"]["ollama"]["model"] == "override-model"


def test_load_configs_model_override_is_provider_aware_for_kiste(tmp_path):
    """A repair config declaring repair_agent.provider: kiste must receive
    the --model override in repair_agent.kiste.model, never silently land
    in an unused repair_agent.ollama.model that provider: kiste never
    reads."""
    explainer_path = tmp_path / "llm_explainer.kiste.yaml"
    explainer_path.write_text(
        "provider: kiste\n"
        "models:\n  primary: original-model\n  fallback: null\n"
        "kiste:\n  base_url: https://kiste.example.invalid/v1\n"
        "generation:\n  temperature: 0.1\n  top_p: 0.9\n  max_tokens: 700\n  timeout_seconds: 120\n"
        "retry:\n  max_retries: 1\n  retry_on: []\n"
        "prompt:\n  strategy: few_shot\n  template: dependency_explanation_v1\n  version: i3_prompt_v1\n"
        "output:\n  path: data/x.jsonl\n  schema: schemas/explanation.schema.json\n",
        encoding="utf-8",
    )
    repair_path = tmp_path / "rag_repair.kiste.yaml"
    repair_path.write_text(
        "repair_agent:\n"
        "  provider: kiste\n"
        "  kiste:\n"
        "    base_url: https://kiste.example.invalid/v1\n"
        "    model: original-kiste-model\n"
        "  prompt:\n    template: dependency_repair_v1\n    version: i4_prompt_v1\n"
        "  retry:\n    max_retries: 1\n    retry_on: []\n"
        "  output:\n    path: data/y.jsonl\n    schema: schemas/repair_proposal.schema.json\n",
        encoding="utf-8",
    )

    args = SimpleNamespace(
        explainer_config=str(explainer_path),
        repair_config=str(repair_path),
        fix_config=str(ROOT / "config" / "fix_applicator.yaml"),
        model="Qwen3.6-35B-A3B-MLX-8bit",
        prompt_strategy=None,
    )

    explainer_cfg, repair_cfg, _fix_cfg = run_pipeline.load_configs(args)

    assert explainer_cfg["models"]["primary"] == "Qwen3.6-35B-A3B-MLX-8bit"
    assert repair_cfg["repair_agent"]["kiste"]["model"] == "Qwen3.6-35B-A3B-MLX-8bit"
    assert "ollama" not in repair_cfg["repair_agent"]


def always_not_logged(notebook_execution_id, run_id, round_number):
    return False


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def mock_pypi(monkeypatch, distribution, versions, requires_python=">=3.10"):
    def fake_urlopen(request, timeout=None):
        return FakeResponse(
            json.dumps(
                {
                    "files": [
                        {"filename": f"{distribution}-{v}.tar.gz", "yanked": False, "requires-python": requires_python}
                        for v in versions
                    ]
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(pypi_retriever.urllib.request, "urlopen", fake_urlopen)


def ollama_repair_response(action, install_name, version, rationale="grounded rationale"):
    return json.dumps({"action": action, "install_name": install_name, "version": version, "rationale": rationale})


def valid_explanation_json():
    return json.dumps(
        {
            "summary": "A dependency is missing.",
            "root_cause": "The notebook imports a package that is not installed.",
            "evidence": ["error message"],
            "failing_module": "example",
            "explanation_confidence": "high",
            "limitations": "Only metadata is available.",
        }
    )


def _completed(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _clean_notebook_json():
    return json.dumps({"cells": [{"cell_type": "code", "outputs": []}], "nbformat": 4})


def _error_notebook_json(ename, evalue):
    return json.dumps(
        {
            "cells": [
                {
                    "cell_type": "code",
                    "outputs": [{"output_type": "error", "ename": ename, "evalue": evalue, "traceback": []}],
                }
            ],
            "nbformat": 4,
        }
    )


class SequencedDockerRunner:
    """Scripts git/docker calls across possibly-multiple apply_and_validate()
    invocations (one per repair round). "docker run" outcomes are consumed
    from a queue, one per call, in order; every other call (clone/checkout/
    build/rm) always succeeds. Mirrors tests/test_fix_applicator.py's own
    ScriptedDockerRunner, extended to script a *sequence* of runs rather
    than just one, since an i7 test can drive two rounds through one runner
    instance."""

    def __init__(self, run_outcomes):
        # run_outcomes: list of (writes, stdout) tuples, consumed in order.
        # writes is "fixed" | (ename, evalue) | "no_file".
        self.run_outcomes = list(run_outcomes)
        self.calls = []
        self.build_dirs = []
        # entrypoint.sh content captured at "docker build" time, before
        # apply_and_validate()'s own cleanup() deletes the work dir in its
        # finally block - reading it back afterwards would find nothing.
        self.build_entrypoints = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        key = (argv[0], argv[1] if len(argv) > 1 else None)

        if key == ("git", "clone"):
            Path(argv[3]).mkdir(parents=True, exist_ok=True)
            return _completed(returncode=0)
        if key == ("git", "checkout"):
            return _completed(returncode=0)
        if key == ("docker", "build"):
            build_dir = Path(argv[-1])
            self.build_dirs.append(build_dir)
            self.build_entrypoints.append((build_dir / "entrypoint.sh").read_text(encoding="utf-8"))
            return _completed(returncode=0)
        if key == ("docker", "run"):
            host_repo_dir = self._extract_volume_host_path(argv)
            writes, stdout = self.run_outcomes.pop(0)
            if writes == "fixed":
                (host_repo_dir / "notebook_output.ipynb").write_text(_clean_notebook_json(), encoding="utf-8")
            elif isinstance(writes, tuple):
                (host_repo_dir / "notebook_output.ipynb").write_text(
                    _error_notebook_json(*writes), encoding="utf-8"
                )
            return _completed(returncode=0, stdout=stdout)
        if key == ("docker", "rm"):
            return _completed(returncode=0)

        raise AssertionError(f"unscripted call: {argv}")

    @staticmethod
    def _extract_volume_host_path(argv) -> Path:
        for i, item in enumerate(argv):
            if item == "-v":
                volume_arg = argv[i + 1]
                assert volume_arg.endswith(":/app")
                return Path(volume_arg[: -len(":/app")])
        raise AssertionError("no -v volume argument found")


class RefusingRunner:
    def __call__(self, argv, **kwargs):
        raise AssertionError(f"subprocess should never have been called, got: {argv}")


# --- record fixtures -----------------------------------------------------------


def sklearn_record():
    return {
        "notebook_execution_id": 8,
        "error_type": "ModuleNotFoundError",
        "error_message": "No module named 'sklearn'",
        "original_subtype": "missing_package",
        "refined_subtype": "missing_package",
        "scope_status": "usable",
        "exclusion_reason": None,
        "split": "dev",
        "failing_module": "sklearn",
        "root_cause_hint": "import_distribution_name_mismatch",
        "context_status": "metadata_only",
        "repository_id": 14,
        "notebook_id": 27,
        "notebook_name": "notebook.ipynb",
        "repository_url": "https://github.com/org/repo",
    }


def cumtrapz_record():
    return {
        "notebook_execution_id": 174,
        "error_type": "ImportError",
        "error_message": (
            "cannot import name 'cumtrapz' from 'scipy.integrate' "
            "(/tmp/.local/lib/python3.10/site-packages/scipy/integrate/__init__.py)"
        ),
        "original_subtype": "wrong_version",
        "refined_subtype": "wrong_version",
        "scope_status": "usable",
        "exclusion_reason": None,
        "split": "dev",
        "failing_module": "scipy",
        "root_cause_hint": "version_or_api_incompatibility",
        "context_status": "metadata_only",
        "repository_id": 55,
        "notebook_id": 91,
        "notebook_name": "notebook.ipynb",
        "repository_url": "https://github.com/org/mdsuite-like-repo",
    }


def system_library_record():
    return {
        "notebook_execution_id": 15,
        "error_type": "ImportError",
        "error_message": "libxcb.so.1: cannot open shared object file: No such file or directory",
        "original_subtype": "system_library",
        "refined_subtype": "system_library",
        "scope_status": "excluded",
        "exclusion_reason": "requires system library, outside pip-only scope",
        "split": "excluded",
        "failing_module": "libxcb.so.1",
        "root_cause_hint": "system_level_dependency",
        "context_status": "metadata_only",
        "repository_id": 16,
        "notebook_id": 35,
        "notebook_name": "notebook.ipynb",
        "repository_url": "https://github.com/org/repo2",
    }


def i2_index_for(*records):
    return {r["notebook_execution_id"]: r for r in records}


# =============================================================================
# 1. select_records: split / start-index / limit
# =============================================================================


def _make_records(splits):
    return [{"notebook_execution_id": i, "split": s} for i, s in enumerate(splits)]


def test_select_records_filters_by_split_preserving_original_index():
    records = _make_records(["dev", "evaluation", "dev", "excluded", "dev"])
    selected = select_records(records, "dev", 0, None)
    assert [i for i, _ in selected] == [0, 2, 4]


def test_select_records_start_index_applies_after_split_filter():
    records = _make_records(["dev", "evaluation", "dev", "excluded", "dev"])
    selected = select_records(records, "dev", 1, None)
    assert [i for i, _ in selected] == [2, 4]


def test_select_records_limit_applies_after_split_filter():
    records = _make_records(["dev", "evaluation", "dev", "excluded", "dev"])
    selected = select_records(records, "dev", 0, 2)
    assert [i for i, _ in selected] == [0, 2]


def test_select_records_split_all_returns_every_record_in_order():
    records = _make_records(["dev", "evaluation", "dev", "excluded", "dev"])
    selected = select_records(records, "all", 0, None)
    assert [i for i, _ in selected] == [0, 1, 2, 3, 4]


def test_select_records_evaluation_split_is_isolated_from_dev():
    records = _make_records(["dev", "evaluation", "dev", "excluded", "dev"])
    selected = select_records(records, "evaluation", 0, None)
    assert [i for i, _ in selected] == [1]


def test_load_all_records_preserves_file_order(tmp_path):
    path = tmp_path / "i2.jsonl"
    path.write_text(
        "\n".join(json.dumps({"notebook_execution_id": i}) for i in [8, 15, 174]) + "\n", encoding="utf-8"
    )
    records = load_all_records(str(path))
    assert [r["notebook_execution_id"] for r in records] == [8, 15, 174]


def test_make_run_id_shape():
    run_id = make_run_id()
    assert run_id.startswith("i7-")
    assert run_id.endswith("Z")


# =============================================================================
# 2. evaluate_round2_trigger: pure classification-driven trigger rules
# =============================================================================


def _still_failing_i5_result(new_error_type, new_error_message, same_as_original=False, argv=None):
    return {
        "outcome": "still_failing",
        "new_error_type": new_error_type,
        "new_error_message": new_error_message,
        "same_as_original_error": same_as_original,
        "argv": argv or ["python", "-m", "pip", "install", "scipy==1.13.1"],
    }


def test_round2_not_triggered_when_round1_outcome_is_fixed():
    trigger = evaluate_round2_trigger({"outcome": "fixed"}, cumtrapz_record())
    assert trigger["triggered"] is False
    assert trigger["reason"] == "round1_outcome_not_still_failing"


def test_round2_not_triggered_when_round1_outcome_is_apply_error():
    trigger = evaluate_round2_trigger({"outcome": "apply_error"}, cumtrapz_record())
    assert trigger["triggered"] is False


def test_round2_not_triggered_when_i5_result_is_none():
    trigger = evaluate_round2_trigger(None, cumtrapz_record())
    assert trigger["triggered"] is False


def test_round2_not_triggered_when_same_as_original_error():
    i5_result = _still_failing_i5_result("ImportError", "cannot import name 'cumtrapz' ...", same_as_original=True)
    trigger = evaluate_round2_trigger(i5_result, cumtrapz_record())
    assert trigger["triggered"] is False
    assert trigger["reason"] == "same_as_original_error"


def test_round2_triggered_for_new_eligible_missing_package_error():
    i5_result = _still_failing_i5_result("ModuleNotFoundError", "No module named 'pandas'")
    trigger = evaluate_round2_trigger(i5_result, cumtrapz_record())
    assert trigger["triggered"] is True
    assert trigger["round2_record"]["scope_status"] == "usable"
    assert trigger["round2_record"]["refined_subtype"] == "missing_package"
    assert trigger["round2_record"]["failing_module"] == "pandas"
    # notebook identity is preserved from the original record
    assert trigger["round2_record"]["notebook_execution_id"] == 174
    assert trigger["round2_record"]["repository_url"] == "https://github.com/org/mdsuite-like-repo"
    # no source context is invented for a failure that was never re-fetched
    assert trigger["round2_record"].get("prompt_context") is None


def test_round2_not_triggered_for_non_dependency_related_new_error():
    i5_result = _still_failing_i5_result("KeyError", "'some_key'")
    trigger = evaluate_round2_trigger(i5_result, cumtrapz_record())
    assert trigger["triggered"] is False
    assert trigger["round2_record"]["scope_status"] == "excluded"
    assert trigger["round2_record"]["original_subtype"] == "out_of_scope"


def test_round2_not_triggered_for_system_library_new_error():
    i5_result = _still_failing_i5_result(
        "ImportError", "libxcb.so.1: cannot open shared object file: No such file or directory"
    )
    trigger = evaluate_round2_trigger(i5_result, cumtrapz_record())
    assert trigger["triggered"] is False
    assert "system_library" in trigger["reason"] or trigger["round2_record"]["original_subtype"] == "system_library"
    assert trigger["round2_record"]["scope_status"] == "excluded"


def test_round2_not_triggered_for_mapping_unknown_new_error():
    i5_result = _still_failing_i5_result("ModuleNotFoundError", "No module named 'utils'")
    trigger = evaluate_round2_trigger(i5_result, cumtrapz_record())
    assert trigger["triggered"] is False
    assert trigger["round2_record"]["original_subtype"] == "mapping_unknown"
    assert trigger["round2_record"]["scope_status"] == "excluded"


def test_round2_not_triggered_when_new_error_type_missing():
    i5_result = {"outcome": "still_failing", "new_error_type": None, "new_error_message": None}
    trigger = evaluate_round2_trigger(i5_result, cumtrapz_record())
    assert trigger["triggered"] is False
    assert trigger["reason"] == "no_new_error_recorded"


def test_build_round2_record_never_invents_prompt_context():
    record = build_round2_record(cumtrapz_record(), "ModuleNotFoundError", "No module named 'tf_keras'")
    assert record.get("prompt_context") is None
    assert record["failing_module"] == "tf_keras"
    assert record["notebook_name"] == "notebook.ipynb"


# =============================================================================
# 3. build_excluded_repair_stub: never calls RAGRepairAgent
# =============================================================================


def test_build_excluded_repair_stub_never_calls_run_repair_agent(monkeypatch):
    def fail_if_called(*a, **k):
        raise AssertionError("run_repair_agent must never be called for an excluded record")

    monkeypatch.setattr(rag_repair_agent, "run_repair_agent", fail_if_called)

    stub = build_excluded_repair_stub(system_library_record(), "i7-test-run")
    assert stub["status"] == "abstained"
    assert stub["final_action"] == "none"
    assert stub["eligibility"]["decision"] == "excluded"
    assert stub["run_id"] == "i7-test-run"


# =============================================================================
# 4. process_record: excluded record is explanation-only
# =============================================================================


def test_excluded_record_is_explained_but_never_repaired(monkeypatch, explainer_config, explainer_template, repair_config, fix_config):
    monkeypatch.setattr(run_llm_explainer, "call_ollama", lambda **kwargs: (valid_explanation_json(), {}))

    def fail_if_called(*a, **k):
        raise AssertionError("RAGRepairAgent must never be called for an excluded record")

    monkeypatch.setattr(rag_repair_agent, "run_repair_agent", fail_if_called)
    monkeypatch.setattr(fix_applicator, "apply_and_validate", fail_if_called)

    record = system_library_record()
    diagnostics, pending_rows = process_record(
        record, 0, "i7-test-run", 2,
        explainer_config, explainer_template, "schemas/explanation.schema.json",
        repair_config, fix_config, i2_index_for(record), None, RefusingRunner(), None,
        always_not_logged,
    )

    assert diagnostics["explanation_status"] == "success"
    assert diagnostics["repair_eligibility"]["decision"] == "excluded"
    assert len(pending_rows) == 1
    round_number, row = pending_rows[0]
    assert round_number == 1
    assert row["action"] == "none"
    assert row["outcome"] is None
    assert row["run_id"] == "i7-test-run"


# =============================================================================
# 5. process_record: Round 1 only (fixed outcome -> no Round 2)
# =============================================================================


def test_round1_fixed_outcome_does_not_trigger_round2(monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config):
    monkeypatch.setattr(run_llm_explainer, "call_ollama", lambda **kwargs: (valid_explanation_json(), {}))
    mock_pypi(monkeypatch, "scikit-learn", ["1.7.2"])
    monkeypatch.setattr(
        rag_repair_agent, "call_ollama",
        lambda **kwargs: (ollama_repair_response("install", "scikit-learn", None), {}),
    )

    runner = SequencedDockerRunner(run_outcomes=[("fixed", "FIX_INSTALL_SUCCESS")])
    record = sklearn_record()

    diagnostics, pending_rows = process_record(
        record, 0, "i7-test-run", 2,
        explainer_config, explainer_template, "schemas/explanation.schema.json",
        repair_config, fix_config, i2_index_for(record), None, runner, tmp_path,
        always_not_logged,
    )

    assert len(diagnostics["rounds"]) == 1
    assert diagnostics["rounds"][0]["i5_result"]["outcome"] == "fixed"
    assert diagnostics["rounds"][0]["round2_trigger"]["triggered"] is False
    assert len(pending_rows) == 1
    assert pending_rows[0][0] == 1


# =============================================================================
# 6. process_record: Round 1 still_failing + new eligible error -> Round 2 runs
# =============================================================================


def test_round1_still_failing_new_eligible_error_triggers_round2(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    monkeypatch.setattr(run_llm_explainer, "call_ollama", lambda **kwargs: (valid_explanation_json(), {}))
    mock_pypi(monkeypatch, "scipy", ["1.13.0", "1.13.1", "1.14.0"])

    ollama_calls = []

    def fake_ollama(**kwargs):
        ollama_calls.append(kwargs["prompt"])
        if "pandas" in kwargs["prompt"]:
            return ollama_repair_response("install", "pandas", None), {}
        return ollama_repair_response("pin_version", "scipy", "1.13.1"), {}

    monkeypatch.setattr(rag_repair_agent, "call_ollama", fake_ollama)

    # After round 1's scipy pin, PyPI is queried again for pandas in round 2.
    original_retrieve = pypi_retriever.retrieve

    def fake_retrieve(import_name, **kwargs):
        if import_name == "pandas":
            mock_pypi(monkeypatch, "pandas", ["2.2.0"])
        return original_retrieve(import_name, **kwargs)

    monkeypatch.setattr(rag_repair_agent, "retrieve", fake_retrieve)

    runner = SequencedDockerRunner(
        run_outcomes=[
            (("ModuleNotFoundError", "No module named 'pandas'"), "FIX_INSTALL_SUCCESS"),
            ("fixed", "FIX_INSTALL_SUCCESS"),
        ]
    )
    record = cumtrapz_record()

    diagnostics, pending_rows = process_record(
        record, 0, "i7-shared-run-id", 2,
        explainer_config, explainer_template, "schemas/explanation.schema.json",
        repair_config, fix_config, i2_index_for(record), None, runner, tmp_path,
        always_not_logged,
    )

    rounds = diagnostics["rounds"]
    assert len(rounds) == 2
    assert rounds[0]["i5_result"]["outcome"] == "still_failing"
    assert rounds[0]["i5_result"]["new_error_message"] == "No module named 'pandas'"
    assert rounds[0]["round2_trigger"]["triggered"] is True
    assert rounds[1]["i4_result"]["final_install_name"] == "pandas"
    assert rounds[1]["i5_result"]["outcome"] == "fixed"

    # both rounds share the same orchestration-level run_id
    assert rounds[0]["i4_result"]["run_id"] == "i7-shared-run-id"
    assert rounds[1]["i4_result"]["run_id"] == "i7-shared-run-id"
    assert rounds[0]["i5_result"]["run_id"] == "i7-shared-run-id"
    assert rounds[1]["i5_result"]["run_id"] == "i7-shared-run-id"

    # two distinct repair_attempts rows
    assert [r for r, _ in pending_rows] == [1, 2]
    row1, row2 = pending_rows[0][1], pending_rows[1][1]
    assert row1["install_name"] == "scipy"
    assert row2["install_name"] == "pandas"
    assert row1["round"] == 1 and row2["round"] == 2
    assert row1["run_id"] == row2["run_id"] == "i7-shared-run-id"

    # Round 2's environment carried Round 1's fix forward: the second
    # "docker build" produced an entrypoint that re-applies scipy==1.13.1
    # before installing pandas.
    entrypoint = runner.build_entrypoints[1]
    assert "scipy==1.13.1" in entrypoint
    assert "pandas" in entrypoint
    assert entrypoint.index("scipy==1.13.1") < entrypoint.index("pip install pandas")


def test_max_rounds_1_disables_round2_even_when_eligible(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    monkeypatch.setattr(run_llm_explainer, "call_ollama", lambda **kwargs: (valid_explanation_json(), {}))
    mock_pypi(monkeypatch, "scipy", ["1.13.0", "1.13.1", "1.14.0"])
    monkeypatch.setattr(
        rag_repair_agent, "call_ollama",
        lambda **kwargs: (ollama_repair_response("pin_version", "scipy", "1.13.1"), {}),
    )

    runner = SequencedDockerRunner(
        run_outcomes=[(("ModuleNotFoundError", "No module named 'pandas'"), "FIX_INSTALL_SUCCESS")]
    )
    record = cumtrapz_record()

    diagnostics, pending_rows = process_record(
        record, 0, "i7-test-run", 1,
        explainer_config, explainer_template, "schemas/explanation.schema.json",
        repair_config, fix_config, i2_index_for(record), None, runner, tmp_path,
        always_not_logged,
    )

    assert len(diagnostics["rounds"]) == 1
    assert "round2_trigger" not in diagnostics["rounds"][0]
    assert len(pending_rows) == 1


def test_max_rounds_hard_cap_never_exceeds_two_even_if_caller_passes_more(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    """process_record's own MAX_ROUNDS_HARD_CAP defends against a
    hypothetical bad caller passing max_rounds > 2 directly (the CLI itself
    already restricts --max-rounds to {1, 2} via argparse `choices`)."""
    monkeypatch.setattr(run_llm_explainer, "call_ollama", lambda **kwargs: (valid_explanation_json(), {}))
    mock_pypi(monkeypatch, "scipy", ["1.13.0", "1.13.1", "1.14.0"])

    def fake_ollama(**kwargs):
        if "pandas" in kwargs["prompt"]:
            return ollama_repair_response("install", "pandas", None), {}
        return ollama_repair_response("pin_version", "scipy", "1.13.1"), {}

    monkeypatch.setattr(rag_repair_agent, "call_ollama", fake_ollama)

    original_retrieve = pypi_retriever.retrieve

    def fake_retrieve(import_name, **kwargs):
        if import_name == "pandas":
            mock_pypi(monkeypatch, "pandas", ["2.2.0"])
        return original_retrieve(import_name, **kwargs)

    monkeypatch.setattr(rag_repair_agent, "retrieve", fake_retrieve)

    # Even if round 2 also comes back "still_failing" with yet another new
    # eligible error, only two rounds ever execute.
    runner = SequencedDockerRunner(
        run_outcomes=[
            (("ModuleNotFoundError", "No module named 'pandas'"), "FIX_INSTALL_SUCCESS"),
            (("ModuleNotFoundError", "No module named 'yet_another_pkg'"), "FIX_INSTALL_SUCCESS"),
        ]
    )
    record = cumtrapz_record()

    diagnostics, pending_rows = process_record(
        record, 0, "i7-test-run", 99,
        explainer_config, explainer_template, "schemas/explanation.schema.json",
        repair_config, fix_config, i2_index_for(record), None, runner, tmp_path,
        always_not_logged,
    )

    assert len(diagnostics["rounds"]) == 2
    assert len(pending_rows) == 2
    assert [r for r, _ in pending_rows] == [1, 2]


# =============================================================================
# 7. RAG abstention handled cleanly (no Docker call at all)
# =============================================================================


def test_rag_abstention_in_round1_never_touches_docker_and_stops_round_progression(
    monkeypatch, explainer_config, explainer_template, repair_config, fix_config
):
    monkeypatch.setattr(run_llm_explainer, "call_ollama", lambda **kwargs: (valid_explanation_json(), {}))

    def fail_if_llm(*a, **k):
        raise AssertionError("must not call the LLM when PyPI retrieval has nothing grounded to propose from")

    monkeypatch.setattr(rag_repair_agent, "call_ollama", fail_if_llm)

    record = {
        "notebook_execution_id": 50,
        "error_type": "ModuleNotFoundError",
        "error_message": "No module named 'dms_variants'",
        "original_subtype": "missing_package",
        "refined_subtype": "missing_package",
        "scope_status": "usable",
        "exclusion_reason": None,
        "split": "dev",
        "failing_module": "dms_variants",  # deliberately not in config/package_mapping.yaml
        "root_cause_hint": "insufficient_context",
        "context_status": "metadata_only",
        "repository_id": 99,
        "notebook_id": 199,
        "notebook_name": "notebook.ipynb",
        "repository_url": "https://github.com/org/repo3",
    }

    diagnostics, pending_rows = process_record(
        record, 0, "i7-test-run", 2,
        explainer_config, explainer_template, "schemas/explanation.schema.json",
        repair_config, fix_config, i2_index_for(record), None, RefusingRunner(), None,
        always_not_logged,
    )

    assert len(diagnostics["rounds"]) == 1
    round_entry = diagnostics["rounds"][0]
    assert round_entry["i4_result"]["status"] == "abstained"
    assert round_entry["i5_result"]["status"] == "skipped"
    assert round_entry["i5_result"]["outcome"] is None
    assert round_entry["round2_trigger"]["triggered"] is False
    assert round_entry["round2_trigger"]["reason"] == "round1_outcome_not_still_failing"
    assert len(pending_rows) == 1
    assert pending_rows[0][1]["action"] == "none"


# =============================================================================
# 8. Failure isolation: one bad notebook does not abort the next
# =============================================================================


def test_component_failure_is_isolated_and_does_not_raise(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    monkeypatch.setattr(run_llm_explainer, "call_ollama", lambda **kwargs: (valid_explanation_json(), {}))
    mock_pypi(monkeypatch, "scikit-learn", ["1.7.2"])
    monkeypatch.setattr(
        rag_repair_agent, "call_ollama",
        lambda **kwargs: (ollama_repair_response("install", "scikit-learn", None), {}),
    )

    def raising_apply_and_validate(*a, **k):
        raise RuntimeError("simulated docker daemon crash")

    monkeypatch.setattr(fix_applicator, "apply_and_validate", raising_apply_and_validate)

    record = sklearn_record()
    diagnostics, pending_rows = process_record(
        record, 0, "i7-test-run", 2,
        explainer_config, explainer_template, "schemas/explanation.schema.json",
        repair_config, fix_config, i2_index_for(record), None, RefusingRunner(), tmp_path,
        always_not_logged,
    )

    assert diagnostics["rounds"][0]["status"] == "component_error"
    assert "simulated docker daemon crash" in diagnostics["rounds"][0]["error"]
    assert pending_rows == []


class RaisingRunner:
    """Simulates an infrastructure crash (e.g. a dead Docker daemon) on the
    very first subprocess call - used to prove one notebook's failure never
    corrupts shared state that the next notebook's (separate) process_record
    call depends on."""

    def __call__(self, argv, **kwargs):
        raise RuntimeError("simulated docker daemon crash for this notebook only")


def test_a_failed_record_does_not_prevent_the_next_record_from_succeeding(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    """Mirrors what scripts/run_pipeline.py's main() loop does: call
    process_record() for each record in turn, wrapped in a per-record
    try/except. Only the runner differs between the two calls (a plain
    argument, not a monkeypatched module attribute), so no patch
    setup/teardown juggling is needed to prove isolation."""
    monkeypatch.setattr(run_llm_explainer, "call_ollama", lambda **kwargs: (valid_explanation_json(), {}))
    mock_pypi(monkeypatch, "scikit-learn", ["1.7.2"])
    monkeypatch.setattr(
        rag_repair_agent, "call_ollama",
        lambda **kwargs: (ollama_repair_response("install", "scikit-learn", None), {}),
    )

    bad_record = sklearn_record()
    good_record = sklearn_record()
    good_record["notebook_execution_id"] = 999

    results = []
    for index, (record, runner) in enumerate(
        [(bad_record, RaisingRunner()), (good_record, SequencedDockerRunner(run_outcomes=[("fixed", "FIX_INSTALL_SUCCESS")]))]
    ):
        try:
            results.append(
                process_record(
                    record, index, "i7-test-run", 2,
                    explainer_config, explainer_template, "schemas/explanation.schema.json",
                    repair_config, fix_config, i2_index_for(record), None, runner, tmp_path,
                    always_not_logged,
                )
            )
        except Exception as e:  # this is exactly what main()'s own per-record try/except guards against
            results.append(e)

    bad_diagnostics, _ = results[0]
    good_diagnostics, good_rows = results[1]

    assert bad_diagnostics["rounds"][0]["status"] == "component_error"
    assert good_diagnostics["rounds"][0]["i5_result"]["outcome"] == "fixed"
    assert len(good_rows) == 1


# =============================================================================
# 9. Resume behaviour: same run_id does not duplicate an already-logged round
# =============================================================================


def test_already_logged_round_is_skipped_and_not_duplicated(
    monkeypatch, explainer_config, explainer_template, repair_config, fix_config
):
    monkeypatch.setattr(run_llm_explainer, "call_ollama", lambda **kwargs: (valid_explanation_json(), {}))

    def fail_if_called(*a, **k):
        raise AssertionError("round 1 was already logged for this run_id; RAGRepairAgent must not be re-invoked")

    monkeypatch.setattr(rag_repair_agent, "run_repair_agent", fail_if_called)

    def already_logged_round1(notebook_execution_id, run_id, round_number):
        return round_number == 1

    record = sklearn_record()
    diagnostics, pending_rows = process_record(
        record, 0, "i7-resumed-run", 2,
        explainer_config, explainer_template, "schemas/explanation.schema.json",
        repair_config, fix_config, i2_index_for(record), None, RefusingRunner(), None,
        already_logged_round1,
    )

    assert diagnostics["rounds"] == [{"round": 1, "status": "skipped_already_logged"}]
    assert pending_rows == []


# =============================================================================
# 10. run_repair_round reuses the real component functions
# =============================================================================


def test_run_repair_round_calls_real_run_repair_agent_and_apply_and_validate(
    monkeypatch, tmp_path, repair_config, fix_config
):
    calls = {"i4": 0, "i5": 0}
    real_run_repair_agent = rag_repair_agent.run_repair_agent
    real_apply_and_validate = fix_applicator.apply_and_validate

    def spy_run_repair_agent(*a, **k):
        calls["i4"] += 1
        return real_run_repair_agent(*a, **k)

    def spy_apply_and_validate(*a, **k):
        calls["i5"] += 1
        return real_apply_and_validate(*a, **k)

    monkeypatch.setattr(rag_repair_agent, "run_repair_agent", spy_run_repair_agent)
    monkeypatch.setattr(fix_applicator, "apply_and_validate", spy_apply_and_validate)

    mock_pypi(monkeypatch, "scikit-learn", ["1.7.2"])
    monkeypatch.setattr(
        rag_repair_agent, "call_ollama",
        lambda **kwargs: (ollama_repair_response("install", "scikit-learn", None), {}),
    )

    record = sklearn_record()
    runner = SequencedDockerRunner(run_outcomes=[("fixed", "FIX_INSTALL_SUCCESS")])
    i4_result, i5_result = run_repair_round(
        record, "i7-test-run", repair_config, fix_config, i2_index_for(record), None, runner, tmp_path, None
    )

    assert calls == {"i4": 1, "i5": 1}
    assert i4_result["status"] == "success"
    assert i5_result["outcome"] == "fixed"


# =============================================================================
# 11. CLI argument validation
# =============================================================================


def test_max_rounds_rejects_value_outside_one_or_two():
    with pytest.raises(SystemExit):
        parse_args(["--max-rounds", "3"])


def test_max_rounds_accepts_one_and_two():
    assert parse_args(["--max-rounds", "1"]).max_rounds == 1
    assert parse_args(["--max-rounds", "2"]).max_rounds == 2


def test_cli_defaults_to_dev_split():
    args = parse_args([])
    assert args.split == "dev"


def test_cli_accepts_the_documented_example_invocation():
    args = parse_args(["--split", "dev", "--start-index", "0", "--limit", "1", "--max-rounds", "2"])
    assert args.split == "dev"
    assert args.start_index == 0
    assert args.limit == 1
    assert args.max_rounds == 2


# =============================================================================
# 12. ResultLogger compatibility sanity check (no changes made to it)
# =============================================================================


def test_orchestrator_rows_round_trip_through_the_existing_result_logger_schema(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    monkeypatch.setattr(run_llm_explainer, "call_ollama", lambda **kwargs: (valid_explanation_json(), {}))
    mock_pypi(monkeypatch, "scikit-learn", ["1.7.2"])
    monkeypatch.setattr(
        rag_repair_agent, "call_ollama",
        lambda **kwargs: (ollama_repair_response("install", "scikit-learn", None), {}),
    )

    record = sklearn_record()
    runner = SequencedDockerRunner(run_outcomes=[("fixed", "FIX_INSTALL_SUCCESS")])
    _, pending_rows = process_record(
        record, 0, "i7-test-run", 1,
        explainer_config, explainer_template, "schemas/explanation.schema.json",
        repair_config, fix_config, i2_index_for(record), None, runner, tmp_path,
        always_not_logged,
    )

    conn = sqlite3.connect(":memory:")
    result_logger.create_table(conn)
    for _, row in pending_rows:
        result_logger.insert_row(conn, row)

    fetched = conn.execute("SELECT notebook_execution_id, outcome, run_id, round FROM repair_attempts").fetchall()
    assert fetched == [(8, "fixed", "i7-test-run", 1)]


# =============================================================================
# 13. SQLite connection handling: creation, insert, close, lock behaviour
# =============================================================================
#
# Real regression: a manual pilot run crashed with
# "sqlite3.OperationalError: database is locked" while another process was
# writing to the same default repair_attempts.sqlite. Root cause (confirmed
# by inspection, not assumed): main() opened its connection with
# sqlite3.connect(str(db_path)) - no explicit timeout beyond Python's 5s
# default - and, more importantly, called create_table()/the --overwrite
# DROP TABLE *before* entering the try/finally that closed the connection,
# so any exception in that window (a locked database very much included)
# leaked the open connection instead of closing it deterministically.
# open_repair_attempts_db()/_reset_repair_attempts_table() fix both: an
# explicit, generous busy-wait, and a connection lifecycle that is always
# inside a try/finally from the moment it exists.


def test_open_repair_attempts_db_creates_table_and_returns_usable_connection(tmp_path):
    conn = open_repair_attempts_db(tmp_path / "db.sqlite")
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(repair_attempts)").fetchall()}
        assert "notebook_execution_id" in columns
        assert "run_id" in columns
    finally:
        conn.close()


def test_open_repair_attempts_db_allows_insert_and_commits(tmp_path):
    db_path = tmp_path / "db.sqlite"
    conn = open_repair_attempts_db(db_path)
    try:
        record = sklearn_record()
        row = result_logger.build_repair_attempt_row(
            {"final_action": "install", "final_install_name": "scikit-learn", "final_version": None,
             "command": "python -m pip install scikit-learn", "final_rationale": "x", "retrieval_result": None,
             "run_id": "r1", "created_at": "2026-01-01T00:00:00+00:00", "notebook_execution_id": 8},
            record, None, None, 1,
        )
        row_id = result_logger.insert_row(conn, row)
        assert row_id is not None
    finally:
        conn.close()

    # committed, not just buffered in the closed connection - a fresh
    # connection to the same file sees it
    verify_conn = sqlite3.connect(str(db_path))
    try:
        count = verify_conn.execute("SELECT COUNT(*) FROM repair_attempts").fetchone()[0]
        assert count == 1
    finally:
        verify_conn.close()


def test_repeated_open_close_cycles_never_leave_the_database_locked(tmp_path):
    db_path = tmp_path / "db.sqlite"
    for i in range(5):
        conn = open_repair_attempts_db(db_path)
        try:
            row = result_logger.build_repair_attempt_row(
                {"final_action": "none", "final_install_name": None, "final_version": None, "command": None,
                 "final_rationale": None, "retrieval_result": None, "run_id": f"r{i}",
                 "created_at": "2026-01-01T00:00:00+00:00", "notebook_execution_id": i},
                {"failing_module": None, "refined_subtype": None}, None, None, 1,
            )
            result_logger.insert_row(conn, row)
        finally:
            conn.close()

    final_conn = sqlite3.connect(str(db_path), timeout=1)
    try:
        count = final_conn.execute("SELECT COUNT(*) FROM repair_attempts").fetchone()[0]
        assert count == 5
    finally:
        final_conn.close()


def test_two_sequential_orchestrator_style_runs_reuse_the_database_safely(tmp_path):
    """Simulates two separate CLI invocations against the same --database
    path, one after another (not concurrently) - the normal way a resumed
    or re-run pilot reuses a database."""
    db_path = tmp_path / "db.sqlite"

    conn1 = open_repair_attempts_db(db_path)
    try:
        row = result_logger.build_repair_attempt_row(
            {"final_action": "install", "final_install_name": "scikit-learn", "final_version": None,
             "command": "x", "final_rationale": "x", "retrieval_result": None,
             "run_id": "run-1", "created_at": "2026-01-01T00:00:00+00:00", "notebook_execution_id": 8},
            {"failing_module": "sklearn", "refined_subtype": "missing_package"}, None, None, 1,
        )
        result_logger.insert_row(conn1, row)
    finally:
        conn1.close()

    conn2 = open_repair_attempts_db(db_path)
    try:
        row = result_logger.build_repair_attempt_row(
            {"final_action": "install", "final_install_name": "pandas", "final_version": None,
             "command": "x", "final_rationale": "x", "retrieval_result": None,
             "run_id": "run-2", "created_at": "2026-01-01T00:00:01+00:00", "notebook_execution_id": 8},
            {"failing_module": "pandas", "refined_subtype": "missing_package"}, None, None, 1,
        )
        result_logger.insert_row(conn2, row)
        run_ids = [r[0] for r in conn2.execute("SELECT run_id FROM repair_attempts ORDER BY id").fetchall()]
    finally:
        conn2.close()

    assert run_ids == ["run-1", "run-2"]


def test_overwrite_drops_and_recreates_the_table(tmp_path):
    db_path = tmp_path / "db.sqlite"
    conn = open_repair_attempts_db(db_path)
    try:
        row = result_logger.build_repair_attempt_row(
            {"final_action": "none", "final_install_name": None, "final_version": None, "command": None,
             "final_rationale": None, "retrieval_result": None, "run_id": "old-run",
             "created_at": "2026-01-01T00:00:00+00:00", "notebook_execution_id": 1},
            {"failing_module": None, "refined_subtype": None}, None, None, 1,
        )
        result_logger.insert_row(conn, row)
        assert conn.execute("SELECT COUNT(*) FROM repair_attempts").fetchone()[0] == 1

        _reset_repair_attempts_table(conn, db_path)
        assert conn.execute("SELECT COUNT(*) FROM repair_attempts").fetchone()[0] == 0
    finally:
        conn.close()


def _hold_write_lock(db_path, hold_seconds, ready_event):
    """Acquire a real RESERVED write lock on db_path via a second
    connection and hold it for hold_seconds before releasing - simulates
    another process actively writing to the same database file. Signals
    `ready_event` once the lock is actually held, so the caller never races
    the lock's acquisition.

    Uses threading.Event().wait() rather than time.sleep() for the hold
    duration: this file's autouse _reset_pypi_cache fixture monkeypatches
    pypi_retriever.time.sleep - and since pypi_retriever does `import time`,
    that patches the *same* global time module every other caller in this
    process sees, silently turning a plain time.sleep() here into a no-op."""
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("BEGIN IMMEDIATE")
    ready_event.set()
    threading.Event().wait(hold_seconds)
    conn.rollback()
    conn.close()


def test_open_repair_attempts_db_waits_out_a_temporary_lock(tmp_path):
    """CREATE TABLE IF NOT EXISTS is a no-op (and needs no write lock) once
    the table already exists, so the lock must be acquired *before* the
    table is ever created - forcing open_repair_attempts_db()'s own first
    CREATE TABLE to be a real write that genuinely contends with the held
    RESERVED lock."""
    db_path = tmp_path / "db.sqlite"

    ready = threading.Event()
    holder = threading.Thread(target=_hold_write_lock, args=(db_path, 0.5, ready))
    holder.start()
    ready.wait(timeout=5)

    start = time.monotonic()
    conn = open_repair_attempts_db(db_path, timeout=5.0)
    elapsed = time.monotonic() - start
    conn.close()
    holder.join()

    # it waited for (roughly) the lock to clear rather than failing instantly
    assert elapsed >= 0.3


def test_open_repair_attempts_db_raises_clear_error_on_persistent_lock(tmp_path):
    db_path = tmp_path / "db.sqlite"

    ready = threading.Event()
    holder = threading.Thread(target=_hold_write_lock, args=(db_path, 2.0, ready))
    holder.start()
    ready.wait(timeout=5)

    try:
        with pytest.raises(RuntimeError) as excinfo:
            open_repair_attempts_db(db_path, timeout=0.2)
        message = str(excinfo.value)
        assert "busy/locked" in message
        assert "another pipeline process" in message
        assert str(db_path) in message
    finally:
        holder.join()


def test_reset_repair_attempts_table_raises_clear_error_on_persistent_lock(tmp_path):
    """_reset_repair_attempts_table()'s DROP TABLE + CREATE TABLE is always
    a real write (unlike a no-op CREATE TABLE IF NOT EXISTS on an existing
    table), so the table can safely already exist here. `conn`'s own busy
    timeout (set once, at connect time) must be shorter than the lock's
    hold duration for the wait to actually time out within the test."""
    db_path = tmp_path / "db.sqlite"
    conn = open_repair_attempts_db(db_path, timeout=0.2)

    ready = threading.Event()
    holder = threading.Thread(target=_hold_write_lock, args=(db_path, 2.0, ready))
    holder.start()
    ready.wait(timeout=5)

    try:
        with pytest.raises(RuntimeError) as excinfo:
            _reset_repair_attempts_table(conn, db_path)
        assert "busy/locked" in str(excinfo.value)
    finally:
        holder.join()
        conn.close()


def test_resume_skip_check_against_a_real_database_prevents_duplicate_rows(tmp_path):
    """The already_logged() SQL check used by main() against a real,
    on-disk database (not a fake callable) - confirms resume behaviour at
    the actual SQL level, not just via process_record()'s own already_logged
    parameter (covered separately in test_already_logged_round_is_skipped_and_not_duplicated)."""
    db_path = tmp_path / "db.sqlite"
    conn = open_repair_attempts_db(db_path)
    try:
        row = result_logger.build_repair_attempt_row(
            {"final_action": "install", "final_install_name": "scikit-learn", "final_version": None,
             "command": "x", "final_rationale": "x", "retrieval_result": None,
             "run_id": "resume-run", "created_at": "2026-01-01T00:00:00+00:00", "notebook_execution_id": 8},
            {"failing_module": "sklearn", "refined_subtype": "missing_package"}, None, None, 1,
        )
        result_logger.insert_row(conn, row)

        def already_logged(notebook_execution_id, run_id, round_number):
            cursor = conn.execute(
                "SELECT 1 FROM repair_attempts WHERE notebook_execution_id = ? AND run_id = ? AND round = ? LIMIT 1",
                (notebook_execution_id, run_id, round_number),
            )
            return cursor.fetchone() is not None

        assert already_logged(8, "resume-run", 1) is True
        assert already_logged(8, "resume-run", 2) is False
        assert already_logged(8, "a-different-run", 1) is False
    finally:
        conn.close()
