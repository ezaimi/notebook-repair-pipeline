# Protocol: Comparison with a PLLM-Style Dependency-Repair Baseline

**Status:** frozen protocol before baseline implementation or evaluation.

This document defines the comparison between the thesis repair layer and a
PLLM-style baseline. It fixes conditions, outcomes, and reporting rules
before either method is run on the reserved evaluation split. It does not
authorise an evaluation run and does not change the thesis results.

## 1. Aim and comparison claim

The comparison tests whether the thesis repair layer and a close,
execution-feedback-driven dependency-repair baseline achieve different
outcomes when they are given the same failing Jupyter notebooks.

The baseline will be called **PLLM-style**, not PLLM, unless the original
authors' implementation can be run without material adaptation. It will
use the central PLLM loop:

1. receive a failing program and its execution error;
2. use an LLM and PyPI evidence to propose dependency changes;
3. apply the changes in an isolated environment and execute the program;
4. use the resulting execution feedback in a possible second repair round.

The comparison does not seek to prove that the thesis system is generally
better than PLLM. It tests both implementations in one defined
notebook-pipeline setting.

## 2. Evaluation population

| Item | Protocol rule |
|---|---|
| Dataset | `data/context-classification/dependency_error_contexts.jsonl` |
| Split | `evaluation` only |
| Expected records | 187 |
| Notebook identifiers | Exact identifiers in `data/dependency-errors/split_manifest.json` under `splits.evaluation` |
| Development data | Only the 13-record `dev` split may be used to build, debug, or tune the baseline. |
| Excluded records | The 14 `excluded` records remain outside both methods' repair evaluation. |

No prompt, package mapping, retry rule, or implementation may be changed
after a method has processed an evaluation-split record. If a defect is
found, discard that run, document the correction, re-freeze the method,
and only then run a replacement.

## 3. Methods being compared

### Thesis repair layer

The comparison run uses the existing pipeline with its normal components:
classification, explanation, PyPI-grounded repair proposal, deterministic
proposal validation, Docker-based fix application, bounded Round 2, and
result logging. Explanation and RDF outputs are retained as thesis features
but do not enter repair-rate metrics.

### PLLM-style baseline

The baseline receives the same original notebook, recorded initial error,
repository revision, and Docker starting environment. It may inspect the
notebook source and error feedback. It uses a repair loop that proposes
dependency changes, executes the notebook, and passes the resulting error
to a possible second round.

The baseline must not reuse the thesis system's static
import-to-distribution mapping, error-subtype gate, proposal-schema gate,
or explanation/RDF components. It must write a structured log sufficient
to determine every outcome in Section 6. An abstention is an outcome, not
a reason to remove a notebook from the denominator.

## 4. Conditions held constant

| Condition | Frozen rule |
|---|---|
| Evaluation records | The same 187 identifiers, processed once by each method. |
| Starting state | Same repository commit, Dockerfile/build recipe, and original dependency failure per notebook. |
| Repository metadata | Same upstream Docker-pipeline SQLite snapshot, identified by SHA-256. |
| Environment | Same base-image digest, Python version, and execution timeouts. |
| LLM | Same local model artifact/digest, decoding parameters, token limit, and timeout; record all values in both manifests. |
| PyPI evidence | One timestamped immutable cache of all PyPI responses used by both methods; neither final run queries live PyPI after it is frozen. |
| Repair budget | At most two repair rounds per notebook. |
| Isolation | Each attempt begins from a clean reconstruction of the original notebook environment; no installed package carries to another notebook. |
| Hardware | Record CPU/GPU, memory, operating system, Docker version, and model-serving version. |

The existing Gemma evaluation used `gemma2:9b` and a two-round cap. For a
fair comparison, the thesis repair layer must be re-run under the same
newly frozen inputs as the baseline; do not compare a new baseline against
an earlier run that used live PyPI responses.

## 5. Round and feedback rules

- Round 1 starts from the recorded original dependency error.
- Round 2 is allowed only if Round 1 made an actual repair attempt,
  progressed beyond the targeted error, and produced a new
  dependency-related failure as feedback.
- Neither system receives a third repair round.
- Clone, build, Docker execution, and model-service failures use the
  existing infrastructure-versus-method classification rules.
- Both methods log every proposed dependency command or package/version
  combination and its execution result.

## 6. Outcomes and metrics

The headline notebook denominator is all 187 evaluation records.
Targeted-error resolution is attempt-level, so one notebook may contribute
one or two repair attempts.

| Metric | Definition |
|---|---|
| Full notebook recovery (primary) | Notebooks completing execution after at most two rounds / 187. |
| Round-1 recovery | Notebooks completing after Round 1 / 187. |
| Additional Round-2 recovery | Notebooks still failing after Round 1 that complete after Round 2. |
| Targeted-error resolution | Actual attempts where the error targeted in that round is absent after re-execution / all actual repair attempts. |
| Attempt coverage | Actual repair attempts / 187, reported with abstentions and failures. |
| Final-state abstention | Notebooks whose final repair decision abstained / 187. |
| Infrastructure and method failures | Final counts and rates / 187, using the established classification rules. |
| Runtime and effort | Per-notebook and total wall-clock time, LLM calls, and actual repair attempts. |

Full recovery and targeted-error resolution must always be reported
separately. Removing `ModuleNotFoundError: sklearn` but then exposing a
`pandas` failure resolves the targeted error; it does not recover the
whole notebook.

## 7. Required artefacts

Each final run must produce a separate directory under `data/evaluation/`:

```text
manifest.json              # configuration, hashes, environment, and run ID
raw/                       # raw trace and repair-attempt database
summary/                   # per-notebook outcomes and aggregate metrics
tables/                    # thesis-ready metric tables
validation_report.json     # integrity and count checks
```

The baseline manifest must state whether it is the original PLLM
implementation or a PLLM-style reimplementation, its source repository
and commit, and every adaptation made for notebooks.

## 8. Reporting and interpretation

Report paired notebook-level outcomes: successes under both methods,
thesis-only successes, baseline-only successes, and failures under both.
Report these alongside the aggregate metrics in Section 6.

An overall difference does not prove that a particular component caused it.
The thesis may discuss associated design differences, but cannot attribute
an outcome to one component without a separate ablation. If original PLLM
cannot be used, the thesis must call the alternative a PLLM-style
reimplementation and state the validity limitation.

## 9. Deviations

Record any departure from this protocol before the final runs, including
the reason, affected methods, and expected effect on comparability.
Undocumented changes invalidate a direct comparison.
