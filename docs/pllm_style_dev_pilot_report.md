# PLLM-Style Baseline Development Pilot

**Status:** completed. This is development evidence only; it is not part of
the 187-record comparison and must not be reported as an evaluation result.

## Scope

- Run ID: `pllm-style-dev-pilot-20260922T172000Z`
- Input: all 13 records in the `dev` split
- Baseline: `pllm_style_notebook_v1`
- Model: local Ollama `gemma2:9b`, temperature 0.1, top-p 0.9, maximum 700
  output tokens
- Repair budget: at most two rounds
- Execution: a clean FAIR Jupyter Docker reconstruction for each attempt

The run used the notebook-adapted PLLM-style implementation, not the
original PLLM program. The adaptation and its justification are recorded in
`docs/pllm_original_compatibility_assessment.md`.

## Completion and checks

All 13 records were written to
`data/pllm-style-baseline/pllm-style-dev-pilot-20260922T172000Z.jsonl`.
The process exited successfully, its stderr log was empty, and no Docker
container was still running when the run completed. The baseline unit tests
passed after the pilot (8 passed).

## Observed development outcomes

| Measure | Result |
|---|---:|
| Records processed | 13 / 13 |
| Actual repair attempts | 16 |
| Full notebook recoveries | 2 / 13 |
| Round-1 recoveries | 0 / 13 |
| Additional Round-2 recoveries | 2 / 13 |
| Attempts that removed their targeted error | 12 / 16 |
| Records reaching Round 2 | 4 / 13 |

These values establish that the adapter executes its feedback loop and
respects the two-round limit. They are not an estimate of final performance:
the development split was used to correct the parser and the Python-version
filter, and it remains excluded from the final comparison denominator.

## Freeze preparation

The pilot initially used a writable development cache. Before any evaluation
run, a separate cache was built from the 85 distinct distributions in PLLM's
checked module-link table. It contains 82 resolved PyPI project responses and
three cached `not_found` responses. The final baseline configuration points
to this cache and has `allow_network: false`. Thus an evaluation run cannot
silently use a newer live PyPI response. A proposal for a package outside
this frozen evidence universe is recorded as an abstention rather than
causing a live lookup.

The next task is to add a guarded evaluation-only runner and produce its
manifest. Before interpreting any final comparison, the thesis repair layer
must be re-run under the same frozen cache, model artifact, repository
metadata snapshot, and Docker execution configuration, as required by
`docs/pllm_style_baseline_protocol.md`.
