# I8: Evaluation Methodology and Tooling

I8 evaluates the already-implemented I1-I7 pipeline. It does not
redesign, tune, or extend any I1-I7 component. This document describes
the frozen metric definitions and the tooling that computes them
(`scripts/evaluation_manifest.py`, `scripts/run_evaluation.py`,
`scripts/evaluation_metrics.py`, `scripts/infra_classification.py`,
`scripts/manual_ground_truth_scoring.py`, `scripts/evaluate_results.py`,
`scripts/validate_evaluation_results.py`, `scripts/kg_competency_checks.py`,
`scripts/freeze_manual_samples.py`).

## Dev-before-evaluation rule

The reserved 187-record `evaluation` split is never touched by this
tooling except through an explicit, separately-guarded invocation. Every
script in this document defaults to (or, for `scripts/run_evaluation.py`,
hard-refuses anything but) the 13-record `dev` split unless a caller
passes `--split evaluation` **and** (`run_evaluation.py` specifically)
`--i-understand-this-touches-the-reserved-split`. All numbers in this
document and in the current `data/evaluation/` outputs come from the dev
split only.

## Metric hierarchy

### PRIMARY

1. **System-level Repair Success Rate** = fixed (final, up to 2 rounds) /
   expected record count. The headline metric. Never replace this
   denominator with a smaller one anywhere numbers are reported.
2. **Round-1 Repair Success Rate** = Round-1 fixed / expected record count.
3. **Final Repair Success Rate (up to 2 rounds)** - numerically identical
   to (1), reported alongside (2) for the Round-1-vs-2 comparison.
4. **Additional notebooks fixed by Round 2** - count of notebooks
   `still_failing` after Round 1 that become `fixed` after Round 2.
5. **Absolute percentage-point improvement from Round 2** = (3) - (2).

### SECONDARY / diagnostic

- **Conditional Repair Success Rate** = fixed / notebooks where
  FixApplicator actually attempted a repair. Must never replace the
  headline system-level rate - it silently drops every abstention from
  the denominator.
- **Targeted Error Resolution Rate** - attempt-level (not
  notebook-level): resolved attempts (fixed, or `still_failing` with
  `same_as_original_error == False`) / all real FixApplicator attempts,
  any round. Distinguishes "notebook fully fixed" from "the *targeted*
  dependency error is gone but a new one appeared" (e.g. sklearn missing ->
  install scikit-learn -> sklearn error gone -> pandas missing).
- **Method-only Success Rate** = fixed / (expected count - genuine
  infrastructure failures).
- **Infrastructure Failure Rate**, **Abstention Rate**.
- **Proposal Validity Rate** = schema-valid proposals / LLM repair
  responses (malformed LLM output only).
- **Grounding Pass Rate** = grounded proposals / schema-valid proposals
  (grounding rejection only - never conflated with the above).
- **Subtype-level repair success**, **explanation schema-validity rate**.
- **Distribution Resolution Accuracy** (once manual labels exist) - no
  Precision@k/Recall@k/MRR/nDCG: `scripts/pypi_retriever.py`'s `retrieve()`
  sorts candidates newest-first, not by relevance, so there is nothing to
  rank-evaluate.
- **Classifier metrics** (once manual labels exist): scope-status
  precision/recall/F1, subtype confusion matrix + per-class P/R/F1,
  failing-module exact-match accuracy (deliberately NOT a
  precision/recall/F1/confusion-matrix metric - unbounded label space).

## Infrastructure-vs-method classification rule

Implemented once, centrally, in `scripts/infra_classification.py`
(`classify_i4_i5()` / `classify_round_entry()`). Governing principle:
**when a case is ambiguous, classify it as a method failure, not an
infrastructure failure** - the opposite default would let "infrastructure"
absorb awkward cases and inflate a method-only success rate.

| Condition | Category |
|---|---|
| i4 `status == "failed"` | infrastructure (by construction - only ever set for timeout/model_unavailable/runtime_error) |
| i4 abstained, retrieval status in `{network_error, invalid_response, configuration_error}` | infrastructure |
| i4 abstained, retrieval status in `{mapping_unknown, package_not_found, no_compatible_release}`, or any other abstention gate | abstained (method) |
| i5 `apply_error`, `failure_stage` in `{clone, checkout, build, timeout, join, validation}` | infrastructure |
| i5 `apply_error`, `execution_status` in `{fix_install_failed, notebook_not_found, docker_run_failed, output_notebook_missing}` | method (conservative default) |
| i5 `apply_error`, anything unrecognized | method (conservative default) |
| orchestrator `component_error`/`orchestrator_error` | infrastructure |
| `scope_status != "usable"` | excluded (outside the repair-success denominator entirely) |

## Paired Round-1/Round-2 design

