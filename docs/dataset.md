# Dependency Error Dataset

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
