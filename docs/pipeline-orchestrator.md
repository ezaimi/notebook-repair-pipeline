# PipelineOrchestrator (i7)

## 1. Purpose

PipelineOrchestrator sequences the already-implemented components - ErrorClassifier (i1/i2),
LLMExplainer (i3), RAGRepairAgent (i4), FixApplicator (i5), and ResultLogger (i6) - into one
pipeline invocation per dependency-error record, and adds the one piece none of them owned
individually: a bounded, two-round repair loop with one shared run identifier threading through
every stage.

It does not reimplement classification, PyPI retrieval, proposal validation, command construction,
Docker execution, or result logging. Every one of those stays exactly where i2-i6 already put it;
`scripts/run_pipeline.py` only calls their existing functions in sequence and makes the small,
backwards-compatible plumbing changes needed to carry a shared `run_id` and a cumulative fix list
between rounds (§8, §9).

## 2. Component sequence

```text
i2-classified record
        |
  LLMExplainer (i3)                          -- always, every record, all 214 rows
        |
  repair eligibility check (scope_status)     -- reused from rag_repair_agent.check_eligibility()
        |  (usable only - excluded/invalid records stop here)
  RAGRepairAgent (i4)  -- run_repair_agent()
        |
  FixApplicator (i5)   -- apply_and_validate(): clone -> checkout -> build -> run -> classify
        |
  ResultLogger (i6)    -- build_repair_attempt_row() + insert_row()
        |
  repair_attempts (SQLite)
```

`scripts/run_pipeline.py` implements this as two Python functions:

- `explain_record()` - identical per-record body to `run_llm_explainer.py`'s own CLI loop
  (`render_record_prompt`, `explain_one`, `build_input_metadata`, `build_llm_metadata`), called for
  every selected record regardless of repair eligibility.
- `process_record()` - the repair eligibility check plus the bounded repair-round loop (§6, §7).

## 3. Explanation scope vs. repair scope

Unchanged from `docs/architecture-note.md` §7.1, and enforced by construction rather than by a new
rule: `process_record()` always calls `explain_record()` first, then separately calls
`rag_repair_agent.check_eligibility(record)` to decide whether to proceed into a repair round.

- **All 214 records** go through `explain_record()`. The 200 `scope_status == "usable"` rows also go
  through Round 1; the 14 `scope_status == "excluded"` rows (10 `system_library`, 4
  `mapping_unknown`) do not.
- For an excluded (or `scope_status`-invalid) record, `process_record()` calls
  `build_excluded_repair_stub()` instead of `rag_repair_agent.run_repair_agent()`.
  `build_excluded_repair_stub()` reuses `run_repair_agent`'s own exported `check_eligibility()` and
  `_base_result()` helpers to build the *exact same* abstained result shape `run_repair_agent()`
  would produce for that record - without ever calling `run_repair_agent()` (or, by construction,
  `fix_applicator.apply_and_validate()`) itself. This is what "an excluded record must still be
  explainable but must never call RAGRepairAgent or FixApplicator" means at the code level: not a
  behavioral difference in the result, a difference in which function produces it.