`scripts/run_evaluation.py` invokes `scripts/run_pipeline.py` **once**,
with `--max-rounds 2`. `scripts/evaluation_metrics.build_comparison_record()`
then derives both conditions from that single run:

- Round-1 condition = the record's own Round-1 result.
- Up-to-Round-2 condition = Round 2's result if Round 2 actually ran, else
  Round 1's.

This is deliberate: `config/rag_repair.yaml` and `config/llm_explainer.yaml`
both run Ollama at `temperature: 0.1` with no `seed` parameter anywhere in
the call sites, so two independent runs are not guaranteed to reproduce
the same Round-1 LLM output. Re-running Round 1 for a separate
`--max-rounds 1` experiment would let LLM sampling noise masquerade as a
Round-2 effect. The paired design cannot have this confound, because
Round 1 is read once and never re-sampled.

McNemar's test is not the primary Round-1-vs-2 comparison: because the
up-to-Round-2 condition is monotone in Round 1 (nothing "un-fixes" between
conditions), one of McNemar's four contingency cells is structurally zero.
The primary comparison is the plain count of additionally-fixed notebooks
and the absolute percentage-point improvement; an exact binomial test on
the rescue proportion is an optional secondary inferential check.

## Reproducible configuration

`scripts/evaluation_manifest.py` records, per run: `run_id`, `split`,
`expected_record_count` (derived from the live i2 dataset at manifest-build
time - never a hardcoded 13/187/214), `max_rounds`, `model`,
`prompt_strategy`, prompt/repair version tags, config file paths, Python
version, git commit SHA, timestamps, database/output paths, repository
metadata DB accessibility, and SHA-256 hashes of `prompts/`,
`config/package_mapping.yaml`, `config/rag_repair.yaml`,
`config/llm_explainer.yaml`, `config/fix_applicator.yaml`. It never reads
or stores `.env` contents. `scripts/run_evaluation.py` refuses to resume
under an existing `run_id` if any of these frozen fields drifted since the
last manifest for that `run_id` (`evaluation_manifest.ManifestConsistencyError`).

## Output artifact structure

```
data/evaluation/<run_id>/
  manifest.json
  raw/
    pipeline-runs/<run_id>.jsonl   # scripts/run_pipeline.py's own trace
    repair_attempts.sqlite         # I6 schema, reused as-is
  summary/
    evaluation_summary.json
    evaluation_summary.csv
    per_notebook_comparison.csv
    failure_breakdown.csv
    subtype_breakdown.csv
  tables/
    table_1_overall_repair_results.csv
    table_2_round1_vs_round2.csv
    table_3_targeted_error_resolution_vs_full_repair.csv
    table_4_subtype_breakdown.csv
    table_5_failure_abstention_infra_breakdown.csv
    table_6_pypi_rag_proposal_quality.csv
    table_7_classifier_performance.csv
    table_8_pipeline_resultlogger_integrity.csv
  validation_report.json           # scripts/validate_evaluation_results.py
```

Raw pipeline output (`raw/`) is kept separate from the generated
summaries/tables so a re-run of `scripts/evaluate_results.py` never
confuses a scratch artifact with a committed result.

## Manual ground-truth requirements

`scripts/freeze_manual_samples.py` selects, deterministically (a stable
SHA-256-derived ordering, never Python's seeded `random`), two samples
**before** the evaluation split is run:

- `data/manual-ground-truth/classifier_ground_truth_sample.csv` - all
  `system_library` (10) and `mapping_unknown` (4) records (the two
  excluded subtypes), plus a stratified sample of `wrong_version` (15) and
  `missing_package` (20), each drawn primarily from the evaluation split
  with a small dev-split slice for calibration. `manual_scope_status`/
  `manual_subtype`/`manual_failing_module` are blank; `predicted_*`
  columns are reference-only context, never copied into the manual
  columns.
- `data/manual-ground-truth/pypi_resolution_sample.csv` - every import
  name in `config/package_mapping.yaml` actually exercised by the dataset,
  plus the most frequently exercised import names that are **not** in that
  mapping. The generated sample already shows a real, honest finding:
  several high-frequency `missing_package` import names (`rpy2`, `cana`,
  `celloracle`, `keras`, `statsmodels`, and others - together well over 50
  usable records) have no entry in the 9-name static mapping table and
  will abstain as `mapping_unknown` at retrieval time even though several
  of them are real, self-named PyPI packages. This is a genuine
  RAGRepairAgent coverage limitation the evaluation is designed to
  surface, not a bug in this tooling, and it is explicitly **not** to be
  fixed as part of I8.

`scripts/manual_ground_truth_scoring.py` scores these samples only once a
human fills in the `manual_*` columns; a row left blank is skipped and
counted separately, never defaulted to "correct" or "incorrect", and never
inferred from the pipeline's own prediction.

Also required, later and separately from I8: the LLMExplainer human
evaluation rubric (correctness/relevance/clarity/groundedness/usefulness)
over a ~30-40 explanation sample drawn **only** from the evaluation
split's own outputs - dev-split explanations are excluded from that later
sample because two dev records (notebook 8, sklearn; notebook 174, scipy
cumtrapz) are the frozen few-shot examples baked into
`prompts/dependency_explanation_v1.txt`, and the rest of `dev` was used
for prompt development.

## Exact-commit requirement

`FixApplicator` resolves `repository_commit` from the upstream Docker
pipeline's sqlite DB (`config/fix_applicator.yaml`,
`upstream_docker_pipeline.db_path`, default `~/era/computational-
reproducibility-pmc-docker/data/db/db.sqlite`). `scripts/
evaluation_manifest.py`'s `check_repository_metadata_db()` records whether
that path is reachable at manifest-build time.

