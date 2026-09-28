import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_pllm_style_evaluation as runner


def test_evaluation_records_require_exact_split_manifest(tmp_path):
    i2_path = tmp_path / "records.jsonl"
    i2_path.write_text("\n".join(json.dumps({
        "split": "evaluation", "notebook_execution_id": identifier
    }) for identifier in range(1, 188)) + "\n", encoding="utf-8")
    split_path = tmp_path / "split.json"
    split_path.write_text(json.dumps({"splits": {"evaluation": list(range(1, 188))}}), encoding="utf-8")

    records = runner.evaluation_records(i2_path, split_path)
    assert len(records) == 187

    split_path.write_text(json.dumps({"splits": {"evaluation": list(range(2, 189))}}), encoding="utf-8")
    with pytest.raises(runner.EvaluationFreezeError, match="do not exactly match"):
        runner.evaluation_records(i2_path, split_path)


def test_validate_freeze_rejects_live_network_configuration(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("baseline:\n  pypi:\n    allow_network: true\n", encoding="utf-8")
    cache_path = tmp_path / "data" / "pllm-style-baseline" / "frozen-pypi-cache.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("{}", encoding="utf-8")
    data_path = tmp_path / "data" / "context-classification" / "dependency_error_contexts.jsonl"
    data_path.parent.mkdir(parents=True)
    data_path.write_text("", encoding="utf-8")
    split_path = tmp_path / "data" / "dependency-errors" / "split_manifest.json"
    split_path.parent.mkdir(parents=True)
    split_path.write_text("{}", encoding="utf-8")
    link_path = tmp_path / "third_party" / "fse-aiware-python-dependencies" / "tools" / "pllm" / "helpers" / "ref_files" / "module_link.json"
    link_path.parent.mkdir(parents=True)
    link_path.write_text("{}", encoding="utf-8")
    baseline_path = tmp_path / "scripts" / "pllm_style_baseline.py"
    baseline_path.parent.mkdir(parents=True)
    baseline_path.write_text("# frozen", encoding="utf-8")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.baseline, "load_config", lambda _path: {"baseline": {"pypi": {"allow_network": True}}})

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    freeze = {
        "status": "pre_evaluation_frozen",
        "evaluation_processed": False,
        "frozen_pypi_cache": {
            "path": "data/pllm-style-baseline/frozen-pypi-cache.json",
            "sha256": digest(cache_path),
        },
        "integrity": {
            "baseline_config_sha256": digest(config_path),
            "baseline_script_sha256": digest(baseline_path),
            "context_dataset_sha256": digest(data_path),
            "split_manifest_sha256": digest(split_path),
            "pllm_module_link_sha256": digest(link_path),
        },
    }
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(json.dumps(freeze), encoding="utf-8")

    with pytest.raises(runner.EvaluationFreezeError, match="disable live PyPI"):
        runner.validate_freeze(freeze_path, config_path)
