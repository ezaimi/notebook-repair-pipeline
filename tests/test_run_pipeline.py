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


# =============================================================================
# 12. Round-2 LLMExplainer: the newly exposed error gets its own explanation
# =============================================================================
#
# Round 2 re-enters the pipeline at reclassification, not at
# RAGRepairAgent. After the new error is reclassified into a round2_record
# it receives its OWN explanation (from that record, never from the
# original Round-1 record) before RAGRepairAgent runs on it. Explanation
# and repair stay separate objectives: an explanation failure must never
# block a repair-eligible Round-2 attempt. Exactly one explanation per
# executed round, bounded by the same two-round hard cap.


def explanation_json_for(failing_module, summary=None):
    """A schema-valid explanation whose content is tied to a specific
    failing module, so Round-1 and Round-2 explanations are distinguishable
    in the logged rows rather than coincidentally identical."""
    return json.dumps(
        {
            "summary": summary or "The notebook failed because '{}' is missing.".format(failing_module),
            "root_cause": "The notebook imports '{}', which is not installed.".format(failing_module),
            "evidence": ["error message names {}".format(failing_module)],
            "failing_module": failing_module,
            "explanation_confidence": "high",
            "limitations": "Only metadata is available.",
        }
    )


class ExplainerSpy:
    """Records every prompt LLMExplainer sends and answers each call from a
    scripted queue. A queue item is either a string (the raw response to
    return) or an exception instance (raised, so explain_one()'s own
    timeout/model-unavailable handling is exercised for real)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def __call__(self, **kwargs):
        self.prompts.append(kwargs["prompt"])
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item, {}


def _two_round_scipy_then_pandas(monkeypatch, explainer_responses):
    """Shared setup for a cumtrapz record whose Round-1 scipy pin exposes a
    new, repair-eligible pandas error, so Round 2 fires. Returns
    (explainer_spy, docker_runner, record)."""
    spy = ExplainerSpy(explainer_responses)
    monkeypatch.setattr(run_llm_explainer, "call_ollama", spy)
    mock_pypi(monkeypatch, "scipy", ["1.13.0", "1.13.1", "1.14.0"])

    def fake_repair_ollama(**kwargs):
        if "pandas" in kwargs["prompt"]:
            return ollama_repair_response("install", "pandas", None), {}
        return ollama_repair_response("pin_version", "scipy", "1.13.1"), {}

    monkeypatch.setattr(rag_repair_agent, "call_ollama", fake_repair_ollama)

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
    return spy, runner, cumtrapz_record()


def _run(record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config, max_rounds=2):
    return process_record(
        record, 0, "i7-r2-explain", max_rounds,
        explainer_config, explainer_template, "schemas/explanation.schema.json",
        repair_config, fix_config, i2_index_for(record), None, runner, tmp_path,
        always_not_logged,
    )


# --- A. Round-2 explanation is generated, exactly once, from the round2_record


def test_round2_generates_its_own_explanation_exactly_once(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    spy, runner, record = _two_round_scipy_then_pandas(
        monkeypatch, [explanation_json_for("scipy"), explanation_json_for("pandas")]
    )

    diagnostics, pending_rows = _run(record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)

    rounds = diagnostics["rounds"]
    assert len(rounds) == 2
    assert rounds[0]["round2_trigger"]["triggered"] is True

    # the new error was reclassified into a fresh record ...
    r2_record = rounds[0]["round2_trigger"]["round2_record"]
    assert r2_record["failing_module"] == "pandas"
    assert r2_record["refined_subtype"] == "missing_package"
    assert r2_record["context_status"] == "round2_reclassified_from_execution_outcome"

    # ... and LLMExplainer was called exactly twice: once per executed round
    assert len(spy.prompts) == 2

    # Round 2's explanation was generated from the round2_record, and is
    # tagged with its round so the relationship is unambiguous
    r2_expl = rounds[1]["explanation"]
    assert r2_expl["round"] == 2
    assert r2_expl["input"]["failing_module"] == "pandas"
    assert r2_expl["input"]["error_type"] == "ModuleNotFoundError"
    assert r2_expl["input"]["error_message"] == "No module named 'pandas'"
    assert r2_expl["input"]["context_status"] == "round2_reclassified_from_execution_outcome"
    assert rounds[1]["explanation_status"] == "success"

    # Round 1's own entry carries the original-failure explanation, tagged round 1
    assert rounds[0]["explanation"]["round"] == 1
    assert rounds[0]["explanation"]["input"]["failing_module"] == "scipy"
    assert rounds[0]["explanation_status"] == "success"


# --- B. the second explanation input is the NEW error context, not Round 1's


def test_round2_explanation_prompt_contains_new_error_not_original(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    spy, runner, record = _two_round_scipy_then_pandas(
        monkeypatch, [explanation_json_for("scipy"), explanation_json_for("pandas")]
    )

    diagnostics, _ = _run(record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)

    # The few-shot template embeds fixed examples (including a scipy/cumtrapz
    # one) in EVERY prompt, so compare only the record-specific section that
    # follows the "Now explain this input record." marker.
    marker = "Now explain this input record."
    assert marker in spy.prompts[0] and marker in spy.prompts[1]
    round1_input = spy.prompts[0].split(marker, 1)[1]
    round2_input = spy.prompts[1].split(marker, 1)[1]

    # Round 1's input section describes the original cumtrapz/scipy failure
    assert "cannot import name 'cumtrapz'" in round1_input
    assert "error_type: ImportError" in round1_input
    assert "root_cause_hint: version_or_api_incompatibility" in round1_input
    assert "failing_module: scipy" in round1_input

    # Round 2's input section describes the NEW pandas failure with its own
    # reclassification, and carries none of the original error's context
    assert "error_message: No module named 'pandas'" in round2_input
    assert "error_type: ModuleNotFoundError" in round2_input
    assert "refined_subtype: missing_package" in round2_input
    assert "failing_module: pandas" in round2_input
    assert "context_status: round2_reclassified_from_execution_outcome" in round2_input
    assert "cumtrapz" not in round2_input
    assert "version_or_api_incompatibility" not in round2_input
    assert "failing_module: scipy" not in round2_input

    # and the two explanation records are distinct objects with distinct inputs
    r1_expl, r2_expl = diagnostics["rounds"][0]["explanation"], diagnostics["rounds"][1]["explanation"]
    assert r1_expl is not r2_expl
    assert r1_expl["input"] != r2_expl["input"]
    assert r2_expl["input"]["root_cause_hint"] != r1_expl["input"]["root_cause_hint"]


# --- C. each repair_attempts row stores its own round's explanation


def test_round1_and_round2_rows_store_their_own_explanations(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    spy, runner, record = _two_round_scipy_then_pandas(
        monkeypatch, [explanation_json_for("scipy"), explanation_json_for("pandas")]
    )

    _, pending_rows = _run(record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)

    assert [r for r, _ in pending_rows] == [1, 2]
    row1, row2 = pending_rows[0][1], pending_rows[1][1]

    assert row1["explanation"] is not None
    assert row2["explanation"] is not None
    expl1, expl2 = json.loads(row1["explanation"]), json.loads(row2["explanation"])
    assert expl1["failing_module"] == "scipy"
    assert expl2["failing_module"] == "pandas"
    # Round 1's explanation was not copied into the Round 2 row
    assert row1["explanation"] != row2["explanation"]
    # and each row's classification columns match its own round's record
    assert row1["failing_module"] == "scipy" and row1["subtype"] == "wrong_version"
    assert row2["failing_module"] == "pandas" and row2["subtype"] == "missing_package"


# --- D. Round-2 row metadata comes from the Round-2 explanation record


def test_round2_row_llm_metadata_comes_from_round2_explanation(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    spy, runner, record = _two_round_scipy_then_pandas(
        monkeypatch, [explanation_json_for("scipy"), explanation_json_for("pandas")]
    )

    diagnostics, pending_rows = _run(record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)
    row2 = pending_rows[1][1]
    r2_expl = diagnostics["rounds"][1]["explanation"]

    # metadata populated (previously NULL for every Round-2 row) ...
    assert row2["llm_model"] == explainer_config["models"]["primary"]
    assert row2["prompt_strategy"] == explainer_config["prompt"]["strategy"]
    # ... and sourced from the Round-2 explanation's own llm block
    assert row2["llm_model"] == r2_expl["llm"]["llm_model"]
    assert row2["prompt_strategy"] == r2_expl["llm"]["prompt_strategy"]
    assert r2_expl["round"] == 2


def test_round2_row_metadata_is_not_inherited_from_round1_when_config_differs_per_round(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    """Guard against a stale-inheritance regression: if the Round-2
    explanation record were ever built from a different model than Round
    1's, the Round-2 row must reflect Round 2's own record, not Round 1's.
    Simulated by swapping the primary model on the second explain_record()
    call only."""
    spy, runner, record = _two_round_scipy_then_pandas(
        monkeypatch, [explanation_json_for("scipy"), explanation_json_for("pandas")]
    )

    original_explain_record = run_pipeline.explain_record
    calls = {"n": 0}

    def explain_record_with_per_round_model(rec, config, template, schema, run_id, index):
        calls["n"] += 1
        per_round_config = json.loads(json.dumps(config))
        if calls["n"] == 2:
            per_round_config["models"]["primary"] = "model-used-only-in-round-2"
        return original_explain_record(rec, per_round_config, template, schema, run_id, index)

    monkeypatch.setattr(run_pipeline, "explain_record", explain_record_with_per_round_model)

    diagnostics, pending_rows = _run(record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)
    row1, row2 = pending_rows[0][1], pending_rows[1][1]

    assert row1["llm_model"] == "gemma2:9b"
    assert row2["llm_model"] == "model-used-only-in-round-2"
    assert diagnostics["rounds"][1]["explanation"]["llm"]["llm_model"] == "model-used-only-in-round-2"


# --- E. Round-2 explanation failure does not block the repair


def test_round2_explanation_timeout_does_not_block_repair(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    spy, runner, record = _two_round_scipy_then_pandas(
        monkeypatch, [explanation_json_for("scipy"), TimeoutError("explainer timed out")]
    )

    diagnostics, pending_rows = _run(record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)
    rounds = diagnostics["rounds"]
    assert len(rounds) == 2

    # the failure is captured, not raised, and attributed to Round 2
    assert rounds[1]["explanation_status"] == "failed"
    assert rounds[1]["explanation"]["explanation_result"]["failure_category"] == "timeout"
    assert rounds[1]["explanation"]["round"] == 2
    # Round 1's explanation is untouched
    assert rounds[0]["explanation_status"] == "success"

    # RAGRepairAgent still ran on the Round-2 record and proposed a grounded fix ...
    assert rounds[1]["i4_result"]["status"] == "success"
    assert rounds[1]["i4_result"]["final_install_name"] == "pandas"
    # ... FixApplicator still ran it ...
    assert rounds[1]["i5_result"]["status"] == "completed"
    assert rounds[1]["i5_result"]["outcome"] == "fixed"
    # ... and ResultLogger still gets a Round-2 row for the attempt
    assert [r for r, _ in pending_rows] == [1, 2]
    row2 = pending_rows[1][1]
    assert row2["install_name"] == "pandas"
    assert row2["outcome"] == "fixed"
    assert row2["explanation"] is None  # no valid explanation to store
    assert row2["llm_model"] == "gemma2:9b"  # but the attempted model is recorded


def test_round2_explanation_schema_failure_does_not_block_repair(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    malformed = json.dumps({"summary": "missing every other required field"})
    spy, runner, record = _two_round_scipy_then_pandas(monkeypatch, [explanation_json_for("scipy"), malformed])

    diagnostics, pending_rows = _run(record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)
    rounds = diagnostics["rounds"]

    assert rounds[1]["explanation_status"] == "failed"
    assert rounds[1]["explanation"]["explanation_result"]["validation_errors"]
    assert rounds[1]["i4_result"]["final_install_name"] == "pandas"
    assert rounds[1]["i5_result"]["outcome"] == "fixed"
    assert pending_rows[1][1]["explanation"] is None
    assert pending_rows[1][1]["install_name"] == "pandas"


def test_round2_explanation_unexpected_exception_is_caught_and_repair_still_runs(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    """explain_round_record()'s last-resort guard: even an exception that
    explain_one()/explain_record() do not anticipate is turned into a
    failed explanation for Round 2 rather than aborting the round."""
    spy, runner, record = _two_round_scipy_then_pandas(monkeypatch, [explanation_json_for("scipy")])

    original_explain_record = run_pipeline.explain_record
    calls = {"n": 0}

    def explain_record_that_explodes_on_round2(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("unexpected explainer crash")
        return original_explain_record(*args, **kwargs)

    monkeypatch.setattr(run_pipeline, "explain_record", explain_record_that_explodes_on_round2)

    diagnostics, pending_rows = _run(record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)
    rounds = diagnostics["rounds"]

    assert len(rounds) == 2
    assert rounds[1]["explanation_status"] == "failed"
    assert rounds[1]["explanation"]["explanation_result"]["failure_category"] == "runtime_error"
    assert "unexpected explainer crash" in rounds[1]["explanation"]["explanation_result"]["error"]
    assert rounds[1]["i5_result"]["outcome"] == "fixed"
    assert len(pending_rows) == 2


# --- F. no Round 2 means no second explanation


def test_round1_fixed_means_exactly_one_explanation(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    spy = ExplainerSpy([explanation_json_for("sklearn")])
    monkeypatch.setattr(run_llm_explainer, "call_ollama", spy)
    mock_pypi(monkeypatch, "scikit-learn", ["1.7.2"])
    monkeypatch.setattr(
        rag_repair_agent, "call_ollama",
        lambda **kwargs: (ollama_repair_response("install", "scikit-learn", None), {}),
    )
    runner = SequencedDockerRunner(run_outcomes=[("fixed", "FIX_INSTALL_SUCCESS")])

    diagnostics, _ = _run(sklearn_record(), runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)

    assert diagnostics["rounds"][0]["i5_result"]["outcome"] == "fixed"
    assert len(spy.prompts) == 1


def test_same_error_repeated_means_exactly_one_explanation(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    spy = ExplainerSpy([explanation_json_for("sklearn")])
    monkeypatch.setattr(run_llm_explainer, "call_ollama", spy)
    mock_pypi(monkeypatch, "scikit-learn", ["1.7.2"])
    monkeypatch.setattr(
        rag_repair_agent, "call_ollama",
        lambda **kwargs: (ollama_repair_response("install", "scikit-learn", None), {}),
    )
    # the same sklearn error comes back after the fix -> same_as_original_error
    runner = SequencedDockerRunner(
        run_outcomes=[(("ModuleNotFoundError", "No module named 'sklearn'"), "FIX_INSTALL_SUCCESS")]
    )

    diagnostics, _ = _run(sklearn_record(), runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)

    assert diagnostics["rounds"][0]["round2_trigger"]["triggered"] is False
    assert diagnostics["rounds"][0]["round2_trigger"]["reason"] == "same_as_original_error"
    assert len(diagnostics["rounds"]) == 1
    assert len(spy.prompts) == 1


def _sklearn_round1_exposing(monkeypatch, new_error, explainer_responses):
    """Shared setup: an sklearn record whose Round-1 install succeeds but
    re-execution exposes `new_error`. Spies on run_repair_agent() itself so
    a test can assert exactly how many times RAGRepairAgent was entered."""
    spy = ExplainerSpy(explainer_responses)
    monkeypatch.setattr(run_llm_explainer, "call_ollama", spy)
    mock_pypi(monkeypatch, "scikit-learn", ["1.7.2"])
    monkeypatch.setattr(
        rag_repair_agent, "call_ollama",
        lambda **kwargs: (ollama_repair_response("install", "scikit-learn", None), {}),
    )

    original_run_repair_agent = rag_repair_agent.run_repair_agent
    repair_calls = []

    def spying_run_repair_agent(record, config, run_id=None):
        repair_calls.append(record["failing_module"])
        return original_run_repair_agent(record, config, run_id=run_id)

    monkeypatch.setattr(rag_repair_agent, "run_repair_agent", spying_run_repair_agent)

    runner = SequencedDockerRunner(run_outcomes=[(new_error, "FIX_INSTALL_SUCCESS")])
    return spy, repair_calls, runner, sklearn_record()


@pytest.mark.parametrize(
    "new_error, expected_reason_prefix, expected_subtype",
    [
        # newly exposed system library: reclassified as excluded -> not repair-eligible
        (("ImportError", "libxcb.so.1: cannot open shared object file: No such file or directory"),
         "new_error_not_repair_eligible", "system_library"),
        # newly exposed ambiguous local module: reclassified as mapping_unknown
        (("ModuleNotFoundError", "No module named 'utils'"),
         "new_error_not_repair_eligible", "mapping_unknown"),
    ],
)
def test_non_repairable_new_error_is_explained_but_never_repaired(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config,
    new_error, expected_reason_prefix, expected_subtype,
):
    """Explanation scope is wider than repair scope, as in Round 1. A newly
    exposed error that reclassifies as system_library or mapping_unknown
    still receives its own explanation, generated after reclassification and
    before the eligibility decision. Eligibility then stops Round 2, so
    RAGRepairAgent and FixApplicator never run on it and no Round-2
    repair_attempts row is written. The explanation is preserved in the
    trace on the trigger dict, next to the round2_record it explains, and
    is deliberately not a rounds[] entry (every trace consumer reads a
    round == 2 entry as an executed Round 2)."""
    spy, repair_calls, runner, record = _sklearn_round1_exposing(
        monkeypatch, new_error, [explanation_json_for("sklearn"), explanation_json_for(expected_subtype)]
    )

    diagnostics, pending_rows = _run(record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)

    trigger = diagnostics["rounds"][0]["round2_trigger"]
    assert trigger["triggered"] is False
    assert trigger["reason"].startswith(expected_reason_prefix)
    assert trigger["round2_record"]["refined_subtype"] == expected_subtype

    # the new error WAS explained: a second LLMExplainer call, from the
    # reclassified record, tagged as the Round-2 explanation ...
    assert len(spy.prompts) == 2
    assert "explanation" in trigger
    assert trigger["explanation_status"] == "success"
    assert trigger["explanation"]["round"] == 2
    assert trigger["explanation"]["input"]["error_type"] == new_error[0]
    assert trigger["explanation"]["input"]["error_message"] == new_error[1]
    assert trigger["explanation"]["input"]["refined_subtype"] == expected_subtype
    assert trigger["explanation"]["input"]["scope_status"] == "excluded"
    assert trigger["explanation"]["input"]["context_status"] == "round2_reclassified_from_execution_outcome"
    round2_input = spy.prompts[1].split("Now explain this input record.", 1)[1]
    assert new_error[1] in round2_input
    assert "failing_module: sklearn" not in round2_input

    # ... but RAGRepairAgent was entered exactly once (Round 1, sklearn),
    # never for the new error, and FixApplicator ran only Round 1
    assert repair_calls == ["sklearn"]
    assert len([c for c in runner.calls if c[:2] == ["docker", "run"]]) == 1

    # no executed Round 2: no rounds[] entry with round 2, no Round-2 row
    assert len(diagnostics["rounds"]) == 1
    assert [r for r, _ in pending_rows] == [1]
    # so under the one-row-per-executed-round contract the Round-2
    # explanation exists in the trace only, and the Round-1 row keeps
    # Round 1's own explanation
    assert json.loads(pending_rows[0][1]["explanation"])["failing_module"] == "sklearn"


def test_non_repairable_new_error_explanation_failure_is_captured_not_raised(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    """Non-blocking holds on the non-repairable path too: a failed Round-2
    explanation is recorded on the trigger and the record still finishes
    cleanly with its Round-1 row."""
    new_error = ("ImportError", "libxcb.so.1: cannot open shared object file: No such file or directory")
    spy, repair_calls, runner, record = _sklearn_round1_exposing(
        monkeypatch, new_error, [explanation_json_for("sklearn"), TimeoutError("explainer timed out")]
    )

    diagnostics, pending_rows = _run(record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)

    trigger = diagnostics["rounds"][0]["round2_trigger"]
    assert trigger["triggered"] is False
    assert trigger["explanation_status"] == "failed"
    assert trigger["explanation"]["explanation_result"]["failure_category"] == "timeout"
    assert trigger["explanation"]["round"] == 2
    assert repair_calls == ["sklearn"]
    assert len(diagnostics["rounds"]) == 1
    assert len(pending_rows) == 1
    assert diagnostics["rounds"][0]["explanation_status"] == "success"


def test_repair_eligible_new_error_explanation_is_on_trigger_and_on_round2_entry(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    """For a repair-eligible new error the single Round-2 explanation is
    reachable both where every reclassified error's explanation lives
    (round2_trigger.explanation) and on the executed Round-2 entry, as the
    same record - and it reaches the Round-2 repair_attempts row."""
    spy, runner, record = _two_round_scipy_then_pandas(
        monkeypatch, [explanation_json_for("scipy"), explanation_json_for("pandas")]
    )

    diagnostics, pending_rows = _run(record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)

    trigger = diagnostics["rounds"][0]["round2_trigger"]
    assert trigger["triggered"] is True
    assert trigger["explanation"] is diagnostics["rounds"][1]["explanation"]
    assert trigger["explanation"]["round"] == 2
    assert trigger["explanation"]["input"]["failing_module"] == "pandas"
    assert len(spy.prompts) == 2
    assert json.loads(pending_rows[1][1]["explanation"])["failing_module"] == "pandas"


def test_no_new_error_means_no_reclassification_and_no_second_explanation(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    """When Round 1 ends still_failing on the SAME error, nothing new was
    exposed: no round2_record is built, so there is nothing to explain."""
    spy, repair_calls, runner, record = _sklearn_round1_exposing(
        monkeypatch, ("ModuleNotFoundError", "No module named 'sklearn'"), [explanation_json_for("sklearn")]
    )

    diagnostics, pending_rows = _run(record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)

    trigger = diagnostics["rounds"][0]["round2_trigger"]
    assert trigger["reason"] == "same_as_original_error"
    assert "round2_record" not in trigger
    assert "explanation" not in trigger
    assert len(spy.prompts) == 1
    assert repair_calls == ["sklearn"]
    assert len(pending_rows) == 1


def test_max_rounds_1_never_reclassifies_or_explains_a_new_error(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    """With a one-round budget no Round 2 can ever be considered, so the new
    error is neither reclassified nor explained - the explanation of a
    Round-2 error exists only where a Round 2 could follow."""
    spy, repair_calls, runner, record = _sklearn_round1_exposing(
        monkeypatch, ("ModuleNotFoundError", "No module named 'pandas'"), [explanation_json_for("sklearn")]
    )

    diagnostics, pending_rows = _run(
        record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config, max_rounds=1
    )

    assert len(diagnostics["rounds"]) == 1
    assert "round2_trigger" not in diagnostics["rounds"][0]
    assert len(spy.prompts) == 1
    assert repair_calls == ["sklearn"]
    assert len(pending_rows) == 1



# --- G. the hard cap bounds explanations too: never a third


def test_hard_cap_yields_at_most_two_explanations_even_if_errors_keep_appearing(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    # Every round exposes yet another eligible error; without the cap this
    # would recurse indefinitely. The queue holds a third explanation on
    # purpose - it must never be consumed.
    spy, runner, record = _two_round_scipy_then_pandas(
        monkeypatch,
        [explanation_json_for("scipy"), explanation_json_for("pandas"), explanation_json_for("never-explained")],
    )
    # Round 2's re-execution exposes a THIRD eligible error instead of fixing
    runner.run_outcomes[1] = (("ModuleNotFoundError", "No module named 'numpy'"), "FIX_INSTALL_SUCCESS")

    diagnostics, pending_rows = _run(
        record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config, max_rounds=5
    )

    assert len(diagnostics["rounds"]) == 2
    assert diagnostics["rounds"][1]["i5_result"]["outcome"] == "still_failing"
    assert diagnostics["rounds"][1]["i5_result"]["new_error_message"] == "No module named 'numpy'"
    assert "round2_trigger" not in diagnostics["rounds"][1]  # no evaluation of a third round
    assert len(pending_rows) == 2
    assert len(spy.prompts) == 2
    assert len(spy.responses) == 1  # the third scripted response was never used


def test_each_round_is_explained_exactly_once_not_repeatedly(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    spy, runner, record = _two_round_scipy_then_pandas(
        monkeypatch, [explanation_json_for("scipy"), explanation_json_for("pandas")]
    )

    diagnostics, _ = _run(record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)

    rounds_explained = [r["explanation"]["round"] for r in diagnostics["rounds"]]
    assert rounds_explained == [1, 2]
    assert len(spy.prompts) == 2


def test_already_logged_round2_is_not_re_explained(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    """Resume semantics: if Round 2 is already in the database, the round is
    skipped before its explanation would be generated - no wasted LLM call."""
    spy, runner, record = _two_round_scipy_then_pandas(
        monkeypatch, [explanation_json_for("scipy"), explanation_json_for("pandas")]
    )

    def round2_already_logged(notebook_execution_id, run_id, round_number):
        return round_number == 2

    diagnostics, pending_rows = process_record(
        record, 0, "i7-r2-explain", 2,
        explainer_config, explainer_template, "schemas/explanation.schema.json",
        repair_config, fix_config, i2_index_for(record), None, runner, tmp_path,
        round2_already_logged,
    )

    assert diagnostics["rounds"][1]["status"] == "skipped_already_logged"
    assert len(pending_rows) == 1
    assert len(spy.prompts) == 1


# --- H. Round-1 behaviour is unchanged


def test_one_round_record_behaviour_is_unchanged(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    spy = ExplainerSpy([explanation_json_for("sklearn")])
    monkeypatch.setattr(run_llm_explainer, "call_ollama", spy)
    mock_pypi(monkeypatch, "scikit-learn", ["1.7.2"])
    monkeypatch.setattr(
        rag_repair_agent, "call_ollama",
        lambda **kwargs: (ollama_repair_response("install", "scikit-learn", None), {}),
    )
    runner = SequencedDockerRunner(run_outcomes=[("fixed", "FIX_INSTALL_SUCCESS")])

    diagnostics, pending_rows = _run(sklearn_record(), runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)

    # one explanation, of the original failure, still at the top level for
    # every pre-existing consumer of the trace
    assert len(spy.prompts) == 1
    assert diagnostics["explanation_status"] == "success"
    assert diagnostics["explanation"]["input"]["failing_module"] == "sklearn"
    assert diagnostics["explanation"]["round"] == 1
    # and mirrored into Round 1's own entry, as the same record
    assert diagnostics["rounds"][0]["explanation"] is diagnostics["explanation"]
    # same repair flow and same single logged row as before
    assert diagnostics["rounds"][0]["i4_result"]["final_install_name"] == "scikit-learn"
    assert diagnostics["rounds"][0]["i5_result"]["outcome"] == "fixed"
    assert len(pending_rows) == 1
    row1 = pending_rows[0][1]
    assert row1["round"] == 1
    assert json.loads(row1["explanation"])["failing_module"] == "sklearn"
    assert row1["llm_model"] == "gemma2:9b"


def test_excluded_record_round_entry_carries_its_explanation(
    monkeypatch, explainer_config, explainer_template, repair_config, fix_config
):
    """The excluded-record path (explained, never repaired) now also exposes
    the explanation on its round entry, consistently with executed rounds."""
    spy = ExplainerSpy([explanation_json_for("libxcb.so.1")])
    monkeypatch.setattr(run_llm_explainer, "call_ollama", spy)

    record = system_library_record()
    diagnostics, pending_rows = process_record(
        record, 0, "i7-r2-explain", 2,
        explainer_config, explainer_template, "schemas/explanation.schema.json",
        repair_config, fix_config, i2_index_for(record), None, RefusingRunner(), None,
        always_not_logged,
    )

    assert diagnostics["rounds"][0]["status"] == "excluded"
    assert diagnostics["rounds"][0]["explanation"] is diagnostics["explanation"]
    assert diagnostics["rounds"][0]["explanation_status"] == "success"
    assert len(spy.prompts) == 1
    assert len(pending_rows) == 1


def test_round2_explanation_round_trips_through_result_logger_schema(
    monkeypatch, tmp_path, explainer_config, explainer_template, repair_config, fix_config
):
    """End to end against a real SQLite repair_attempts table: the existing
    schema stores both rounds' explanations with no migration."""
    spy, runner, record = _two_round_scipy_then_pandas(
        monkeypatch, [explanation_json_for("scipy"), explanation_json_for("pandas")]
    )
    _, pending_rows = _run(record, runner, tmp_path, explainer_config, explainer_template, repair_config, fix_config)

    conn = open_repair_attempts_db(tmp_path / "db.sqlite")
    try:
        for _, row in pending_rows:
            result_logger.insert_row(conn, row)
        stored = conn.execute(
            "SELECT round, explanation, llm_model, prompt_strategy, failing_module, subtype "
            "FROM repair_attempts WHERE notebook_execution_id = ? ORDER BY round",
            (record["notebook_execution_id"],),
        ).fetchall()
    finally:
        conn.close()

    assert [s[0] for s in stored] == [1, 2]
    assert json.loads(stored[0][1])["failing_module"] == "scipy"
    assert json.loads(stored[1][1])["failing_module"] == "pandas"
    assert stored[1][2] == "gemma2:9b" and stored[1][3] == "few_shot"
    assert stored[1][4] == "pandas" and stored[1][5] == "missing_package"
