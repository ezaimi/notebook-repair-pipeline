# Round-2 LLMExplainer: evaluation methodology freeze for the final reruns

This note freezes the experimental design and metric definitions for the
final evaluation reruns that follow the Round-2 LLMExplainer change to
`scripts/run_pipeline.py`. It supplements, and does not replace,
`docs/i8-evaluation-methodology.md` (metric definitions, now including the
"Explanation metrics" section), `docs/i8-pre-final-evaluation-freeze.md`
(the original Gemma freeze, historical), and
`docs/i9-qwen-model-sensitivity-freeze.md` (the original Qwen freeze,
historical). The frozen result directories under `data/evaluation/` from
those runs are unchanged and remain the authoritative record of the
pre-Round-2-explanation behaviour.

## What changed in the pipeline (and what did not)

Changed - explanation only:

- After Round 1, a genuinely new dependency error
  (`still_failing`, `same_as_original_error == False`, new error present)
  is reclassified into a `round2_record` with the same two classifier
  stages every original row went through, and is then **explained by
  LLMExplainer as its own record**, from that reclassified record, before
  repair eligibility is evaluated.
- Explanation scope is broader than repair scope, exactly as in Round 1:
  a newly exposed `system_library`, `mapping_unknown`, or otherwise
  non-repairable error is still explained. Repair eligibility does **not**
  control whether it is explained.
- Only repair-eligible reclassified records proceed to RAGRepairAgent and
  FixApplicator (Round 2), unchanged.
- Explanation failure (timeout, model unavailable, malformed output,
  exhausted retry, unexpected exception) is non-blocking: the repair round
  still runs for an eligible record.
- Round 2 remains capped at one additional repair round
  (`MAX_ROUNDS_HARD_CAP = 2`); reclassification + explanation happen at
  most once per notebook, so there is no third explanation.
- Each `repair_attempts` row stores its own round's explanation and
  explanation metadata (`llm_model`, `prompt_strategy`): Round 1 -> the
  original failure, Round 2 -> the newly exposed error. Schema unchanged.

Not changed - repair:

- Prompts, few-shot examples, schemas, `config/package_mapping.yaml`,
  PyPI retrieval, grounding validation, FixApplicator, Round-2 eligibility
  rules, the cumulative Round-1 + Round-2 container, the one-row-per-
  executed-round ResultLogger contract, and every repair metric definition.
- RAGRepairAgent receives the same classified Round-2 record and the same
  PyPI evidence as before; it never sees the explanation.

## Explanation population and metrics (frozen)

Defined in full in `docs/i8-evaluation-methodology.md` -> "Explanation
metrics". In brief, all record-level (one record per encountered error;
retries are attempts, not records):

| Metric | Numerator | Denominator |
|---|---|---|
| A `original_explanation_schema_validity_rate` (alias `explanation_schema_validity_rate`, unchanged) | valid original-failure explanations | notebooks processed in the run (187 for `evaluation`) |
| B `round2_explanation_schema_validity_rate` | valid Round-2 explanations | newly reclassified Round-2 errors that received an explanation record - **including** non-repairable ones that exist in the trace only |
| C `combined_explanation_schema_validity_rate` | A + B valid | A + B records |

Derived counts reported alongside (`explanation.call_counts`, `table_9`):
original / Round-2 / total explanation records; valid / failed for each;
`reclassified_new_errors`, `reclassified_without_explanation` (0 in a
fresh run), `explained_repair_eligible`,
`explained_not_repair_eligible_trace_only`; and `*_llm_attempts_incl_retries`.
None of these counts is hardcoded: the rerun determines its own
denominators. (The frozen Gemma trace shows 50 reclassified new errors,
48 eligible + 2 excluded; the rerun's own numbers govern.)

Trace representation, and why it is not double counting: the Round-2
explanation lives on `rounds[0].round2_trigger.explanation`; an executed
Round 2 repeats the same record on `rounds[1].explanation`.
`evaluation_metrics.round2_explanation()` returns exactly one record per
notebook (trigger first, entry only as fallback), and
`validate_evaluation_results.check_round2_entry_explanation_matches_trigger`
confirms the two copies are equal. A non-repairable Round-2 error has no
Round-2 entry and no `repair_attempts` row; its explanation is trace-only.

Repair metrics are computed from `i4_result` / `i5_result` entries only;
an explanation record is never an `i4_result`, so a Round-2 explanation
call cannot be counted as a repair-agent invocation
(`test_repair_invocation_counts_are_unchanged_by_round2_explanations`).

## Integrity checks added (`scripts/validate_evaluation_results.py`)

All pass trivially on traces that predate Round-2 explanations, so the
frozen runs re-validate as before.

- `round2_explanations_well_formed` - every Round-2 explanation is tagged
  `round == 2` and its `input` equals the `round2_record` it explains.
- `round2_entry_explanation_matches_trigger` - executed Round-2 entries
  carry the same Round-2 explanation as the trigger.
- `no_round3_explanation` - no explanation tagged above 2; no
  `round2_trigger` on a Round-2 entry; no rounds entry outside 1..2.
- `top_level_explanation_is_round1` - the top-level explanation is still
  the original failure's (metric A reads it).
- `non_repairable_round2_explanations_are_trace_only` - a reclassified,
  non-eligible new error has no executed Round-2 entry and no round-2 row.
- `round2_explanation_failure_did_not_block_repair` - a failed Round-2
  explanation on a triggered record still has an executed Round-2 entry.
- `single_run_id` now also covers Round-2 explanation `run_id`s.
- `manifest_config_hash_consistency` also compares `code_hashes` when the
  manifest recorded them.

## Provenance additions (`scripts/evaluation_manifest.py`)

`code_hashes` (component source SHA-256s), `git_working_tree_dirty`, and
`orchestrator_features.round2_explanation` (derived from
`scripts/run_pipeline.py`, not asserted). Old manifests lack these keys and
are compared exactly as before; `config_hashes` keys are unchanged.

## Model-sensitivity comparison

There is no automated comparison script; the Gemma-vs-Qwen comparison
(`docs/i9-qwen-vs-gemma-comparison.md`, frozen, not modified) was assembled
from each run's `summary/evaluation_summary.csv` and `tables/`. The rerun
outputs flatten the explanation block into `evaluation_summary.csv`
(`explanation.<block>.<field>` rows) and write `table_9`, so the next
comparison must report three explanation rows - original, Round-2,
combined - for each model, separately from the repair rows, instead of the
single "Explanation schema validity" row the old comparison used.

## Human evaluation

Unchanged. The human study rated original-failure explanations only, from
the frozen Gemma run. Metrics A/B/C are automated schema checks; no wording
in the tooling or its outputs describes Round-2 explanations as
human-evaluated (`table_9`'s note states this explicitly).

## Freeze status

Frozen for the reruns once the working tree is committed. Note for the
manifest: `git_commit_sha` records HEAD; if the rerun is made on an
uncommitted tree the manifest's `git_working_tree_dirty` will be `true`
and `code_hashes` identifies the code that actually ran. Committing first
is preferable so the SHA alone is sufficient.

Known, pre-existing item that this freeze does not change: the frozen
Gemma manifest (`i8-eval-final-rerun-20260913T113423Z`) recorded the hash
of `config/fix_applicator.yaml` although the run used
`config/fix_applicator.evaluation.local.yaml` (already documented as the
thesis's provenance note). With the current path-aware validator, that
frozen manifest reports `manifest_config_hash_consistency` as failed for
`fix_applicator_config`; its stored `validation_report.json` predates the
path-aware check and is left untouched. New manifests hash the actual
path, so this cannot recur.