- One `repair_attempts` row is still logged for an excluded record (`round=1`, `action="none"`,
  `outcome=NULL`), matching the pre-i7 architecture's own documented contract
  (`docs/architecture-note.md` §7.3: "LLMExplainer's output reaches ResultLogger for every row,
  independent of repair eligibility") and the existing `tests/test_result_logger.py` fixtures. This
  is not a new rule i7 introduces; it is the historical CLI-batch behavior, reproduced without ever
  making the LLM/network calls that behavior implies for an excluded row (which the CLI-batch
  workflow was always cheap for anyway, since `check_eligibility()` already aborted before any real
  work - i7 just proves that formally by never calling the function at all).
- Eligibility is never redefined or re-derived: both the top-level check and the excluded-row stub
  read `scope_status`/`exclusion_reason` exactly as i1/i2 already computed them.

## 4. Round 1

For a usable record, `run_repair_round()` is called once:

```python
i4_result = rag_repair_agent.run_repair_agent(record, repair_config, run_id=run_id)
i5_result = fix_applicator.apply_and_validate(
    i4_result, i2_index, fix_config,
    repository_metadata_lookup=..., runner=..., run_id=run_id,
    work_dir_base=..., prior_fix_argvs=None,
)
```

Both are the real, unmodified component functions. `apply_and_validate()` is called for *every*
usable record's Round 1, regardless of whether `run_repair_agent()` succeeded, abstained, or
failed - its own `resolve_attempt()` already decides "skip" (zero subprocess calls) for anything
that is not `status == "success"` with `final_action != "none"`. The orchestrator reuses that gate
instead of re-implementing "should FixApplicator even try" itself.

`RAGRepairAgent status == "success"` is never read as "the notebook is fixed" - the orchestrator
never inspects `i4_result["status"]` to decide the repair outcome; only `i5_result["outcome"]`
(`fixed` / `still_failing` / `apply_error`, or `None` when Round 1 never actually executed) means
anything for that. This mirrors `docs/fix-applicator.md`'s own "Outcome semantics" section:
proposal generation (i4) and applied-repair outcome (i5) stay two separate judgments, joined only
for logging.

## 5. The bounded second round

### 5.1 Exact trigger (`evaluate_round2_trigger()`)

A pure function, no I/O, no LLM call - given Round 1's `i5_result` and the *original* record, it
returns `{"triggered": bool, "reason": str, "round2_record": {...}}`. Round 2 is triggered only when
**all** of the following hold, checked in this order:

1. `i5_result is not None` and `i5_result["outcome"] == "still_failing"` - Round 1 must have actually
   run the fix and re-executed the notebook (not `apply_error`, not `fixed`, not "skipped" because
   `run_repair_agent()` never produced an actionable proposal).
2. `i5_result["new_error_type"]` is present - there is a genuinely new error to reclassify.
3. `i5_result["same_as_original_error"]` is `False`. **This flag alone never triggers Round 2, only
   ever stops it early** - a `True` value is an immediate stop; a `False` value is necessary but not
   sufficient, since step 4 still has to hold.
4. The new failure, reclassified from scratch (§5.2), has `scope_status == "usable"` **and**
   `refined_subtype` in `{"missing_package", "wrong_version"}` under i1/i2's own existing rules -
   exactly the same pip-only scope test every original record already passed.

Any other outcome - the same original error, a non-dependency error, a `system_library` error, a
`mapping_unknown` (ambiguous local module) error, or anything else i1's classifier excludes - stops
at step 4 with `triggered: False` and a `reason` string identifying which check failed, plus the
reclassified `round2_record` for diagnostics even when it was not eligible.

### 5.2 Reclassifying the new failure (`build_round2_record()`)

Reuses i1's and i2's own classification functions, unmodified, on the *new* error:

- `prepare_dependency_dataset.extract_failing_module(new_error_message)` - the same regex-based
  extraction i1 uses for every dataset row.
- `prepare_dependency_dataset.classify(new_error_type, new_error_message, new_failing_module)` - i1's
  authoritative `(subtype, scope_status, exclusion_reason)` decision. This is the source of truth
  for eligibility; it is never re-derived by hand.
- `extract_error_contexts.classify_refined(...)` - i2's refinement, for `root_cause_hint`/
  `confidence` (kept for provenance/prompt-rendering parity with an original i2 row, not for the
  eligibility decision itself).

Notebook/repository identity (`notebook_execution_id`, `repository_id`, `notebook_id`,
`notebook_name`, `repository_url`, `split`) is copied unchanged from the original record - it is the
same notebook. **No source context is invented**: `build_round2_record()` never sets
`prompt_context`, since the new failure was never re-fetched from GitHub or the legacy `executions`
table. `render_repair_prompt()`/`render_record_prompt()` already fall back to `"Not available"` for
any record lacking `prompt_context` (this is existing, unmodified behavior in both render modules;
no new fallback was added), so Round 2's prompt is honest about what it does and does not know
about the failing cell.

### 5.3 Worked example (real, documented case)

```text
Original (notebook_execution_id=174):
  ImportError: cannot import name 'cumtrapz' from 'scipy.integrate'
        |
Round 1: RAGRepairAgent proposes pin_version scipy==1.13.1 (grounded in
         config/api_compatibility_evidence.yaml's scipy.integrate.cumtrapz entry)
        |
FixApplicator re-executes -> outcome: still_failing
  new_error_type: ModuleNotFoundError
  new_error_message: "No module named 'tf_keras'"
  same_as_original_error: False
        |
evaluate_round2_trigger(): reclassify "No module named 'tf_keras'"
  -> failing_module "tf_keras", subtype missing_package, scope_status usable
  -> triggered: True
        |
Round 2: RAGRepairAgent called for the *new* record (tf_keras), never the
         original scipy record
```

This is the exact case documented in `docs/i5-live-validation.md` Case 2, run for real again as
part of i7's own pilot validation - see `docs/pipeline-orchestrator.md` §12 for what actually
happened when Round 2 ran for it.

## 6. Maximum two rounds

`MAX_ROUNDS_HARD_CAP = 2` is a module-level constant in `scripts/run_pipeline.py`, independent of
whatever `--max-rounds` is passed. `process_record()`'s round loop always computes
`effective_max_rounds = min(max_rounds, MAX_ROUNDS_HARD_CAP)` and never evaluates
`evaluate_round2_trigger()` once `round_number >= effective_max_rounds` - so even a caller that
passes `max_rounds=99` directly to `process_record()` (bypassing the CLI) can never produce a third
round; there is no code path that re-enters the loop after Round 2 completes.

At the CLI layer, `--max-rounds` uses `argparse`'s `choices=[1, 2]`, so `--max-rounds 3` is rejected
before the run even starts, with argparse's own usage-error message.

- `--max-rounds 1`: `effective_max_rounds = 1`; the loop breaks immediately after Round 1, and
  `evaluate_round2_trigger()` is never called at all (not "called and ignored" - simply not
  reached).
- `--max-rounds 2`: Round 2 runs if and only if §5.1's trigger fires.

## 7. Round 2 input construction

Round 2 calls the exact same `run_repair_round()` function as Round 1, with two differences: the
record passed in is `round2_record` (§5.2), not the original record, and `prior_fix_argvs` (§8) is
non-empty. RAGRepairAgent and FixApplicator have no separate "round 2" code path of their own - the
orchestrator is the only thing that knows there are rounds at all.

Provenance is preserved end-to-end in the orchestrator's own diagnostics (not in the
`repair_attempts` row, which has no room for it and does not need it - see §9): each record's
trace entry in the per-run JSONL log (`--output-dir`) carries, per round, the full `i4_result`
(proposal), the full `i5_result` (outcome), and - on Round 1's entry - the full
`round2_trigger` decision including the reclassified `round2_record`. Reading Round 1's and Round
2's entries for the same `notebook_execution_id` together gives the complete chain: original
failure -> Round 1 proposal -> Round 1 outcome -> new failure -> Round 2 proposal -> Round 2
outcome.

