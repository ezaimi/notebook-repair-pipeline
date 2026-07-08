import csv
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / "era/computational-reproducibility-pmc-docker/data/db/db.sqlite"
OUTPUT_PATH = Path("data/dependency-errors/dependency_errors.csv")
SCHEMA_PATH = Path("data/dependency-errors/dependency_errors_schema.md")
STATS_PATH = Path("data/dependency-errors/statistics.json")
SPLIT_PATH = Path("data/dependency-errors/split_manifest.json")
DOCS_PATH = Path("docs/dataset.md")

DEV_IDS = {8, 10, 17, 19, 43, 45, 49, 50, 60, 61, 157, 174, 188}

def extract_failing_module(error_message):
    if not error_message:
        return ""

    patterns = [
        r"No module named ['\"]([^'\"]+)['\"]",
        r"cannot import name ['\"][^'\"]+['\"] from ['\"]([^'\"]+)['\"]",
        r"Missing optional dependency ['\"]([^'\"]+)['\"]",
        r"[Ii]nstall ([A-Za-z0-9_.-]+)",
        r"[Pp]lease install ([A-Za-z0-9_.-]+)",
        r"pip install ([A-Za-z0-9_.-]+)",
        r"['\"]([^'\"]+)['\"] must be installed",
        r"install [`']([^`']+)[`']",
        r"([A-Za-z0-9_.-]+) is required",
    ]

    for pattern in patterns:
        match = re.search(pattern, error_message, re.IGNORECASE)
        if match:
            return match.group(1).split(".")[0]

    match = re.search(r"(lib[A-Za-z0-9_.-]+\.so(?:\.\d+)*)", error_message)
    if match:
        return match.group(1)

    return ""

def classify(error_type, error_message, failing_module):
    message = error_message or ""

    if ".so" in message or "shared object file" in message:
        return "system_library", "excluded", "requires system library, outside pip-only scope"

    if failing_module in {"utils", "statistics", "config", "helpers", "src"}:
        return "mapping_unknown", "excluded", "ambiguous local/module-path import"

    if error_type == "ModuleNotFoundError" or "No module named" in message:
        return "missing_package", "usable", ""

    if "cannot import name" in message:
        return "wrong_version", "usable", ""

    if "install" in message.lower() or "required" in message.lower():
        return "missing_package", "usable", ""

    return "out_of_scope", "excluded", "unsupported dependency-error pattern"


