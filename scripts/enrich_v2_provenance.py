#!/usr/bin/env python3

"""Create the strict, commit-pinned input dataset for V2 evaluation.

The original context file may contain best-effort source fetches that fell
back from a recorded commit to ``main`` or ``master``.  V2 never does that.
This script keeps the error records unchanged but separately records whether
the upstream database supplied an exact commit, the commit's author date, and
requirements content fetched only at that exact commit.
"""

import argparse
import hashlib
import json
import sqlite3
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from extract_error_contexts import load_repository_metadata


DEFAULT_DB_PATH = Path.home() / "era/computational-reproducibility-pmc-docker/data/db/db.sqlite"
PATCH_URL = "https://github.com/{repository}/commit/{commit}.patch"
RAW_URL = "https://raw.githubusercontent.com/{repository}/{commit}/{path}"
USER_AGENT = "ma-thesis-v2-provenance/1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def fetch_bytes(url: str) -> Optional[bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None


def fetch_commit_date(repository: str, commit: str) -> Optional[str]:
    payload = fetch_bytes(PATCH_URL.format(repository=repository, commit=commit))
    if payload is None:
        return None
    for line in payload.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("Date: "):
            continue
        try:
            parsed = parsedate_to_datetime(line[len("Date: "):])
            if parsed.tzinfo is None:
                return None
            return parsed.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            return None
    return None


def strict_requirements(repository: str, commit: str, raw_paths: Optional[str]) -> list:
    result = []
    for path in (raw_paths or "").split(";"):
        path = path.strip()
        if not path:
            continue
        payload = fetch_bytes(RAW_URL.format(repository=repository, commit=commit, path=path))
        result.append({
            "path": path,
            "fetched": payload is not None,
            "ref": commit if payload is not None else None,
            "content": payload.decode("utf-8", errors="replace")[:4000] if payload is not None else None,
            "provenance": "recorded_commit_only",
        })
    return result


def _open_immutable_db(path: Path) -> sqlite3.Connection:
    # The upstream pipeline can keep a write lock on its database.  This
    # read-only snapshot avoids changing it and records the exact DB hash in
    # the provenance manifest.  It must never be used if the path is absent.
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def _repository_provenance(item: Tuple[int, Dict[str, Any]]) -> Tuple[int, Dict[str, Any]]:
    repository_id, meta = item
    repository, commit = meta.get("repository"), meta.get("commit")
    if not repository or not commit:
        return repository_id, {
            "repository_commit": commit,
            "repository_commit_date": None,
            "provenance_status": "recorded_commit_unavailable",
            "dependency_file_metadata": [],
            "repository_setup_paths": [],
        }
    commit_date = fetch_commit_date(repository, commit)
    requirements = strict_requirements(repository, commit, meta.get("requirements"))
    return repository_id, {
        "repository_commit": commit,
        "repository_commit_date": commit_date,
        "provenance_status": (
            "recorded_commit_and_date" if commit_date is not None else "recorded_commit_date_unavailable"
        ),
        "dependency_file_metadata": requirements,
        "repository_setup_paths": [p.strip() for p in (meta.get("setups") or "").split(";") if p.strip()],
    }


def enrich_records(records: Iterable[Dict[str, Any]], metadata: Dict[int, Dict[str, Any]], workers: int) -> Tuple[list, Dict[str, int]]:
    repository_ids = sorted({int(r["repository_id"]) for r in records if r.get("repository_id") is not None})
    selected = [(repository_id, metadata.get(repository_id, {})) for repository_id in repository_ids]
    provenance: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_repository_provenance, item) for item in selected]
        for future in as_completed(futures):
            repository_id, value = future.result()
            provenance[repository_id] = value

    enriched = []
    for record in records:
        updated = dict(record)
        repo_value = provenance.get(int(record["repository_id"])) if record.get("repository_id") is not None else None
        repo_value = repo_value or {
            "repository_commit": None,
            "repository_commit_date": None,
            "provenance_status": "repository_metadata_unavailable",
            "dependency_file_metadata": [],
            "repository_setup_paths": [],
        }
        updated.update(repo_value)
        prompt_context = dict(updated.get("prompt_context") or {})
        prompt_context["dependency_files"] = repo_value["dependency_file_metadata"]
        prompt_context["repository_commit"] = repo_value["repository_commit"]
        prompt_context["repository_commit_date"] = repo_value["repository_commit_date"]
        updated["prompt_context"] = prompt_context
        enriched.append(updated)

    counts: Dict[str, int] = {}
    for value in provenance.values():
        status = value["provenance_status"]
        counts[status] = counts.get(status, 0) + 1
    return enriched, counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Build strict V2 commit-pinned context/provenance records.")
    parser.add_argument("--input", type=Path, default=Path("data/context-classification/dependency_error_contexts.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/context-classification-v2/dependency_error_contexts.jsonl"))
    parser.add_argument("--manifest", type=Path, default=Path("data/context-classification-v2/provenance_manifest.json"))
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if not args.db_path.is_file():
        raise SystemExit(f"upstream metadata DB does not exist: {args.db_path}")

    records = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    connection = _open_immutable_db(args.db_path)
    try:
        metadata = load_repository_metadata(connection)
    finally:
        connection.close()
    enriched, status_counts = enrich_records(records, metadata, args.workers)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in enriched), encoding="utf-8")
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_path": str(args.input),
        "input_sha256": sha256(args.input),
        "upstream_metadata_db_path": str(args.db_path),
        "upstream_metadata_db_sha256": sha256(args.db_path),
        "commit_date_source": "GitHub commit patch Date header at exact recorded commit",
        "dependency_file_policy": "requirements files fetched only at exact recorded commit; no main/master fallback",
        "record_count": len(enriched),
        "repository_provenance_status_counts": status_counts,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