## 8. Cumulative Round 1 + Round 2 environment

This is the trickiest correctness requirement, and the one most tied to FixApplicator's actual
architecture rather than an idealized one.

**The problem.** `docs/fix-applicator.md` and `docker_runner.py`'s own module docstring are explicit
that FixApplicator never reuses a container: the upstream Docker pipeline's per-repository
containers/images were never persisted on this machine, and even if they had been, i5 rebuilds a
fresh, uniquely-named container/work-dir/image on *every* attempt as its isolation guarantee
(`docker_runner.make_attempt_names()`). A naive Round 2 call - `apply_and_validate()` again, with
the Round 2 argv and nothing else - would therefore rebuild the environment from the *original*
base image and baseline `requirements.txt`/`setup.py` install loop, apply only the Round 2 fix, and
run the notebook: Round 1's fix would simply never have happened in that container. That would
silently test "original environment + Round 2 only," not "original environment + Round 1 + Round
2," and any `fixed`/`still_failing` outcome from it would misrepresent what was actually verified.

**The chosen strategy: re-apply, not reuse.** Since no Round 1 container survives to be reused
(nothing does, by design - see above), i7 makes Round 2's freshly-rebuilt container reproduce Round
1's effect deterministically, by re-running Round 1's own already-validated pip command inside it,
immediately before Round 2's own fix:

```text
Round 2 container build:
  base image + baseline requirements.txt/setup.py loop   (unchanged, as in Round 1)
  + python -m pip install scipy==1.13.1                  (Round 1's fix, re-applied)
  + python -m pip install tf-keras                       (Round 2's fix)
  -> notebook re-execution
```

This is the smallest change that makes "original environment + Round 1 + Round 2" true without
inventing any stateful Docker commit/checkpoint machinery the rest of the architecture does not
have. It is deterministic (the exact same validated argv, replayed) rather than incremental
(no attempt to diff or snapshot a live container), which keeps it consistent with every other
FixApplicator guarantee: every attempt is a clean, reproducible rebuild.

**Implementation.** Two small, backwards-compatible signature additions, both defaulting to "do
nothing different" so every pre-i7 caller and test is unaffected:

- `docker_runner.write_build_context(build_dir, fix_argv, prior_fix_argvs=None)` - when
  `prior_fix_argvs` is given, each prior argv is rendered through the *same*
  `render_fix_command()` safety check as the primary `fix_argv` (never a raw LLM string; every
  token still passes `is_safe_shell_word()`), and a `FIX_INSTALL_SUCCESS`/`FIX_INSTALL_FAILED`
  block for each prior fix is written into `entrypoint.sh` *before* the primary fix's own block.
  When `prior_fix_argvs` is `None`/empty (every call site before i7, and `fix_applicator.py`'s own
  CLI), the generated `entrypoint.sh` is byte-identical to the pre-i7 template - proven by the full
  pre-existing `tests/test_docker_runner.py` suite passing unmodified.
- `fix_applicator.apply_and_validate(..., prior_fix_argvs=None)` - forwards the parameter straight
  to `write_build_context()`. Nothing else in `apply_and_validate()` changes; `resolve_attempt()`,
  the Docker/git call sequence, and outcome classification are all untouched.

The orchestrator supplies `prior_fix_argvs` itself: after a Round 1 whose `i5_result["outcome"] ==
"still_failing"` triggers Round 2, `process_record()` collects `i5_result["argv"]` (the argv
`apply_and_validate()` independently rebuilt and validated, not the raw i4 proposal) into a list and
passes it as `prior_fix_argvs` on the Round 2 call. Because `MAX_ROUNDS_HARD_CAP == 2`, this list
never grows past one element in practice, but it is a list (not a single optional argv) so the
mechanism does not need to change shape if a future issue ever revisits the two-round limit.

**No raw LLM shell strings, ever.** Both Round 1's and Round 2's fixes reach the container only as
already-validated, deterministically-constructed argv (`rag_repair_agent.build_argv()`), re-checked
by `resolve_attempt()`'s own independent argv rebuild before either round's Docker call. Nothing
about the cumulative mechanism changes this: `render_fix_command()`/`render_fix_commands()` reject
any unsafe token before writing anything, for the prior fix exactly as for the primary one.

