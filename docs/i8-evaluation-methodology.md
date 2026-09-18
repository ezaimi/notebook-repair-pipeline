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
- **Infrastructure Failure Rate**.
- **Round-1 Abstention Rate** (`round1_abstention_rate`) = notebooks the
  repair agent declined to propose anything for **in Round 1**, before any
  Round 2 could even be considered / expected record count. A Round-2
  trigger can never fire from an abstained Round-1 outcome
  (`evaluate_round2_trigger()` requires Round-1 outcome `still_failing`),
  so this population never overlaps with the next one.
- **Round-2 Abstention Count** (`round2_abstention_count`) = notebooks
  that had a real Round-1 attempt leaving them `still_failing`, became
  Round-2-eligible, and whose Round-2 repair-agent invocation ALSO
  abstained (same mechanism as Round 1 - typically `mapping_unknown` on
  whatever new/remaining dependency error Round 2 is now targeting).
  `round2_summary.non_attempt_reasons` in the full report gives the exact
  per-reason tally for the eligible-but-not-attempted population this
  count is drawn from.
- **Final-state Abstention Count/Rate** (`final_state_abstention_count`,
  `final_state_abstention_rate`) = `round1_abstention_count` +
  `round2_abstention_count`: every notebook whose LAST-classified round
  (Round 2's, if it ran, else Round 1's) was `abstained`. This is the
  number `failure_breakdown()["abstained"]` / table_5's `abstained` row
  also report - a strictly LARGER, DIFFERENT population than
  `round1_abstention_rate` alone whenever `round2_abstention_count > 0`.
  Never call this plain "abstention rate" without the "final-state"
  qualifier: doing so is exactly the ambiguity that let a Round-1-only
  figure (e.g. 126/187) be quoted next to a final-state breakdown's count
  (e.g. 162/187) as if they were the same number.
- **Proposal Validity Rate** = schema-valid proposals / LLM repair
  responses (malformed LLM output only).
- **Grounding Pass Rate** = grounded proposals / schema-valid proposals
  (grounding rejection only - never conflated with the above).
- **Grounded Proposal Rate Among LLM Invocations**
  (`grounded_proposal_rate_among_llm_invocations`) = grounded proposals /
  LLM repair responses - the composite of the two rates above over the
  same LLM-invoked population. This is conditional: its denominator
  excludes every notebook that abstained BEFORE the LLM was ever called
  (`mapping_unknown`, unsupported subtype, ineligible, etc.), so it can
  read 1.0 even when most repair opportunities never reached the LLM.
  (Formerly published as `end_to_end_valid_grounded_proposal_rate` - that
  name is retired because it implied full coverage while actually being
  conditional; do not reintroduce it.)
- **Overall Grounded Proposal Coverage Rate**
  (`overall_grounded_proposal_coverage_rate`) = grounded proposals / ALL
  repair-agent (i4) invocations across both rounds, pre-LLM abstentions
  included. This is the genuinely end-to-end figure and will be smaller
  than the LLM-conditional rate above whenever the pipeline abstains
  before the LLM on a meaningful share of records. Report both together;
  neither substitutes for the other.
- **Subtype-level repair success**.
- **Explanation metrics** - three views, defined in the dedicated
  "Explanation metrics" section below. They are reported in their own
  block (`explanation.*`, `table_9`) and never enter any repair metric.
- **Distribution Resolution Accuracy** (once manual labels exist) - no
  Precision@k/Recall@k/MRR/nDCG: `scripts/pypi_retriever.py`'s `retrieve()`
  sorts candidates newest-first, not by relevance, so there is nothing to
  rank-evaluate.
- **Classifier metrics** (once manual labels exist): scope-status
  precision/recall/F1, subtype confusion matrix + per-class P/R/F1,
  failing-module exact-match accuracy (deliberately NOT a
  precision/recall/F1/confusion-matrix metric - unbounded label space).

## Explanation metrics

The explanation objective (O1) is evaluated separately from the repair
objectives (O2/O3). Since the Round-2 LLMExplainer extension of
`scripts/run_pipeline.py`, a notebook can produce **two** explanation
records, so "one notebook = one explanation" no longer holds and every
explanation metric must state its denominator.

### Explanation population

- **Original-failure explanation.** Every notebook processed receives one
  explanation of its original dependency error (Round 1), exactly as
  before. It is the top-level `explanation` in the trace (mirrored, as the
  same record, onto the Round-1 entry).
- **Round-2 explanation.** When Round 1's re-execution ends `still_failing`
  on a *genuinely new* error (`same_as_original_error == False`) and the
  run still has round budget, the orchestrator reclassifies that error
  with the same two classifier stages every original row went through
  (`build_round2_record()`) and **explains it before evaluating repair
  eligibility**. Explanation scope is therefore broader than repair scope,
  exactly as in Round 1: a newly exposed `system_library`,
  `mapping_unknown`, or otherwise non-repairable error is still explained.
  Repair eligibility then decides only whether RAGRepairAgent and
  FixApplicator run on that record.
- **Where it lives.** The Round-2 explanation is attached to
  `rounds[0].round2_trigger.explanation`, next to the `round2_record` it
  explains. If Round 2 executed, the executed Round-2 entry carries the
  same record again (`rounds[1].explanation`, equal content). That
  duplicate is one record represented twice, never two explanations:
  `evaluation_metrics.round2_explanation()` returns exactly one record per
  notebook (trigger copy first, entry copy only as a fallback).
