# I9 Qwen/Kiste Model-Sensitivity Freeze Record

## Purpose

Supplementary model-sensitivity experiment: does swapping the generative
LLM change LLMExplainer/RAGRepairAgent behavior? **Gemma-2 9B via Ollama
(I8) remains the authoritative main evaluation** - this experiment isolates
LLM choice as the sole independent variable and is never a replacement for
it.

Only the generative LLM provider/model changes (Ollama/Gemma-2 9B ->
Kiste/Qwen3.6-35B-A3B-MLX-8bit). All other pipeline components are fixed:
prompts, few-shot examples, schemas, classifier, PyPI retrieval and
`config/package_mapping.yaml`, validator behavior, FixApplicator, Round-2
eligibility logic, temperature, top_p, and retry policy. See
`scripts/llm_providers.py`, `config/llm_explainer.kiste.yaml`,
`config/rag_repair.kiste.yaml` for the implementation - a provider dispatch
that defaults to the unchanged Ollama path whenever no `provider` key is
present, so `config/llm_explainer.yaml` and `config/rag_repair.yaml` (and
every other frozen I8 artifact) are never touched by this experiment.

## Frozen configuration

| Parameter | Value |
|---|---|
| model | `Qwen3.6-35B-A3B-MLX-8bit` |
| provider | `kiste` |
| base_url | `https://kiste.informatik.tu-chemnitz.de/v1` |
| LLMExplainer `generation.max_tokens` | `4096` |
| RAGRepairAgent `repair_agent.kiste.max_tokens` | `4096` |
| temperature | `0.1` |
| top_p | `0.9` |
| max_rounds (final evaluation) | `2` (matches the frozen Gemma I8 final-evaluation configuration) |

Config files: `config/llm_explainer.kiste.yaml`, `config/rag_repair.kiste.yaml`
(new, additive, selected only via `--explainer-config`/`--repair-config`;
never the default for any script).

## Calibration methodology

- Used only dev-split records: notebook_execution_id **8** (sklearn,
  missing_package), **43** (pkg_resources, missing_package), **61** (umap,
  missing_package), **157** (scipy/isshape, wrong_version), **174**
  (scipy/cumtrapz, wrong_version). No reserved 187-record evaluation-split
  record was used at any point during calibration.
- Tested token budgets: **1400, 2800, 4096**.
- Truncation (`finish_reason: length`) observed:
  - LLMExplainer: 1400 -> 5/5 truncated; 2800 -> 1/5; 4096 -> 0/5
  - RAGRepairAgent: 0/5 truncated at every tested budget
- **4096** selected as the smallest of the three tested budgets producing
  zero observed truncation for both components. Selection criterion was
  completion/truncation only - repair-outcome correctness or quality was
  never used to choose a budget.

## Final pre-evaluation smoke test

- Same five dev-split records as calibration, run through the real,
  unmodified production path: classification/eligibility gate ->
  LLMExplainer (Kiste/Qwen) -> RAGRepairAgent (Kiste/Qwen) -> FixApplicator
  (real git clone + Docker build/re-execution) -> ResultLogger, with
  `--max-rounds 2` and normal JSON-schema validate/retry handling.
- Dedicated local scratch database/output-dir; no file under
  `data/repair-attempts/`, `data/pipeline-runs/`, or `data/evaluation/`
  was touched.
- **11 real Kiste LLM calls total**: 5 LLMExplainer calls + 5 Round-1
  RAGRepairAgent calls + 1 Round-2 RAGRepairAgent LLM call (notebook 8,
  triggered by a genuinely new eligible `missing_package` error surfaced
  after the Round-1 fix). The Round-2 attempts for notebooks 157 and 174
  abstained correctly *before* any LLM call, because the newly-surfaced
  modules (`matplotlib`, `mdsuite`) are not covered by
  `config/package_mapping.yaml` - a pre-existing retrieval-layer gap,
  unrelated to Qwen or `max_tokens`.
- Across all 11 calls: 0 retries required, 0 `finish_reason: length`, 100%
  schema-valid on first attempt. Largest single LLMExplainer completion:
  3052/4096 tokens (~74.5%, notebook 174).

## Verification: Gemma/Ollama and I8 artifacts unchanged

- `config/llm_explainer.yaml` / `config/rag_repair.yaml`: unmodified
  (`max_tokens: 700`, `model: gemma2:9b`; no git modification recorded).
- `config/package_mapping.yaml` and `config/fix_applicator.yaml` SHA-256
  hashes below are **byte-identical** to the values recorded in
  `docs/i8-pre-final-evaluation-freeze.md`.
- No file under `data/evaluation/` was created, deleted, or modified.

## Config file hashes (SHA-256)

| File | SHA-256 |
|---|---|
| `config/llm_explainer.kiste.yaml` | `f3a3d39df767eda9f3699bad4518ed78a8e5f600696c79f2c1e79eb644b3389c` |
| `config/rag_repair.kiste.yaml` | `76ff1538f6cfaab292e001141a5a429f4283935881cb9db573cce421605e6eea` |
| `config/package_mapping.yaml` | `e2231d9855b77f5b200597c6814f7d719be5fb73302d79e058e6a8f281e17562` (matches I8 freeze - unchanged) |
| `config/fix_applicator.yaml` | `138aaf4f0552d43432dff5b86bb9cf8cd53286beda10893ce3d96e66dbe45637` (matches I8 freeze - unchanged) |

Computed via `evaluation_manifest.hash_file()`. Recompute immediately
before the 187-record run and compare; any mismatch on the last two means
something changed since this freeze and the run must not proceed until
investigated. This document never records `.env` contents or
`KISTE_API_TOKEN`.

## Next step (not yet executed)

```
python scripts/run_evaluation.py \
  --split evaluation --i-understand-this-touches-the-reserved-split \
  --run-id <i9-eval-qwen-TIMESTAMP> \
  --model Qwen3.6-35B-A3B-MLX-8bit --max-rounds 2 \
  --explainer-config config/llm_explainer.kiste.yaml \
  --repair-config config/rag_repair.kiste.yaml
```

Requires explicit authorization; not run as part of this freeze.