**Tests.** `tests/test_docker_runner.py` gained no new assertions on the *existing* tests (they all
still pass against the byte-identical single-fix template); the cumulative behavior itself is
proven in `tests/test_run_pipeline.py::test_round1_still_failing_new_eligible_error_triggers_round2`,
which captures the actual generated `entrypoint.sh` at Round 2's "docker build" call and asserts
Round 1's fix command appears, textually before Round 2's, inside it.

## 9. Shared orchestration-level `run_id`

Before i7, `run_llm_explainer.py`, `rag_repair_agent.py`, and `fix_applicator.py` each minted their
own `i3-<timestamp>` / `i4-<timestamp>` / `i5-<timestamp>` run id per CLI invocation
(`docs/architecture-note.md` §7.3 flags this explicitly as left to i7). All three already accepted
- or, for `run_llm_explainer`'s per-record body, could trivially reuse - an externally supplied
value; **no signature change was needed in any of them**:

- `rag_repair_agent.run_repair_agent(record, config, run_id=None)` already accepted an optional
  `run_id` override (defaulting to its own `i4-<timestamp>` only when omitted). The orchestrator
  passes `run_id=<shared i7 run id>` on every call.
- `fix_applicator.apply_and_validate(..., run_id=None)` - same existing parameter, same treatment.
- `run_llm_explainer.explain_one()` does not stamp a run id itself; the orchestrator's own
  `explain_record()` wraps its result in the same `{"run_id": ..., "created_at": ..., "input": ...,
  "llm": ..., "explanation_result": ...}` shape the i3 CLI already produces, using the shared run id
  directly (mirroring exactly what the CLI's own `main()` does with its own single per-invocation
  `run_id`).

One `run_id` (`i7-<UTC timestamp>`, e.g. `i7-20260911T143000Z`, or an explicit `--run-id`) is
generated once per orchestrator invocation and threaded through every call for every record and
every round it processes in that invocation. It is what ends up in `repair_attempts.run_id` for
every row that invocation writes - the column ResultLogger already had (§6.2 of
`docs/architecture-note.md`) now means exactly what its name says for an orchestrated run, without
any schema change.

**Component-local metadata is not destroyed.** Each component's own detailed result (`i4_result`'s
`retrieval_result`/`llm`/`schema_validation`/`extracted_signature`, `i5_result`'s
`commit_checkout_status`/`execution_status`/`elapsed_seconds`) is untouched and fully preserved -
`run_id` is one field among many in each result dict, and only its value changed (from an
auto-generated timestamp to the caller-supplied one). Nothing about *how* a component builds its
own diagnostic record was altered.

## 10. Per-round `repair_attempts` logging

No new database schema. `result_logger.create_table()`, `build_repair_attempt_row()`, and
`insert_row()` are reused exactly as i6 left them - **no changes were made to
`scripts/result_logger.py`**. `build_repair_attempt_row(i4_record, i2_row, i3_record, i5_record,
round_number)` already operates on in-memory dicts, not files, so the orchestrator calls it
directly once per round:

- Round 1: `i2_row` is the original record; `i3_record` is that record's own explanation result;
  `i5_record` is Round 1's `apply_and_validate()` result (or `None` if it never actually executed -
  see below); `round_number=1`.
- Round 2: `i2_row` is `round2_record` (so `failing_module`/`subtype` in the row describe *this*
  attempt's own target, e.g. `tf_keras`/`missing_package`, not the original notebook's first
  failure); `i3_record` is `None` (no explanation was generated for the newly-discovered failure -
  explanation scope is the 214 original records, not every failure a repair round happens to
  surface; see §3); `round_number=2`.

