#!/usr/bin/env python3

"""Notebook-adapted PLLM-style dependency-repair baseline.

This is not the original PLLM implementation. It retains its central loop:
an LLM proposes a dependency change from PyPI evidence, the notebook is
executed in isolation, and the resulting dependency error can feed one
further proposal. The adapter uses FixApplicator only for FAIR Jupyter's
repository-aware Docker execution; it does not use this thesis's static
package mapping, error-subtype gate, JSON-schema gate, or grounding gate.

The CLI accepts the development split only until a separate, frozen
evaluation entry point is added under docs/pllm_style_baseline_protocol.md.
"""

import argparse
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

import fix_applicator
from prepare_dependency_dataset import extract_failing_module


ROOT = Path(__file__).resolve().parent.parent
SAFE_PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
DEPENDENCY_ERROR_TYPES = {"ModuleNotFoundError", "ImportError"}


class BaselineError(Exception):
    """A controlled baseline failure with a message safe to include in logs."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_run_id(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return "pllm-style-dev-{}".format(now.strftime("%Y%m%dT%H%M%SZ"))


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_records(path: str, split: str = "dev") -> List[Dict[str, Any]]:
    if split != "dev":
        raise BaselineError("the PLLM-style baseline is development-split only")
    records: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                if record.get("split") == "dev":
                    records.append(record)
    return records


def load_reference_module_links(path: str) -> Dict[str, Dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        raise BaselineError(
            "PLLM reference module-link table is unavailable: {}. "
            "Restore the checked third_party checkout before running the baseline.".format(source)
        )
    with source.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return {str(key).lower(): value for key, value in raw.items() if isinstance(value, dict)}


def distribution_from_reference(import_name: Optional[str], links: Dict[str, Dict[str, Any]]) -> Optional[str]:
    if not import_name:
        return None
    root_import = import_name.split(".", 1)[0].strip().lower()
    if not root_import:
        return None
    entry = links.get(root_import)
    if entry and isinstance(entry.get("ref"), str):
        return entry["ref"]
    return root_import


def reference_distributions(links: Dict[str, Dict[str, Any]]) -> List[str]:
    """Return every candidate that PLLM's module-link table can produce.

    Entries with an explicit ``ref`` use that distribution; the remaining
    entries fall back to the import root in ``distribution_from_reference``.
    Both forms must be present in a frozen cache, otherwise an offline run
    would convert a known PLLM candidate into an artificial abstention.
    """
    distributions = set()
    for import_name, entry in links.items():
        candidate = entry.get("ref") if isinstance(entry.get("ref"), str) else import_name.split(".", 1)[0]
        candidate = candidate.strip()
        if SAFE_PACKAGE_RE.fullmatch(candidate):
            distributions.add(candidate)
    return sorted(distributions, key=str.lower)


def precache_reference_distributions(
    links: Dict[str, Dict[str, Any]], config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Fetch the fixed evidence universe before a final run.

    This preflight deliberately uses only PLLM's checked reference table and
    does not inspect or execute a reserved evaluation notebook.
    """
    baseline_config = config.get("baseline", {})
    runtime_python_version = str(baseline_config.get("runtime_python_version", "3.10"))
    pypi_config = baseline_config.get("pypi", {})
    return [
        fetch_pypi_project(distribution, pypi_config, runtime_python_version)
        for distribution in reference_distributions(links)
    ]


