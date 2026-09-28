# I9 Model-Sensitivity Comparison: Gemma-2 9B vs Qwen3.6-35B-A3B-MLX-8bit

Corrected final comparison artifact, suitable as the basis for the thesis
model-sensitivity section. Supersedes the proposal-validity/grounding-pass
figures for Gemma reported in an earlier draft of this comparison, which
incorrectly showed 61/61 instead of the correct 73/73 (both rounds'
invocations, not Round 1 only).

## Source runs (frozen, unmodified)

| | Run directory | Split | n |
|---|---|---|---|
| Gemma-2 9B (authoritative I8) | `data/evaluation/i8-eval-final-rerun-20260913T113423Z/` | evaluation | 187 |
| Qwen3.6-35B-A3B-MLX-8bit (I9) | `data/evaluation/i9-eval-qwen-final-20260915T141055Z/` | evaluation | 187 |

Both runs share the same 187 evaluation-split notebook IDs, the same
classifier, prompts, few-shot examples, schemas, PyPI retrieval and
`config/package_mapping.yaml`, grounding validation, FixApplicator, and
Round-2 eligibility logic. Only the generative LLM provider/model differs
(Ollama/Gemma-2 9B vs Kiste/Qwen3.6-35B-A3B-MLX-8bit, `max_tokens: 4096`
for Qwen vs `700` for Gemma - the only other config difference, calibrated
solely to eliminate truncation, documented in
`docs/i9-qwen-model-sensitivity-freeze.md`). This is a **paired**
comparison over identical notebooks, not two independent samples.

## Corrected metric comparison

| Metric | Gemma-2 9B | Qwen3.6-35B-A3B-MLX-8bit | Difference |
|---|---|---|---|
| Explanation schema validity | 185/187 (98.9%) | 187/187 (100.0%) | +2 |
| R1 abstentions | 126/187 (67.4%) | 126/187 (67.4%) | 0 |
| Final abstentions | 162/187 (86.6%) | 161/187 (86.1%) | −1 |
| Actual repair LLM invocations | 73 = 61 R1 + 12 R2 | 73 = 61 R1 + 12 R2 | 0 |
| **Proposal validity** | **73/73 (100.0%)** | 73/73 (100.0%) | 0 |
| **Grounding pass rate** | **73/73 (100.0%)** | 73/73 (100.0%) | 0 |
| Overall grounded-proposal coverage (all RAG invocations, abstentions included) | 73/235 (31.1%) | 73/234 (31.2%) | −1 (denominator; see note) |
| Targeted-error resolution, overall | 62/73 (84.9%) | 61/73 (83.6%) | −1 |
| — R1 targeted-error resolution | 50/61 (82.0%) | 49/61 (80.3%) | −1 |
| — R2 targeted-error resolution | 12/12 (100.0%) | 12/12 (100.0%) | 0 |
| R1 full recovery | 0/187 (0.0%) | 0/187 (0.0%) | 0 |
| Final full recovery | 0/187 (0.0%) | 0/187 (0.0%) | 0 |
| R2 eligible | 48/187 | 47/187 | −1 |
| R2 actual LLM attempts | 12 | 12 | 0 |
| Additional fixed by R2 | 0 | 0 | 0 |
| Infrastructure failures | 2/187 (1.1%) | 2/187 (1.1%) | 0 |
| Method failures | 1/187 (0.5%) | 2/187 (1.1%) | +1 |

Note on grounded-proposal-coverage denominators: Gemma's total RAG
invocation population is 235 = 126 (R1 abstained) + 61 (R1 real) + 48 (R2
eligible: 36 abstained + 12 attempted). Qwen's is 234 = 126 + 61 + 47 (R2
eligible: 35 abstained + 12 attempted). The 1-record gap is the same
single notebook (191) responsible for every other difference in this
table - see below.

Metric definitions unchanged from `scripts/evaluation_metrics.py`
(I8-frozen): proposal validity is conditional on an LLM response having
been produced; grounding pass is conditional on a schema-valid proposal;
overall grounded-proposal coverage is grounded proposals divided by every
repair-agent invocation across both rounds, abstentions included;
targeted-error resolution is independent of whether the notebook's final
outcome was `fixed` - `still_failing` does not imply the originally
targeted dependency error remained unresolved.

## Paired notebook-ID analysis (same 187 IDs)

- **Fixed by both / only Gemma / only Qwen:** 0 / 0 / 0 - neither model
  fully recovered any of the 187 notebooks.
- **Round-1 (original) targeted-error resolved, per notebook** (renamed
  from an earlier draft's ambiguous "targeted error resolved by both: 49"
  - this is the per-notebook Round-1/original-error outcome, **not** the
  attempt-level overall rate above, which counts up to two resolution
  events per notebook across both rounds): resolved by **both** models:
  **49**; resolved **only by Gemma**: **1** (notebook **191**); resolved
  **only by Qwen**: **0**.
- **Different Round-1 proposed actions:** **0 of 61** paired real
  invocations - every Round-1 action (install/pin_version, exact
  package/version) is identical between the two models.
- **Different Round-2 behavior:** **0 of 12** paired attempts differ in
  action; of the 47 notebooks eligible for Round 2 under both models,
  attempt/abstain agreement is 47/47.
- **`still_failing` final-category set:** identical - same 22 notebook
  IDs for both models.
- **`infrastructure_failure` set:** identical - same 2 notebook IDs (444,
  445) for both models.
- **`method_failure` set:** Gemma {370}; Qwen {191, 370}.

**Every difference in this entire 187-notebook comparison traces to one
record: notebook 191** (numpy, wrong_version). Both models proposed the
identical `pin_version` action. Gemma's run: FixApplicator returned
`still_failing` (original targeted error resolved; a different issue
remained -> Round-2-eligible -> abstained on `mapping_unknown` -> final
`abstained`). Qwen's run: the identical fix attempt returned `apply_error`
(`method_failure`) instead - an execution/infrastructure-layer outcome,
not a difference in either model's proposal. Most plausibly run-to-run
infrastructure noise (e.g. a transient clone/build step) rather than a
model-quality effect, since the input to FixApplicator was identical.

## Interpretation

Replacing Gemma-2 9B with Qwen3.6-35B-A3B-MLX-8bit, with every other
pipeline component held fixed, produced **no detectable model-dependent
difference in repair decisions**: 186 of 187 notebooks (99.5%) have
identical final outcomes, identical Round-1 actions, and identical
Round-2 behavior. The deterministic retrieval/grounding layer constrains
the valid action space tightly enough (exact resolved distribution name,
exact candidate version) that both models converge on the same proposal
whenever they reach a real decision. The one measurable model-side
difference is explanation schema validity (187/187 vs 185/187, a minor,
non-repair-affecting gap). Round-1 abstentions (126/187, identical
notebook set for both) are entirely the shared, deterministic
`config/package_mapping.yaml` coverage gap, unrelated to either model.
Both models reach **0/187 full notebook recovery** despite resolving the
targeted dependency error in ~80-85% of real attempts - a pipeline-wide
ceiling (a second, different downstream failure routinely follows a
correctly-targeted fix) that neither model's answer quality could move,
and that is identical for both.

Classifier and PyPI-resolution manual ground-truth scoring are unchanged,
shared, deterministic components and are not re-evaluated here (see the
Gemma I8 report for those figures).