**One subtlety not present in the pre-i7 CLI-batch workflow:** `apply_and_validate()` is now called
for *every* usable round (§4), including ones where `run_repair_agent()` abstained or failed (its
own `resolve_attempt()` correctly turns that into a zero-subprocess-call `"skipped"` result). Passing
that `"skipped"` result to `build_repair_attempt_row()` as `i5_record` would show `action: None`
instead of the more informative `action: "none"` i4 itself decided (`_base_attempt_result()`'s
default fields are `None`, not `i4`'s own `"none"` string). The orchestrator therefore only passes
`i5_result` to `build_repair_attempt_row()` when it represents an actual attempt
(`i5_result["status"] == "completed"` - `fixed`/`still_failing`/`apply_error`); a `"skipped"` result
falls back to `i4_record`'s own fields, exactly as `build_repair_attempt_row()` already does when no
i5 record exists at all. This is a one-line orchestration policy, not a change to
`build_repair_attempt_row()` itself.

One repair attempt is still exactly one row: a notebook repaired across two rounds produces two
`repair_attempts` rows with the same `notebook_execution_id` and `run_id`, `round=1` and `round=2`
respectively - never collapsed, never overwritten.

## 11. Failure isolation

`process_record()` never lets a single component exception escape past the round it happened in:

- `explain_record()` cannot raise for a network/model/schema failure - `explain_one()` already
  catches `TimeoutError`/`socket.timeout`, `urllib.error.URLError`, and any other `Exception`
  internally and returns a `status: "failed"` result with a `failure_category`; only a
  `render_record_prompt()` `KeyError` (an unexpected template placeholder) is caught by
  `explain_record()` itself, producing a `"render_failed"` result instead of propagating.
- `run_repair_round()` (RAGRepairAgent + FixApplicator for one round) is called inside a `try/except
  Exception` in `process_record()`'s round loop; any exception - PyPI unreachable, a malformed
  config, a clone/checkout/build failure that somehow escapes `DockerRunnerError`'s own handling, an
  unexpected bug - is caught, recorded as `{"round": n, "status": "component_error", "error": ...}`,
  and stops *further rounds for that record only*. It never aborts the batch.
- The CLI's own `main()` loop wraps each `process_record()` call in a further `try/except Exception`,
  so even a bug inside `process_record()` itself that this design did not anticipate cannot take
  down the next record's processing - it is recorded in that record's trace line as
  `"orchestrator_error"` and the loop continues.
- No unbounded retries are introduced anywhere. LLMExplainer's and RAGRepairAgent's own bounded
  retry policies (`config/llm_explainer.yaml`, `config/rag_repair.yaml` - `retry.max_retries`,
  currently 0-1) are reused unchanged; the orchestrator adds no retry loop of its own at any level.
- A genuinely catastrophic startup failure - a missing config file, an unreadable i2 dataset, an
  invalid prompt template - still raises and stops the run before the per-record loop begins. That
  is deliberate: there is no sensible per-record recovery from "the input dataset does not exist."

## 12. Small real integrated pilot

Performed with real Ollama (`gemma2:9b`), real PyPI, and real Docker - never mocked - against two
`--split dev` records (never the reserved 187-row evaluation split). Artifacts: the resulting
`repair_attempts.sqlite` and per-record JSONL traces are checked into `data/repair-attempts/` and
`data/pipeline-runs/` (untracked until a commit is explicitly requested).

### 12.1 Pilot A - normal Round 1 orchestration (`notebook_execution_id=8`, sklearn)

```text
python scripts/run_pipeline.py --split dev --start-index 0 --limit 1 --max-rounds 2 \
  --run-id i7-pilot-20260911-sklearn
```

- **Round 1:** RAGRepairAgent proposed `install scikit-learn` (grounded in a real PyPI lookup);
  FixApplicator cloned `mdjaffardjy/AnalyseDonneesNextflow` at its recorded commit, installed
  `scikit-learn`, and re-executed the notebook -> `outcome: still_failing`, new error
  `ModuleNotFoundError: No module named 'pandas'`, `same_as_original_error: false`. This exactly
  reproduces the real case already documented in `docs/i5-live-validation.md` Case 1.
- **Round 2 trigger:** fired (`pandas` reclassifies to `missing_package`/`usable`).
- **Round 2:** RAGRepairAgent was called for real against `pandas` and **abstained**
  (`final_action: none`) after two attempts, both `invalid_json`. The raw model output shows why:
  `pandas` has an unusually large number of legacy Windows `.exe` release artifacts, each producing
  a `pypi_retriever` "skipping unparseable filename" warning that gets embedded in the repair
  prompt's evidence block; `gemma2:9b` responded by hallucinating a JSON object that echoes that
  warning text back instead of proposing a fix. This is a genuine, unforced model failure mode on a
  large/noisy real prompt, not a bug in the orchestrator - and it is exactly the kind of malformed
  proposal RAGRepairAgent's existing schema validation is built to catch and abstain from safely.
  FixApplicator's Round 2 call correctly never touched Docker (`status: "skipped"`).
- **Logged rows:** two, both `run_id=i7-pilot-20260911-sklearn` - `round=1` (`action=install`,
  `outcome=still_failing`) and `round=2` (`action=none`, `outcome=NULL`).

### 12.2 Pilot B - the documented SciPy/cumtrapz case, with a real Round 2 attempt (`notebook_execution_id=174`)

```text
python scripts/run_pipeline.py --split dev --start-index 11 --limit 1 --max-rounds 2 \
  --run-id i7-pilot-20260911-scipy-cumtrapz-retry
```

- **Round 1:** RAGRepairAgent proposed `pin_version scipy==1.13.1` (grounded in
  `config/api_compatibility_evidence.yaml`'s real `scipy.integrate.cumtrapz` entry); FixApplicator
  cloned `zincware/MDSuite` at its recorded commit, installed `scipy==1.13.1`, and re-executed the
  notebook (334.5s) -> `outcome: still_failing`, new error `ModuleNotFoundError: No module named
  'tf_keras'`, `same_as_original_error: false`. This exactly reproduces
  `docs/i5-live-validation.md` Case 2.
- **Round 2 trigger:** fired (`tf_keras` reclassifies to `missing_package`/`usable` - confirmed by
  direct reclassification before any Round 2 call was made, per the task's own instruction to check
  this rather than assume it).
- **Round 2:** RAGRepairAgent was called for real against `tf_keras` and **abstained** -
  `pypi_retriever.retrieve()` returned `status: "mapping_unknown"` because `tf_keras` has no entry
  in `config/package_mapping.yaml` (unlike `cv2`, which was added to that file during i4's own live
  validation for the same reason). **This confirms, rather than assumes, that the documented
  tf_keras case cannot currently be mapped and handled end-to-end by the existing repair logic** -
  exactly the check the task asked for before treating it as a Round 2 success story. No mapping
  entry was added to force a different outcome: doing so would be tuning RAGRepairAgent's own
  scope/config to manufacture a demo result, which is outside i7's scope (orchestration, not
  repair-agent coverage expansion). FixApplicator's Round 2 call correctly never touched Docker.
- **Environment note:** the first attempt at this pilot (`run_id=i7-pilot-20260911-scipy-cumtrapz`,
  also in `data/pipeline-runs/`) hit a real but environment-specific failure unrelated to the
  orchestrator's own logic: the session's deeply-nested scratch work-dir path exceeded Windows' git
  path-length limit while writing a pack `.keep` file, producing a correctly-classified
  `apply_error`/`clone` result. Re-run with `--work-dir` pointed at a short path succeeded as
  described above; this is recorded here for transparency rather than discarded.
- **Logged rows:** two, both `run_id=i7-pilot-20260911-scipy-cumtrapz-retry` - `round=1`
  (`action=pin_version`, `outcome=still_failing`) and `round=2` (`action=none`, `outcome=NULL`).

### 12.3 What this pilot does and does not show

Both real Round 2 attempts ended in a clean, correctly-logged abstention rather than a successful
second repair - for two different, genuine reasons (a noisy-prompt model failure; a missing PyPI
mapping), neither fabricated or forced. This is still a complete, valid demonstration of every
mechanical claim i7 makes about Round 2: the trigger condition fires only when it should, the new
failure is correctly reclassified and targeted, RAGRepairAgent and FixApplicator are reused
unmodified, the shared `run_id` and cumulative-environment mechanism are exercised for real, and an
abstained/failed Round 2 is logged as cleanly as a successful one would be. Round 2 tests aiming
specifically to prove a *successful* second repair (with a controlled, always-mappable synthetic
package) are covered instead by `tests/test_run_pipeline.py`'s mocked suite, per the task's own
guidance not to force a real example to succeed when the evidence does not support it.

## 13. Boundary with the final evaluation (out of scope for i7)

i7 delivers: an orchestrator that runs the full sequence for a given slice of records, a working
bounded-second-round mechanism validated by both controlled tests and a small real pilot, and
correctly-shaped `repair_attempts` rows that i6's own export/RML pipeline can later consume
unchanged.

i7 does **not** perform: the full 187-row evaluation, a final repair success-rate calculation, a
final one-round-vs-two-round comparison, full benchmark/KG population, or the user study/Likert/
Cohen's kappa analysis. Those all consume the orchestrator built here; none of them were run as
part of building it.

## 14. CLI reference

```text
python scripts/run_pipeline.py \
  --split dev --start-index 0 --limit 1 --max-rounds 2
```

| Flag | Default | Meaning |
|---|---|---|
| `--i2` | `data/context-classification/dependency_error_contexts.jsonl` | i2-classified input. |
| `--split` | `dev` | `dev` / `evaluation` / `excluded` / `all`. Defaults to `dev` deliberately - see §15. |
| `--start-index` | `0` | Offset into the *selected split*, not the raw file. |
| `--limit` | `1` | Max records to process. |
| `--max-rounds` | `2` | `1` or `2` only (`argparse choices`); `--max-rounds 3` is rejected at startup. |
| `--model` | config default | Overrides the Ollama model for both LLMExplainer and RAGRepairAgent. |
| `--prompt-strategy` | config default | Overrides LLMExplainer's `prompt.strategy`. |
| `--run-id` | `i7-<UTC timestamp>` | Shared orchestration-level run id (§9). |
| `--output-dir` | `data/pipeline-runs` | Where the per-record JSONL trace (`<run_id>.jsonl`) is written. |
| `--database` | `data/repair-attempts/repair_attempts.sqlite` | The (reused, unmodified) i6 schema. |
| `--overwrite` | off | Drops and recreates `repair_attempts` first; see §15. |
| `--explainer-config` / `--repair-config` / `--fix-config` | the existing `config/*.yaml` | Override any component's config file. |
| `--work-dir` | system temp dir | Base directory for FixApplicator's per-attempt work dirs. |

## 15. Resume / overwrite behaviour

Kept intentionally simple, proportionate to a thesis pipeline rather than a general workflow engine:

- **Output already exists** (`--database` file, or a trace file under `--output-dir` for the same
  `--run-id`): by default, rows are *appended* - matching `result_logger.py`'s own long-standing
  convention that `repair_attempts` accumulates across runs/configs (`docs/architecture-note.md`
  §6.2: "re-running the same targets under a different model or prompt produces further rows"). The
  trace file for a given `run_id` is opened in append mode.
- **The same `run_id` is used again** (e.g. resuming an interrupted run): before executing a round,
  the orchestrator checks whether a `repair_attempts` row already exists for
  `(notebook_execution_id, run_id, round)`. If it does, that round is **not** re-executed and
  **not** duplicated - it is recorded in the trace as `{"status": "skipped_already_logged"}`, and no
  further rounds are attempted for that record in this invocation. This is a deliberate scope
  boundary: resuming does not reconstruct a Round 2 decision from a Round 1 row already sitting in
  the database (that would require re-deriving `same_as_original_error` and re-running
  classification from stored columns alone) - it simply guarantees no duplicate row is ever written
  for a round that already has one. A fully clean re-run of a multi-round chain needs either a new
  `--run-id` or `--overwrite`.
- **A run stops halfway** (crash, Ctrl-C, host restart): nothing is lost - every round's row is
  inserted and committed immediately after that round completes (`sqlite3`'s default autocommit-per-
  statement-block behavior via `insert_row()`'s own `conn.commit()`), and the trace file is flushed
  after every record. Re-running the identical command with the same `--run-id` resumes correctly
  per the point above.
- **The user explicitly requests overwrite** (`--overwrite`): the `repair_attempts` table is dropped
  and recreated before the run starts (mirroring `result_logger.py`'s own `--overwrite` flag
  exactly), the "already logged" check is disabled entirely for the run (since there is nothing left
  to find), and the trace file for that `run_id` is opened in write (truncate) mode instead of
  append.

## 16. Real-pilot / evaluation-split discipline

`--split` defaults to `dev`, not `all` or `evaluation`. This is a deliberate protective default: the
187-row `evaluation` split is reserved for the eventual final evaluation, and defaulting the
orchestrator's own iteration/debugging entry point away from it means an accidental
`python scripts/run_pipeline.py` with no `--split` flag can never consume it. Reaching the
evaluation split requires explicitly passing `--split evaluation` or `--split all`.

## 17. Commit reproducibility (FixApplicator environment fidelity)

FixApplicator should execute against the exact recorded repository commit whenever one is available,
not the target repository's current/default branch - `docker_runner.checkout_commit()` already
enforces this (`docs/fix-applicator.md` "Commit pinning"): a recorded commit that fails to check out
is a hard `apply_error`, never a silent fallback to the default branch. Three distinct, never-confused
states, all visible in FixApplicator's own result (and therefore in the orchestrator's per-round trace
and the i5 JSONL record - none of this is part of the `repair_attempts` SQL schema, which has no room
for it and does not need it):

| `commit_checkout_status` | Meaning |
|---|---|
| `"checked_out"` | A commit was resolved and `git checkout <commit>` succeeded. |
| `"skipped_no_commit"` | No commit was resolved for this repository (see `commit_resolution_note`, below, for why) - the notebook ran against whatever `git clone` checked out by default (normally the repository's default branch). Not an error. |
| `None`, with `outcome: "apply_error"` and `failure_stage: "checkout"` | A commit *was* resolved, but `git checkout` failed (bad/garbage-collected SHA, unreachable ref). Never silently treated as "no commit" - `checkout_commit()` raises, and the attempt is recorded as a failure, not run against the default branch instead. |

**`commit_resolution_note`** (added as part of this investigation) explains *why* a commit was
unavailable, whenever `commit_checkout_status == "skipped_no_commit"`, so that is never an
unexplained gap:

- `"no repository metadata lookup was configured"` - `--fix-config`'s
  `upstream_docker_pipeline.db_path` was never set (or `default_repository_metadata_lookup()` was
  given `None`).
- `"repository metadata lookup returned no data for repository_id=<id>; repository commit
  unavailable in source metadata"` - a lookup mechanism exists, but returned nothing for this
  repository. This covers **both** "the repository genuinely has no recorded commit" **and** "the
  metadata database itself could not be opened" (missing file, bad path, locked, malformed) -
  `default_repository_metadata_lookup()` deliberately never raises for any of these (see its own
  docstring: commit pinning is "prefer when available", not a hard prerequisite), so this
  orchestrator-level note cannot distinguish the two sub-cases further without changing that
  contract, which was out of scope for this fix.
- `"repository metadata was found for repository_id=<id> but it has no recorded commit"` - the
  lookup succeeded and found a real row, but that row's own `commit` field is empty.

**A concrete, real finding from this investigation:** a real pilot run of `notebook_execution_id=8`
reported `skipped_no_commit` even though the sibling pipeline's database *does* record a commit
(`1a03b9b88da238d430f577f65c39f4377375edcb`) for that repository. Root cause, confirmed by direct
inspection: `config/fix_applicator.yaml`'s default `upstream_docker_pipeline.db_path` uses `~`, which
`Path.expanduser()` resolves relative to the *host Python process's* home directory - on an execution
environment where the pipeline is invoked via a Python interpreter whose home directory differs from
where the sibling pipeline's own data actually lives (for example, a native-Windows Python process
reaching this repository through a WSL mount), `~/era/computational-reproducibility-pmc-docker/...`
does not resolve to the real file, and `default_repository_metadata_lookup()` correctly, silently
(pre-existing, documented behavior) treats that as "no metadata available." **This is not an i7
metadata-propagation bug** - `resolve_attempt()`/`apply_and_validate()` already forward whatever the
lookup returns, unchanged, for both Round 1 and Round 2 (§7, §8 above: Round 2 reuses the same
`i2_index`/`repository_metadata_lookup` call, joined by the same `notebook_execution_id`, so it always
resolves the identical repository identity and commit as Round 1 - it never re-derives or invents
either). It is a pre-existing characteristic of `default_repository_metadata_lookup()`'s path
resolution on environments where the process's home directory and the sibling pipeline's data
directory diverge. The pre-existing `docs/i5-live-validation.md` documents hitting the same class of
access issue during the original i5 pilot and working around it with a local read-only copy of the
database - the same technique used for this investigation's own real-pilot verification (`--fix-config`
pointed at an accessible copy; see the completion report for the exact commands and results).

