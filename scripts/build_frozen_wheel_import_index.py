#!/usr/bin/env python3
"""Build offline wheel-import evidence for a V2 paired comparison.

The input PyPI cache is already frozen.  This tool downloads only the wheel
archives referenced by that cache, extracts their declared top-level imports,
and writes an index keyed by immutable wheel filename.  The later comparison
uses the index offline; it never obtains fresh PyPI project metadata.
"""

import argparse
import hashlib
import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pypi_retriever as pypi  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def selected_wheels(cache, distribution, subtype, repository_date):
    entry = cache.get(pypi.normalize_distribution_name(distribution))
    payload = entry.get("payload") if isinstance(entry, dict) else None
    if not isinstance(payload, dict):
        return []
    files = pypi._simple_files_from_raw_json_payload(payload)
    if files is None:
        return []
    grouped = pypi._group_files_by_version(files, [])
    candidates = pypi._filter_grouped_candidates(
        grouped, pypi._parse_python_version_arg("3.10", []), limit=None, warnings=[]
    )
    if subtype == "wrong_version":
        candidates = pypi._filter_candidates_by_date(candidates, grouped, repository_date)
    candidates = candidates[:pypi.MAX_CANDIDATE_VERSIONS]
    wanted = {candidate["version"] for candidate in candidates}
    return [
        file_info
        for version, release_files in grouped.items()
        if str(version) in wanted
        for file_info in release_files
        if not file_info.get("yanked") and str(file_info.get("filename", "")).endswith(".whl")
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--i2", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--public-mapping", required=True)
    parser.add_argument("--main-trace", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    cache_path = ROOT / args.cache
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    resolver = {
        "package_mapping_path": args.mapping,
        "public_mapping_path": args.public_mapping,
    }
    requests = set()
    for record in records(ROOT / args.i2):
        if record.get("split") != "evaluation" or not record.get("failing_module"):
            continue
        subtype = record.get("refined_subtype") or record.get("original_subtype")
        if subtype not in {"missing_package", "wrong_version"}:
            continue
        for distribution, _method in pypi.resolve_v2_distribution_candidates(
            record["failing_module"], resolver
        ):
            requests.add((distribution, subtype, record.get("repository_commit_date")))

    # Include the only LLM-proposed distributions that actually passed wheel
    # verification in the completed live V2 run.  They are comparison inputs,
    # not new mapping knowledge.
    for line in (ROOT / args.main_trace).read_text(encoding="utf-8").splitlines():
        trace = json.loads(line)
        for round_data in trace.get("rounds", []):
            verification = round_data.get("i4_result", {}).get("mapping_verification") or {}
            if verification.get("status") == "resolved" and verification.get("distribution_name"):
                requests.add((verification["distribution_name"], "missing_package", None))

    entries = {}
    failures = []
    ordered_requests = sorted(requests, key=lambda item: (item[0], item[1], item[2] or ""))
    for number, (distribution, subtype, date) in enumerate(ordered_requests, start=1):
        for file_info in selected_wheels(cache, distribution, subtype, date):
            filename, url = file_info.get("filename"), file_info.get("url")
            if not isinstance(filename, str) or filename in entries:
                continue
            if not isinstance(url, str):
                failures.append({"distribution": distribution, "filename": filename, "reason": "missing_url"})
                continue
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    top_levels = pypi._wheel_top_level_imports(response.read())
            except Exception as exc:  # evidence remains unavailable, never inferred
                failures.append({"distribution": distribution, "filename": filename, "reason": type(exc).__name__})
                continue
            if top_levels is None:
                failures.append({"distribution": distribution, "filename": filename, "reason": "metadata_unavailable"})
                continue
            entries[filename] = top_levels
        print(f"processed={number}/{len(ordered_requests)} distribution={distribution}", flush=True)

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "schema_version": 1,
        "source_pypi_cache": args.cache,
        "source_pypi_cache_sha256": sha256(cache_path),
        "entries": entries,
        "unavailable": failures,
    }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"entries": len(entries), "unavailable": len(failures), "output": str(output)}))


if __name__ == "__main__":
    main()
