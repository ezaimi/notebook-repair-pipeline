#!/usr/bin/env python3
"""Verify the Qwen V2 model-sensitivity run without contacting Qwen or Docker.

The check loads the repository .env file only to test whether the required
token is available. It never prints the token. It confirms that the Qwen run
will use the same evaluation split, frozen package evidence, and Docker
metadata database as the completed Gemma V2 matched run.
"""

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
I2_PATH = ROOT / "data/context-classification-v2/dependency_error_contexts.jsonl"
GEMMA_CONFIG = ROOT / "config/rag_repair.v2.shared-comparison.yaml"
QWEN_REPAIR_CONFIG = ROOT / "config/rag_repair.v2.qwen-shared-comparison.yaml"
QWEN_EXPLAINER_CONFIG = ROOT / "config/llm_explainer.v2.qwen.yaml"
QWEN_FIX_CONFIG = ROOT / "config/fix_applicator.v2.qwen.local.yaml"

EXPECTED_HASHES = {
    ROOT / "data/pllm-style-baseline/shared-comparison-pypi-cache.json":
        "e98b0ef696e48c910dccbd9153a448e8e37863fca83f9a5780cdeaff53a63538",
    ROOT / "data/pllm-style-baseline/v2-shared-comparison-wheel-import-index.json":
        "608861665412554ba92f7d673290b71eb7633444af0ab80a5189bd042325dc44",
    I2_PATH: "510e79649ac92dfb2c9e0b40aa0aa292fd335ee3e611457122a17671571394a4",
}


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError("{} must contain a YAML mapping".format(path))
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def count_evaluation_records(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip() and json.loads(line).get("split") == "evaluation":
                count += 1
    return count


def main() -> int:
    errors: List[str] = []
    load_dotenv(ROOT / ".env", override=False)

    for path, expected_hash in EXPECTED_HASHES.items():
        if not path.is_file():
            errors.append("missing required evidence file: {}".format(path))
        elif sha256(path) != expected_hash:
            errors.append("evidence hash changed: {}".format(path))

    if I2_PATH.is_file() and count_evaluation_records(I2_PATH) != 187:
        errors.append("V2 evaluation split is not exactly 187 records")

    try:
        gemma = load_yaml(GEMMA_CONFIG)
        qwen_repair = load_yaml(QWEN_REPAIR_CONFIG)
        qwen_explainer = load_yaml(QWEN_EXPLAINER_CONFIG)
        qwen_fix = load_yaml(QWEN_FIX_CONFIG)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        errors.append("could not load Qwen configuration: {}".format(exc))
        gemma = qwen_repair = qwen_explainer = qwen_fix = {}

    for key in ("runtime", "pypi_client", "resolver"):
        if qwen_repair.get(key) != gemma.get(key):
            errors.append("Qwen repair config differs from Gemma in {}".format(key))

    gemma_agent = gemma.get("repair_agent", {})
    qwen_agent = qwen_repair.get("repair_agent", {})
    for key in ("decision_policy", "prompt", "retry"):
        if qwen_agent.get(key) != gemma_agent.get(key):
            errors.append("Qwen repair config differs from Gemma in repair_agent.{}".format(key))

    if qwen_agent.get("provider") != "kiste":
        errors.append("Qwen repair provider must be kiste")
    if qwen_agent.get("kiste", {}).get("model") != "Qwen3.6-35B-A3B-MLX-8bit":
        errors.append("Qwen repair model is not Qwen3.6-35B-A3B-MLX-8bit")
    if qwen_explainer.get("provider") != "kiste":
        errors.append("Qwen explainer provider must be kiste")
    if qwen_explainer.get("models", {}).get("primary") != "Qwen3.6-35B-A3B-MLX-8bit":
        errors.append("Qwen explainer model is not Qwen3.6-35B-A3B-MLX-8bit")
    if qwen_explainer.get("generation", {}).get("max_tokens") != 4096:
        errors.append("Qwen explainer max_tokens must be the calibrated value 4096")
    if qwen_agent.get("kiste", {}).get("max_tokens") != 4096:
        errors.append("Qwen repair max_tokens must be the calibrated value 4096")

    if qwen_fix.get("dataset", {}).get("i2_path") != "data/context-classification-v2/dependency_error_contexts.jsonl":
        errors.append("Qwen FixApplicator config does not point at the V2 dataset")
    db_path = qwen_fix.get("upstream_docker_pipeline", {}).get("db_path")
    if not isinstance(db_path, str) or not Path(db_path).is_file():
        errors.append("local upstream metadata database is unavailable: {}".format(db_path))

    if importlib.util.find_spec("openai") is None:
        errors.append("Python package 'openai' is not installed")
    if not os.environ.get("KISTE_API_TOKEN"):
        errors.append("KISTE_API_TOKEN is not exported in this shell")

    if errors:
        print("Qwen V2 preflight FAILED:")
        for error in errors:
            print("- {}".format(error))
        return 1

    print("Qwen V2 preflight passed.")
    print("- evaluation records: 187")
    print("- package evidence: frozen and hash-verified")
    print("- provider/model: Kiste / Qwen3.6-35B-A3B-MLX-8bit")
    print("- no network request or model call was made by this preflight")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