**For the final 187-row evaluation:** prefer a `--fix-config` whose `upstream_docker_pipeline.db_path`
is confirmed reachable from wherever the evaluation is actually run (verify with a one-off Python
check - `Path(db_path).expanduser().is_file()` - before starting a long run), so exact recorded
commits are used rather than default branches wherever the source dataset has one recorded. Running
against the default branch is not incorrect (FixApplicator's own contract treats it as an explicit,
non-fatal fallback, and now names the reason via `commit_resolution_note`), but it is a *lower-fidelity*
reproduction of the notebook's original failure environment, and the final evaluation should not settle
for it silently when a better path is available.

## 18. SQLite concurrency

`repair_attempts.sqlite` is a single-file SQLite database, not a multi-user concurrent database
server - it is not being overstated as one here. What it *does* support, and what this orchestrator
now handles explicitly:

- **One database may be reused safely by sequential runs.** `open_repair_attempts_db()` opens,
  ensures the schema, and hands back a connection that is always closed (via `try/finally`, from the
  moment it exists - see below) at the end of the run. A second, later invocation against the same
  `--database` path opens cleanly and sees everything the first one committed - this is the normal,
  supported way to resume an interrupted run or extend an existing benchmark database with a new
  `--run-id` (§15).
- **Concurrent *writers* can contend.** If two pipeline processes (or a manual pilot and an
  orchestrated run) write to the *same* database file at the *same* time, SQLite's own file-locking
  serializes them - one waits while the other holds the lock. This orchestrator sets an explicit,
  generous busy timeout (`DB_LOCK_TIMEOUT_SECONDS = 30.0`, both via `sqlite3.connect(timeout=...)`
  and an explicit `PRAGMA busy_timeout`) so a *brief* overlap (two runs starting within the same
  second, a quick resumed run) waits it out rather than failing immediately.
