#!/usr/bin/env python3

"""Run the frozen PLLM-style baseline on the reserved evaluation split.

This runner is intentionally separate from the development CLI. It verifies
the pre-evaluation freeze before it reads a reserved record, writes one trace
per completed notebook, and never enables live PyPI access.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import fix_applicator
import pllm_style_baseline as baseline


ROOT = Path(__file__).resolve().parent.parent
EXPECTED_EVALUATION_RECORDS = 187


class EvaluationFreezeError(Exception):
    """A mismatch between a final-run input and the declared freeze."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise EvaluationFreezeError("expected a JSON object: {}".format(path))
    return value


def validate_freeze(
    freeze_path: Path, config_path: Path, fix_config_path: Path = None
) -> Dict[str, Any]:
    freeze = read_json(freeze_path)
    if freeze.get("status") != "pre_evaluation_frozen" or freeze.get("evaluation_processed"):
        raise EvaluationFreezeError("freeze manifest does not authorise a first evaluation run")

    integrity = freeze.get("integrity", {})
    cache_relative_path = freeze.get("frozen_pypi_cache", {}).get("path")
    if not isinstance(cache_relative_path, str):
        raise EvaluationFreezeError("freeze manifest has no frozen PyPI cache path")
    config = baseline.load_config(str(config_path))
    dataset_config = config.get("dataset", {})
    dataset_path = ROOT / dataset_config.get("i2_path", "data/context-classification/dependency_error_contexts.jsonl")
    split_path = ROOT / dataset_config.get("split_manifest_path", "data/dependency-errors/split_manifest.json")
    checks = {
        config_path: integrity.get("baseline_config_sha256"),
        ROOT / "scripts" / "pllm_style_baseline.py": integrity.get("baseline_script_sha256"),
        ROOT / cache_relative_path: freeze.get("frozen_pypi_cache", {}).get("sha256"),
        dataset_path: integrity.get("context_dataset_sha256"),
        split_path: integrity.get("split_manifest_sha256"),
        ROOT / "third_party" / "fse-aiware-python-dependencies" / "tools" / "pllm" / "helpers" / "ref_files" / "module_link.json": integrity.get("pllm_module_link_sha256"),
    }
    if fix_config_path is not None and integrity.get("fix_applicator_config_sha256"):
        checks[fix_config_path] = integrity["fix_applicator_config_sha256"]
    for path, expected in checks.items():
        if not expected or not path.is_file() or sha256(path) != expected:
            raise EvaluationFreezeError("frozen input mismatch: {}".format(path))

    if config.get("baseline", {}).get("pypi", {}).get("allow_network") is not False:
        raise EvaluationFreezeError("evaluation configuration must disable live PyPI access")
    return freeze


def evaluation_records(i2_path: Path, split_path: Path) -> List[Dict[str, Any]]:
    split_manifest = read_json(split_path)
    expected_ids = split_manifest.get("splits", {}).get("evaluation", [])
    if not isinstance(expected_ids, list) or len(expected_ids) != EXPECTED_EVALUATION_RECORDS:
        raise EvaluationFreezeError("evaluation split must contain exactly {} identifiers".format(EXPECTED_EVALUATION_RECORDS))

    records: List[Dict[str, Any]] = []
    with i2_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                if record.get("split") == "evaluation":
                    records.append(record)
    ids = [record.get("notebook_execution_id") for record in records]
    if ids != expected_ids:
        raise EvaluationFreezeError("evaluation records do not exactly match the split manifest")
    return records


def write_json(path: Path, value: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)


def parse_args(argv: List[str] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the frozen PLLM-style baseline on 187 evaluation records.")
    parser.add_argument("--freeze-manifest", required=True)
    parser.add_argument("--config", default="config/pllm_style_baseline.yaml")
    parser.add_argument("--fix-config", required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--dry-run", action="store_true", help="validate frozen inputs and the split without processing a notebook")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    freeze_path = (ROOT / args.freeze_manifest).resolve()
    config_path = (ROOT / args.config).resolve()
    fix_config_path = (ROOT / args.fix_config).resolve()
    freeze = validate_freeze(freeze_path, config_path, fix_config_path)
    config = baseline.load_config(str(config_path))
    i2_path = (ROOT / config["dataset"]["i2_path"]).resolve()
    split_path = (ROOT / config.get("dataset", {}).get(
        "split_manifest_path", "data/dependency-errors/split_manifest.json"
    )).resolve()
    records = evaluation_records(i2_path, split_path)
    if args.dry_run:
        print("dry_run=passed evaluation_records={}".format(len(records)))
        return

    run_id = args.run_id or "pllm-style-evaluation-{}".format(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    run_dir = ROOT / "data" / "evaluation" / run_id
    if run_dir.exists():
        raise EvaluationFreezeError("run directory already exists: {}".format(run_dir))
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True)
    trace_path = raw_dir / "pllm_style_traces.jsonl"
    manifest = {
        "run_id": run_id,
        "status": "running",
        "method": "pllm_style_notebook_v1",
        "freeze_manifest": str(freeze_path.relative_to(ROOT)),
        "freeze_manifest_sha256": sha256(freeze_path),
        "evaluation_records_expected": len(records),
        "baseline_runner_sha256": sha256(Path(__file__).resolve()),
        "freeze": freeze,
    }
    write_json(run_dir / "manifest.json", manifest)

    links = baseline.load_reference_module_links(config["baseline"]["reference_module_link"])
    fix_config = fix_applicator.load_fix_applicator_config(str(fix_config_path))
    i2_index = fix_applicator.load_i2_index(str(i2_path))
    repository_metadata_lookup = fix_applicator.default_repository_metadata_lookup(
        fix_config.get("upstream_docker_pipeline", {}).get("db_path")
    )
    completed = 0
    with trace_path.open("x", encoding="utf-8") as output:
        for record in records:
            trace = baseline.process_record(
                record, config, fix_config, i2_index, repository_metadata_lookup, links, run_id
            )
            output.write(json.dumps(trace, ensure_ascii=False) + "\n")
            output.flush()
            completed += 1
            print("status={}/{} notebook_execution_id={}".format(completed, len(records), record.get("notebook_execution_id")), flush=True)

    manifest["status"] = "completed"
    manifest["evaluation_records_completed"] = completed
    write_json(run_dir / "manifest.json", manifest)
    write_json(run_dir / "validation_report.json", {
        "status": "passed",
        "expected_records": len(records),
        "completed_records": completed,
        "trace_path": str(trace_path.relative_to(ROOT)),
    })


if __name__ == "__main__":
    try:
        main()
    except (EvaluationFreezeError, baseline.BaselineError, FileNotFoundError, json.JSONDecodeError, KeyError) as error:
        print("ERROR: {}".format(error), file=sys.stderr)
        raise SystemExit(1)
