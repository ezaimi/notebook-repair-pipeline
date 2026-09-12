# I8 Pre-Final-Evaluation Freeze Record

This document freezes the exact configuration the 187-record evaluation
split must be run under. It was created immediately after committing the
I8 tooling, so it can reference a fixed Git SHA. **Nothing in this
document authorizes running the evaluation split — it is a freeze record,
not a run.**

## Git state

- **Commit SHA**: `dfb0b652a456627058f0f0a037bd35916db94115`
- Branch: `i8-final-evaluation-pipeline-and-metrics`
- This commit is **not pushed**.
- The final 187-record run must be executed against this exact commit (or
  a fast-forward of it that touches none of the hashed paths below).

## Experiment configuration

| Field | Value |
|---|---|
| `split` | `evaluation` |
| `expected_record_count` | **187** (data-derived from `data/context-classification/dependency_error_contexts.jsonl` at freeze time, not hardcoded) |
| `max_rounds` | `2` |
| `model` | `gemma2:9b` |
| `prompt_strategy` | `few_shot` |
| `explanation_prompt_version` | `i3_prompt_v1` |
| `repair_prompt_version` | `i4_prompt_v1` |
| Python version | `3.13.7` |
| pyyaml | `6.0.3` |
| jsonschema | `4.26.0` |

## Config/prompt hashes (frozen — must be re-verified unchanged immediately before the final run)

| Path | SHA-256 |
|---|---|
| `prompts/` (directory hash) | `76b232f04827ebc35d1cadd7e3cb2821cf9d8c30a10473885c65db3a218b86e4` |
| `config/package_mapping.yaml` | `e2231d9855b77f5b200597c6814f7d719be5fb73302d79e058e6a8f281e17562` |
| `config/rag_repair.yaml` | `1760f298c4b778ae6c36f4774a5833e932ca37eb1190e30ca865e888f4a5d94f` |
| `config/llm_explainer.yaml` | `ae3170258456f017f3ea8254b3a5ea570583c82dae2cc1de0d74b2d39dbdac7d` |
| `config/fix_applicator.yaml` (default, unused by the final run) | `138aaf4f0552d43432dff5b86bb9cf8cd53286beda10893ce3d96e66dbe45637` |
| `config/fix_applicator.evaluation.local.yaml` (**effective** FixApplicator config for the final run — machine-local, untracked) | `d02577b07824da27e37c81f5054503c0ac43c09d51ee2bb38aa0df6478724385` |

Recompute all six with `evaluation_manifest.build_config_hashes()` /
`hashlib.sha256` immediately before the final run and compare against this
table. Any mismatch means something changed since this freeze and the run
must not proceed until investigated.

## Upstream commit-metadata DB (used via `config/fix_applicator.evaluation.local.yaml`)

| Field | Value |
|---|---|
| Source (authoritative) | `/home/zaimi/era/computational-reproducibility-pmc-docker/data/db/db.sqlite` (sibling checkout, WSL filesystem) |
| Local copy used at run time | `C:\Users\zaimi\i8-eval-local-cache\upstream_pmc_docker_db.sqlite` |
| File size | 7,876,608 bytes |
| SHA-256 (source, via native WSL `sha256sum`) | `ce049a7e5853a703f12b789e4dd2ef0f9d9b6d3cc7fbd88a237c7d963623a8a6` |
| SHA-256 (local copy, via Python) | `ce049a7e5853a703f12b789e4dd2ef0f9d9b6d3cc7fbd88a237c7d963623a8a6` (identical — verified byte-for-byte) |
| Tables | `executions` (321 rows), `notebook_executions` (443), `notebook_reproducibility_metrics` (443), `notebooks` (27,271), `repositories` (5,241), `repository_runs` (116), `sqlite_sequence` (3) |

The final evaluation manifest must record this same SHA-256 for the
metadata DB it actually reads from, so a future reader can confirm the
final run used this exact upstream snapshot.

## Intended output structure

```
data/evaluation/<run_id>/
  manifest.json
  raw/                      # gitignored (data/evaluation/*/raw/)
    pipeline-runs/<run_id>.jsonl
    repair_attempts.sqlite
  summary/
  tables/
  validation_report.json
```

`raw/` for the final run should itself be written to a genuine local
(non-UNC) path during execution (same reason as the dev validation and
the exact-commit spot check — see below), then copied into
`data/evaluation/<run_id>/raw/` afterward; `manifest.json`, `summary/`,
`tables/`, and `validation_report.json` are the artifacts intended for
commit.

## Intended final run ID

```
i8-eval-final-<timestamp>
```

e.g. `i8-eval-final-20260915T090000Z`. Exactly one run ID for the actual
187-record run — no competing/parallel run IDs are to be generated ahead
of time.

## Known, deliberately-not-fixed limitation

The static `config/package_mapping.yaml` (9 entries) does not cover
several high-frequency `missing_package` import names surfaced during dev
validation and sample-freezing (`rpy2`, `cana`, `celloracle`, `keras`,
`statsmodels`, and others). These will abstain as `mapping_unknown` in the
final run. This is intentional and must not be "fixed" before or during
the final run — see `docs/i8-evaluation-methodology.md` and the I8 issue's
"do not tune based on evaluation data" constraint.