def write_metadata(output_rows):
    stats = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_database": "~/era/computational-reproducibility-pmc-docker/data/db/db.sqlite",
        "total_rows": len(output_rows),
        "split_counts": dict(Counter(row["split"] for row in output_rows)),
        "subtype_counts": dict(Counter(row["subtype"] for row in output_rows)),
        "error_type_counts": dict(Counter(row["error_type"] for row in output_rows)),
        "scope_status_counts": dict(Counter(row["scope_status"] for row in output_rows)),
        "exclusion_reason_counts": dict(Counter(row["exclusion_reason"] for row in output_rows if row["exclusion_reason"])),
        "top_failing_modules": Counter(row["failing_module"] for row in output_rows).most_common(20),
    }

    STATS_PATH.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_database": "~/era/computational-reproducibility-pmc-docker/data/db/db.sqlite",
        "split_policy": {
            "dev": "Rows already used during L4/L5 design-time work.",
            "evaluation": "In-scope rows reserved for later repair evaluation.",
            "excluded": "Rows outside the pip-only v1 repair scope."
        },
        "splits": {
            split: [
                int(row["notebook_execution_id"])
                for row in output_rows
                if row["split"] == split
            ]
            for split in ["dev", "evaluation", "excluded"]
        }
    }

    SPLIT_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    SCHEMA_PATH.write_text("""# Dependency Error Dataset Schema

| Column | Meaning |
| --- | --- |
| `notebook_execution_id` | ID of the failed notebook execution from `notebook_executions`. |
| `repository_run_id` | ID of the repository run. |
| `repository_id` | Repository ID from the Docker pipeline database. |
| `notebook_id` | Notebook ID from the Docker pipeline database. |
| `notebook_name` | Notebook path/name. |
| `repository_url` | Repository URL recorded during execution. |
| `execution_status` | Execution status recorded by the Docker pipeline. |
| `error_type` | Python exception type, for example `ModuleNotFoundError` or `ImportError`. |
| `error_category` | Pipeline error category. This dataset keeps `DEPENDENCY_ERROR`. |
| `error_message` | Error message stored in the database. |
| `error_cell_index` | Index of the failing notebook cell, if available. |
| `error_count` | Number of errors recorded for the execution. |
| `failing_module` | Module, package, or shared library extracted from the error message. |
| `subtype` | Classified subtype: `missing_package`, `wrong_version`, `system_library`, or `mapping_unknown`. |
| `scope_status` | Whether the row is `usable` or `excluded` for the pip-only v1 repair scope. |
| `exclusion_reason` | Reason why the row was excluded, if applicable. |
| `split` | Dataset split: `dev`, `evaluation`, or `excluded`. |
| `created_at` | Timestamp from the source execution row. |
""", encoding="utf-8")

    DOCS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOCS_PATH.write_text("""# Dependency Error Dataset

## Purpose

This document describes the dependency-error dataset prepared for the notebook repair pipeline.

The dataset contains notebook executions from the Docker-based reproducibility pipeline where `error_category = 'DEPENDENCY_ERROR'`.

The goal is to create a clean input dataset for later LLM-based explanation and repair experiments.

## Source

Source database: `~/era/computational-reproducibility-pmc-docker/data/db/db.sqlite`

Main source table: `notebook_executions`

## Scope

The v1 repair scope is pip-based. This means a row is usable only if the failure can reasonably be repaired by installing or pinning a Python package with `pip`.

Rows are excluded when they require system libraries, shared object files, local import/path fixes, or ambiguous local modules.

## Subtypes

Rows are classified into:

- `missing_package`
- `wrong_version`
- `system_library`
- `mapping_unknown`

Current counts are stored in `data/dependency-errors/statistics.json`.

## Split Policy

The dataset uses three splits:

- `dev`
- `evaluation`
- `excluded`

The `dev` split contains rows already used during L4 prompt design or L5 proof-of-concept work.

The `evaluation` split contains usable rows reserved for later repair evaluation.

The `excluded` split contains rows outside the pip-only v1 repair scope.

## Output Files

- `data/dependency-errors/dependency_errors.csv`
- `data/dependency-errors/dependency_errors_schema.md`
- `data/dependency-errors/statistics.json`
- `data/dependency-errors/split_manifest.json`

The extraction script is `scripts/prepare_dependency_dataset.py`.
""", encoding="utf-8")


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row

    rows = connection.execute("""
        SELECT
            id AS notebook_execution_id,
            repository_run_id,
            repository_id,
            notebook_id,
            notebook_name,
            url AS repository_url,
            execution_status,
            error_type,
            error_category,
            error_message,
            error_cell_index,
            error_count,
            created_at
        FROM notebook_executions
        WHERE error_category = 'DEPENDENCY_ERROR'
        ORDER BY id;
    """).fetchall()

    output_rows = []

    for row in rows:
        failing_module = extract_failing_module(row["error_message"])
        subtype, scope_status, exclusion_reason = classify(
            row["error_type"],
            row["error_message"],
            failing_module
        )

        if scope_status == "excluded":
            split = "excluded"
        elif row["notebook_execution_id"] in DEV_IDS:
            split = "dev"
        else:
            split = "evaluation"

        output_rows.append({
            "notebook_execution_id": row["notebook_execution_id"],
            "repository_run_id": row["repository_run_id"],
            "repository_id": row["repository_id"],
            "notebook_id": row["notebook_id"],
            "notebook_name": row["notebook_name"],
            "repository_url": row["repository_url"],
            "execution_status": row["execution_status"],
            "error_type": row["error_type"],
            "error_category": row["error_category"],
            "error_message": row["error_message"],
            "error_cell_index": row["error_cell_index"],
            "error_count": row["error_count"],
            "failing_module": failing_module,
            "subtype": subtype,
            "scope_status": scope_status,
            "exclusion_reason": exclusion_reason,
            "split": split,
            "created_at": row["created_at"],
        })

    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=output_rows[0].keys())
        writer.writeheader()
        writer.writerows(output_rows)

    write_metadata(output_rows)

    print(f"Loaded rows: {len(rows)}")
    print(f"Wrote: {OUTPUT_PATH}")
    print(f"Wrote: {SCHEMA_PATH}")
    print(f"Wrote: {STATS_PATH}")
    print(f"Wrote: {SPLIT_PATH}")
    print(f"Wrote: {DOCS_PATH}")

if __name__ == "__main__":
    main()