- **A lock that outlives that timeout is never silently ignored.** `open_repair_attempts_db()` and
  `_reset_repair_attempts_table()` (the `--overwrite` path) both catch the resulting
  `sqlite3.OperationalError` and re-raise a clear `RuntimeError` naming the database path and stating
  plainly that another pipeline process may be writing to it - the run stops with that message rather
  than continuing against a database it could not safely open, and never silently switches to a
  different file instead.
- **The connection lifecycle bug this fixes:** before this change, `main()` opened its connection and
  called `create_table()`/the `--overwrite` `DROP TABLE` *before* entering the `try/finally` that
  closed it - an exception in that window (a locked database very much included) leaked the open
  connection instead of closing it deterministically. Both are now inside the same `try/finally` as
  the rest of the run, mirroring the pattern `scripts/result_logger.py`'s own CLI `main()` already
  used correctly.
- **No long-held write transaction.** `result_logger.create_table()` and `result_logger.insert_row()`
  (unchanged) each commit immediately after their one statement - no transaction is ever held open
  across a round's real Ollama/PyPI/Docker work, which is what keeps the actual contention window
  short even under the sequential-reuse pattern above.
- **The schema is created once per run**, not once per record - `open_repair_attempts_db()` is called
  a single time in `main()`, before the per-record loop begins.
- **WAL mode was considered and deliberately not enabled.** `PRAGMA journal_mode=WAL` would allow a
  reader and a writer to proceed concurrently, which sounds attractive here - but WAL's shared-memory
  file (`-wal`/`-shm`) is documented by SQLite itself as unreliable over network filesystems, and this
  repository is routinely accessed through exactly that kind of boundary (a WSL-mounted filesystem
  reached via a UNC path from a native-Windows process, per this investigation's own findings above).
  Enabling WAL here could trade a clear, occasional "busy/locked" error for silent, intermittent
  corruption risk - a strictly worse outcome for a thesis benchmark database. The default rollback
  journal, with the explicit busy timeout above, is the safer choice for this environment.
- **Recommended practice:** use a unique `--run-id` per logical experiment (the default,
  `i7-<timestamp>`, already is one) so sequential/resumed runs against the same database are easy to
  tell apart in `repair_attempts.run_id`; use an isolated `--database` path for a manual, ad hoc pilot
  you do not want interleaved with an in-progress orchestrated run (or with another person's pilot on
  a shared checkout) - both are valid, supported patterns, not workarounds.