def record_distributions(i2_path: str, split: str, links: Dict[str, Dict[str, Any]]) -> List[str]:
    """Collect the baseline's deterministic initial PyPI lookups for one split.

    Imports absent from PLLM's module-link table fall back to their import
    root at run time. Pre-caching these known input roots is not model tuning:
    it prevents an offline cache from changing the method before the LLM has
    made any decision.
    """
    distributions = set()
    with open(i2_path, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                if record.get("split") == split:
                    distribution = distribution_from_reference(record.get("failing_module"), links)
                    if distribution and SAFE_PACKAGE_RE.fullmatch(distribution):
                        distributions.add(distribution)
    return sorted(distributions, key=str.lower)


def precache_distributions(
    distributions: List[str], config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    baseline_config = config.get("baseline", {})
    runtime_python_version = str(baseline_config.get("runtime_python_version", "3.10"))
    pypi_config = baseline_config.get("pypi", {})
    return [
        fetch_pypi_project(distribution, pypi_config, runtime_python_version)
        for distribution in distributions
    ]


def _load_cache(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise BaselineError("PyPI cache must be a JSON object: {}".format(path))
    return value


def _write_cache(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)


def fetch_pypi_project(
    distribution: str,
    pypi_config: Dict[str, Any],
    runtime_python_version: str,
    *,
    request: Callable[..., Any] = urllib.request.urlopen,
) -> Dict[str, Any]:
    """Fetch one distribution's public PyPI JSON metadata with a local cache.

    The cache is writable during development. For a final comparison,
    ``allow_network`` must be false and the cache must be frozen before either
    method runs, as required by the protocol.
    """
    if not SAFE_PACKAGE_RE.fullmatch(distribution):
        return {"status": "invalid_distribution", "distribution": distribution, "versions": []}

    cache_path = ROOT / pypi_config.get("cache_path", "data/pllm-style-baseline/pypi_cache.json")
    # A frozen cache can be tens of megabytes. Keep one in-memory copy for a
    # run so every repair round sees exactly the same evidence snapshot
    # without repeatedly reading the file.
    cache = pypi_config.get("_runtime_cache")
    if not isinstance(cache, dict):
        cache = _load_cache(cache_path)
        pypi_config["_runtime_cache"] = cache
    cache_key = distribution.lower()
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and isinstance(cached.get("payload"), dict):
        return _pypi_result(distribution, cached["payload"], source="cache", runtime_python_version=runtime_python_version)
    if isinstance(cached, dict) and isinstance(cached.get("result"), dict):
        cached_result = dict(cached["result"])
        cached_result["source"] = "cache"
        return cached_result

    if not pypi_config.get("allow_network", False):
        return {"status": "cache_miss", "distribution": distribution, "versions": []}

    base_url = str(pypi_config.get("base_url", "https://pypi.org/pypi")).rstrip("/")
    url = "{}/{}/json".format(base_url, distribution)
    try:
        with request(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            result = {"status": "not_found", "distribution": distribution, "versions": []}
            cache[cache_key] = {"retrieved_at": utc_now(), "result": result}
            _write_cache(cache_path, cache)
            return result
        return {"status": "http_error", "distribution": distribution, "versions": [], "error": str(error)}
    except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
        return {"status": "network_error", "distribution": distribution, "versions": [], "error": str(error)}
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return {"status": "invalid_response", "distribution": distribution, "versions": [], "error": str(error)}

    cache[cache_key] = {"retrieved_at": utc_now(), "payload": payload}
    _write_cache(cache_path, cache)
    return _pypi_result(distribution, payload, source="network", runtime_python_version=runtime_python_version)


def _supports_runtime(file_info: Dict[str, Any], runtime_python_version: str) -> bool:
    requires_python = file_info.get("requires_python")
    if not requires_python:
        return True
    try:
        return Version(runtime_python_version) in SpecifierSet(requires_python)
    except (InvalidSpecifier, InvalidVersion):
        return False


def _version_key(version: str) -> Version:
    try:
        return Version(version)
    except InvalidVersion:
        return Version("0")


def _pypi_result(
    distribution: str,
    payload: Dict[str, Any],
    source: str,
    runtime_python_version: str,
) -> Dict[str, Any]:
    releases = payload.get("releases") or {}
    versions = []
    for version, files in releases.items():
        usable_files = [
            file_info for file_info in files
            if not file_info.get("yanked", False) and _supports_runtime(file_info, runtime_python_version)
        ]
        if usable_files:
            versions.append(version)
    versions.sort(key=_version_key)
    return {
        "status": "resolved",
        "distribution": distribution,
        "versions": versions,
        "latest_version": versions[-1] if versions else None,
        "runtime_python_version": runtime_python_version,
        "source": source,
    }


def build_prompt(
    record: Dict[str, Any],
    distribution: Optional[str],
    pypi_result: Dict[str, Any],
    prior_rounds: List[Dict[str, Any]],
    version_limit: int,
) -> str:
    versions = pypi_result.get("versions") or []
    visible_versions = versions[-version_limit:] if version_limit > 0 else versions
    feedback = "None; this is the first proposal."
    if prior_rounds:
        latest = prior_rounds[-1]
        feedback = "Previous command: {}\nExecution feedback: {}: {}".format(
            latest.get("command") or "none",
            latest.get("new_error_type") or latest.get("outcome") or "unknown",
            latest.get("new_error_message") or "no message recorded",
        )

    return """You are repairing one dependency failure in a Jupyter notebook.
The notebook will be executed in its original repository Docker environment.
Do not change the Python version or modify notebook source code.

Failure type: {error_type}
Failure message: {error_message}
Failing import: {failing_module}
Reference PLLM module-to-distribution candidate: {distribution}
PyPI lookup status: {pypi_status}
PyPI latest version: {latest_version}
Available non-yanked versions (newest subset): {versions}
{feedback}

Choose exactly one Python distribution and, only if necessary, one version.
The distribution must be a real PyPI project. Return JSON only:
{{"package": "distribution-name", "version": "version-or-null", "rationale": "short reason"}}
""".format(
        error_type=record.get("error_type") or "unknown",
        error_message=record.get("error_message") or "unknown",
        failing_module=record.get("failing_module") or "unknown",
        distribution=distribution or "unknown",
        pypi_status=pypi_result.get("status"),
        latest_version=pypi_result.get("latest_version") or "unknown",
        versions=", ".join(visible_versions) if visible_versions else "none",
        feedback=feedback,
    )


def call_model(prompt: str, model_config: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    payload = {
        "model": model_config.get("name"),
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": model_config.get("temperature", 0.1),
            "top_p": model_config.get("top_p", 0.9),
            "num_predict": model_config.get("max_tokens", 700),
        },
    }
    request = urllib.request.Request(
        model_config.get("url"),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=model_config.get("timeout_seconds", 300)) as response:
        response_data = json.loads(response.read().decode("utf-8"))
    return response_data.get("response", ""), response_data


def parse_proposal(raw_response: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Parse the baseline's lightweight response contract.

    This is intentionally not the thesis system's JSON-schema validator. It
    only extracts a single package and optional version so that execution can
    be performed safely with an argument vector rather than a shell command.
    """
    json_text = raw_response.strip()
    if json_text.startswith("```"):
        first_newline = json_text.find("\n")
        closing_fence = json_text.rfind("```")
        if first_newline != -1 and closing_fence > first_newline:
            json_text = json_text[first_newline + 1:closing_fence].strip()
    try:
        proposal = json.loads(json_text)
    except json.JSONDecodeError as error:
        return None, "invalid_json: {}".format(error)
    if not isinstance(proposal, dict):
        return None, "proposal is not a JSON object"
    package = proposal.get("package")
    version = proposal.get("version")
    if not isinstance(package, str) or not SAFE_PACKAGE_RE.fullmatch(package):
        return None, "invalid package name"
    if version is not None and (not isinstance(version, str) or not SAFE_PACKAGE_RE.fullmatch(version)):
        return None, "invalid version"
    return {"package": package, "version": version, "rationale": proposal.get("rationale")}, None


def proposal_to_i4_record(record: Dict[str, Any], proposal: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    version = proposal.get("version")
    action = "pin_version" if version else "install"
    argv = ["python", "-m", "pip", "install", proposal["package"] + ("==" + version if version else "")]
    return {
        "run_id": run_id,
        "notebook_execution_id": record.get("notebook_execution_id"),
        "status": "success",
        "final_action": action,
        "final_install_name": proposal["package"],
        "final_version": version,
        "argv": argv,
        "input": {
            "error_type": record.get("error_type"),
            "error_message": record.get("error_message"),
            "failing_module": record.get("failing_module"),
        },
    }


def build_feedback_record(original: Dict[str, Any], attempt: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if attempt.get("outcome") != "still_failing" or attempt.get("same_as_original_error", True):
        return None
    error_type = attempt.get("new_error_type")
    error_message = attempt.get("new_error_message")
    if error_type not in DEPENDENCY_ERROR_TYPES or not error_message:
        return None
    return {
        "notebook_execution_id": original.get("notebook_execution_id"),
        "repository_id": original.get("repository_id"),
        "notebook_id": original.get("notebook_id"),
        "notebook_name": original.get("notebook_name"),
        "repository_url": original.get("repository_url"),
        "split": original.get("split"),
        "error_type": error_type,
        "error_message": error_message,
        "failing_module": extract_failing_module(error_message),
    }


def propose_round(
    record: Dict[str, Any],
    links: Dict[str, Dict[str, Any]],
    config: Dict[str, Any],
    prior_rounds: List[Dict[str, Any]],
    model_call: Callable[[str, Dict[str, Any]], Tuple[str, Dict[str, Any]]] = call_model,
) -> Dict[str, Any]:
    baseline_config = config.get("baseline", {})
    runtime_python_version = str(baseline_config.get("runtime_python_version", "3.10"))
    distribution = distribution_from_reference(record.get("failing_module"), links)
    pypi_result = fetch_pypi_project(
        distribution or "", baseline_config.get("pypi", {}), runtime_python_version
    )
    prompt = build_prompt(
        record,
        distribution,
        pypi_result,
        prior_rounds,
        int(baseline_config.get("pypi", {}).get("candidate_version_limit", 12)),
    )
    result: Dict[str, Any] = {
        "input": {
            "error_type": record.get("error_type"),
            "error_message": record.get("error_message"),
            "failing_module": record.get("failing_module"),
        },
        "reference_distribution": distribution,
        "pypi_evidence": pypi_result,
        "prompt_version": baseline_config.get("repair", {}).get("prompt_version"),
        "raw_response": None,
        "proposal": None,
        "status": "abstained",
        "reason": None,
    }
    try:
        raw_response, _ = model_call(prompt, baseline_config.get("model", {}))
    except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
        result["status"] = "failed"
        result["reason"] = "model_unavailable: {}".format(error)
        return result
    except Exception as error:
        result["status"] = "failed"
        result["reason"] = "model_error: {}: {}".format(type(error).__name__, error)
        return result

    result["raw_response"] = raw_response
    proposal, parse_error = parse_proposal(raw_response)
    if parse_error:
        result["reason"] = parse_error
        return result

    proposed_pypi = fetch_pypi_project(
        proposal["package"], baseline_config.get("pypi", {}), runtime_python_version
    )
    result["proposed_package_pypi"] = proposed_pypi
    if proposed_pypi.get("status") != "resolved":
        result["reason"] = "proposed package is not available from PyPI"
        return result
    if proposal.get("version") and proposal["version"] not in proposed_pypi.get("versions", []):
        result["reason"] = "proposed version is not available from PyPI"
        return result

    result["proposal"] = proposal
    result["status"] = "proposed"
    return result


def process_record(
    record: Dict[str, Any],
    config: Dict[str, Any],
    fix_config: Dict[str, Any],
    i2_index: Dict[int, Dict[str, Any]],
    repository_metadata_lookup: Callable[[int], Optional[Dict[str, Any]]],
    links: Dict[str, Dict[str, Any]],
    run_id: str,
    *,
    model_call: Callable[[str, Dict[str, Any]], Tuple[str, Dict[str, Any]]] = call_model,
    applier: Callable[..., Dict[str, Any]] = fix_applicator.apply_and_validate,
) -> Dict[str, Any]:
    max_rounds = int(config.get("baseline", {}).get("repair", {}).get("max_rounds", 2))
    if max_rounds not in {1, 2}:
        raise BaselineError("max_rounds must be 1 or 2")

    trace: Dict[str, Any] = {
        "run_id": run_id,
        "created_at": utc_now(),
        "baseline": "pllm_style_notebook_v1",
        "notebook_execution_id": record.get("notebook_execution_id"),
        "split": record.get("split"),
        "rounds": [],
    }
    current = record
    prior_rounds: List[Dict[str, Any]] = []
    prior_argvs: List[List[str]] = []

    for round_number in range(1, max_rounds + 1):
        proposal_result = propose_round(current, links, config, prior_rounds, model_call=model_call)
        round_trace: Dict[str, Any] = {"round": round_number, "proposal": proposal_result, "attempt": None}
        if proposal_result["status"] != "proposed":
            trace["rounds"].append(round_trace)
            break

        i4_record = proposal_to_i4_record(current, proposal_result["proposal"], run_id)
        attempt = applier(
            i4_record,
            i2_index,
            fix_config,
            repository_metadata_lookup,
            run_id=run_id,
            prior_fix_argvs=prior_argvs or None,
        )
        round_trace["attempt"] = attempt
        trace["rounds"].append(round_trace)

        feedback = build_feedback_record(record, attempt)
        if feedback is None or round_number == max_rounds:
            break
        prior_rounds.append({
            "command": attempt.get("command"),
            "new_error_type": attempt.get("new_error_type"),
            "new_error_message": attempt.get("new_error_message"),
            "outcome": attempt.get("outcome"),
        })
        if attempt.get("argv"):
            prior_argvs.append(attempt["argv"])
        current = feedback

    return trace


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the PLLM-style baseline on development records only.")
    parser.add_argument("--split", choices=["dev"], default="dev")
    parser.add_argument("--config", default="config/pllm_style_baseline.yaml")
    parser.add_argument("--fix-config", default="config/fix_applicator.yaml")
    parser.add_argument("--run-id", default=make_run_id())
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output")
    parser.add_argument(
        "--precache-reference-distributions",
        action="store_true",
        help="populate the configured PyPI cache from PLLM's reference table, without running notebooks",
    )
    parser.add_argument(
        "--precache-input-split",
        choices=["dev", "evaluation"],
        help="also cache deterministic initial module candidates for this split; requires --precache-reference-distributions",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    i2_path = config.get("dataset", {}).get("i2_path")
    records = load_records(i2_path, args.split)
    if args.limit is not None:
        records = records[: args.limit]
    links = load_reference_module_links(config.get("baseline", {}).get("reference_module_link", ""))
    if args.precache_reference_distributions:
        distributions = set(reference_distributions(links))
        if args.precache_input_split:
            distributions.update(record_distributions(i2_path, args.precache_input_split, links))
        results = precache_distributions(sorted(distributions, key=str.lower), config)
        status_counts: Dict[str, int] = {}
        for result in results:
            status = str(result.get("status", "unknown"))
            status_counts[status] = status_counts.get(status, 0) + 1
        blocking = [
            result for result in results
            if result.get("status") in {"network_error", "http_error", "invalid_response"}
        ]
        print(
            "cached_distributions={} statuses={}".format(
                len(results), ",".join("{}:{}".format(status, count) for status, count in sorted(status_counts.items()))
            )
        )
        if blocking:
            print("blocking=" + ",".join(result.get("distribution", "unknown") for result in blocking))
            raise SystemExit(1)
        return
    fix_config = fix_applicator.load_fix_applicator_config(args.fix_config)
    i2_index = fix_applicator.load_i2_index(i2_path)
    repository_metadata_lookup = fix_applicator.default_repository_metadata_lookup(
        fix_config.get("upstream_docker_pipeline", {}).get("db_path")
    )

    output_path = Path(args.output or (ROOT / config.get("output", {}).get("trace_directory", "data/pllm-style-baseline") / (args.run_id + ".jsonl")))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        for record in records:
            trace = process_record(
                record, config, fix_config, i2_index, repository_metadata_lookup, links, args.run_id
            )
            output.write(json.dumps(trace, ensure_ascii=False) + "\n")
            output.flush()
            print("notebook_execution_id={} rounds={}".format(record.get("notebook_execution_id"), len(trace["rounds"])))


if __name__ == "__main__":
    try:
        main()
    except (BaselineError, FileNotFoundError, json.JSONDecodeError, KeyError) as error:
        print("ERROR: {}".format(error), file=sys.stderr)
        raise SystemExit(1)