**Finding from the dev validation run:** in an execution environment where
a Windows-native Python interpreter is used against this repository over
its WSL UNC mount (`\\wsl.localhost\...`), SQLite cannot reliably open the
upstream metadata DB at that path - `default_repository_metadata_lookup()`
catches the failure (by design, so a missing DB never blocks a repair
attempt) and returns no metadata, so every attempt falls back to
`commit_checkout_status = "skipped_no_commit"`. This is **not missing or
corrupt upstream data** - the DB exists and contains complete, correct
commit hashes for every dev record checked. A spot check
(run_id `i8-exact-commit-spotcheck`, notebook 8) confirmed that copying
the upstream DB to a genuine local (non-UNC) path and pointing
`--fix-config` at a config with `db_path` set to that local copy resolves
`repository_commit = 1a03b9b88da238d430f577f65c39f4377375edcb` and
`commit_checkout_status = "checked_out"` exactly as expected. The same
class of UNC-path issue affects `repair_attempts.sqlite` itself (worked
around the same way for the dev validation run: `--database` pointed at a
local path, with the finished file copied into `data/evaluation/<run_id>/
raw/` afterward).

**Operational requirement for the final 187-record run**, in any
environment with this same Windows-native-Python-over-WSL-UNC-mount
characteristic: point both `--database` and (via a `--fix-config` copy)
`upstream_docker_pipeline.db_path` at genuine local filesystem paths for
the duration of the run, then copy the finished `repair_attempts.sqlite`
and trace JSONL into `data/evaluation/<run_id>/raw/` afterward - exactly
as done for this dev validation. (Running entirely from native WSL Python
avoids the issue at the source, but was not usable here because Ollama, in
this setup, is reachable from Windows but not from WSL.) The pre-run
checklist item "exact-commit metadata accessible" is satisfied by
demonstrating this workaround, not by requiring a clean run with no
workaround at all.

## Consistency checks

`scripts/validate_evaluation_results.py` checks, after a run: expected
record count, every expected id present exactly once (no silent skips),
no duplicate `(notebook_execution_id, run_id, round)` rows, no `round > 2`,
every Round-2 row has a corresponding Round-1 row, Round 2 only appears
after a genuinely triggered condition, a single `run_id` throughout, no
excluded/dev records inside an `evaluation`-split run, manifest/config
hash consistency, and full ResultLogger row reconciliation (every
completed/excluded trace round produced exactly one `repair_attempts`
row). `scripts/kg_competency_checks.py` adds four small pass/fail checks
over the `repair_attempts` -> KG export shape (every attempt links to a
notebook, fixed rows carry a valid outcome, Round-2 rows carry
`round == 2`, no orphan attempts) without requiring a live triple store -
reusing `scripts/validate_kg_notebook_alignment.py` as-is for the
notebook/repository identifier alignment check itself.

## Usage

```bash
# 1. Freeze manual-sample selections (idempotent, deterministic).
python scripts/freeze_manual_samples.py

# 2. Run the dev-split validation (13 records, both rounds).
python scripts/run_evaluation.py --split dev --run-id i8-dev-validation-<timestamp>

# 3. Compute metrics and write summaries/tables.
python scripts/evaluate_results.py --run-dir data/evaluation/i8-dev-validation-<timestamp>

# 4. Run integrity checks.
python scripts/validate_evaluation_results.py --run-dir data/evaluation/i8-dev-validation-<timestamp>
```

The reserved evaluation split is run the same way, with `--split
evaluation --i-understand-this-touches-the-reserved-split`, only after
every item in the pre-run checklist is satisfied (methodology frozen,
prompts/configs frozen, dev validation passed, exact-commit metadata
accessible, no evaluation-set-based tuning, output/run IDs prepared).