- **Trace-only explanations.** A non-repairable Round-2 error executes no
  repair round, so under the unchanged one-row-per-executed-round
  ResultLogger contract it has **no `repair_attempts` row**. Its
  explanation exists in the trace only, and the trace is the authoritative
  source for every Round-2 explanation count.
- **Bound.** Reclassification and explanation happen at most once per
  notebook (after Round 1), inside the same `MAX_ROUNDS_HARD_CAP = 2`;
  there is no third-round explanation.

### The three metrics (record level)

The unit is the **final explanation result for one encountered dependency
error**, regardless of how many LLM attempts it took.

- **A. Original explanation schema validity**
  (`original_explanation_schema_validity_rate`; historical alias
  `explanation_schema_validity_rate` with its exact former shape) =
  valid original-failure explanations / **notebooks processed in the run**
  (187 for the evaluation split). Directly comparable with the frozen
  Gemma/Qwen runs; its denominator is never changed.
- **B. Round-2 explanation schema validity**
  (`round2_explanation_schema_validity_rate`) = valid Round-2
  explanations / **newly reclassified Round-2 errors that received an
  explanation record**, success or failed, *including* those later
  excluded from repair. It is **not** the repair-eligible subset, **not**
  the subset that reached the Round-2 repair LLM, and **not** the executed
  Round-2 row count. The report also gives `reclassified_new_errors`,
  `reclassified_without_explanation` (0 in a fresh run),
  `explained_repair_eligible`, and
  `explained_not_repair_eligible_trace_only`.
- **C. Combined explanation schema validity**
  (`combined_explanation_schema_validity_rate`) = (A valid + B valid) /
  (A processed + B processed). A descriptive total-reliability figure; it
  never replaces A.

### Records versus LLM attempts

The explainer retries once on a timeout, model-unavailability, or
schema-invalid response (`config/llm_explainer.yaml`). A retry is **not**
a second explanation record. Validity rates are computed over records;
`explanation.call_counts` separately reports `*_records` and
`*_llm_attempts` (the sum of each record's own `attempts`), plus
`records_with_retry`, for call-volume and cost reporting.

### Separation from repair metrics

A Round-2 explanation call is never a repair-agent invocation. Every
repair metric (abstention, eligibility, actual repair LLM attempts,
proposal validity, grounding, coverage, targeted-error resolution, full
recovery, infrastructure/method failure) is derived from `i4_result` /
`i5_result` entries only, and an explanation record is never an
`i4_result`. The Round-2 explainer therefore changes no repair metric's
definition or value; only explanation calls increase.

### Human evaluation scope

The human explanation-quality study (`docs/human-explanation-evaluation-
questionnaire.md`, `scripts/analyze_human_evaluation.py`) rated
**original-failure explanations only**, drawn from the frozen Gemma
evaluation run. No Round-2 explanation has been human-evaluated. Metrics
A/B/C are automated schema checks and must never be described as
human-evaluated quality.

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
`config/llm_explainer.yaml`, `config/fix_applicator.yaml` (hashed at the
config paths the run actually loads, so a machine-local override such as
`config/fix_applicator.evaluation.local.yaml` is hashed as itself). It never
reads or stores `.env` contents. `scripts/run_evaluation.py` refuses to
resume under an existing `run_id` if any of these frozen fields drifted
since the last manifest for that `run_id`
(`evaluation_manifest.ManifestConsistencyError`).

Three provenance fields were added for the Round-2-explanation reruns and
are absent from the frozen I8/I9 manifests (which therefore still validate
exactly as before):

- `code_hashes` - SHA-256 of the component source files that determine
  behaviour (`scripts/run_pipeline.py`, `run_llm_explainer.py`,
  `rag_repair_agent.py`, `fix_applicator.py`, `result_logger.py`,
  `evaluation_metrics.py`). `git_commit_sha` identifies HEAD, not the
  working tree; the code hash identifies what actually ran. Compared on
  resume and by `validate_evaluation_results.py` only when a manifest
  recorded it.
- `git_working_tree_dirty` - whether the SHA fully identifies the code.
- `orchestrator_features.round2_explanation` - derived by inspecting
  `scripts/run_pipeline.py` for `explain_round_record()`, never asserted
  by hand, so a run's manifest states whether newly exposed Round-2 errors
  were explained.

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
    table_9_explanation_schema_validity.csv   # metrics A/B/C + record/attempt counts
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

Separately from I8, the LLMExplainer human evaluation was carried out as a
six-item Explanation-Satisfaction-Scale study over 12 frozen
**original-failure** explanations drawn only from the evaluation split's
own outputs (`docs/human-explanation-evaluation-questionnaire.md`,
`scripts/select_human_evaluation_pool.py`,
`scripts/analyze_human_evaluation.py`). Dev-split explanations were
excluded because two dev records (notebook 8, sklearn; notebook 174, scipy
cumtrapz) are the frozen few-shot examples baked into
`prompts/dependency_explanation_v1.txt`, and the rest of `dev` was used
for prompt development. Round-2 explanations were not part of that study
(see "Explanation metrics" / "Human evaluation scope").

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
