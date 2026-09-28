# Original PLLM Compatibility Assessment

**Status:** completed before baseline implementation. This assessment did
not run the reserved 187-record evaluation split.

## Source assessed

| Item | Value |
|---|---|
| Repository | `https://github.com/checkdgt/fse-aiware-python-dependencies` |
| Checked revision | `11b8e6e45cd0167070df1367e748e00bd67a9b0d` |
| Relevant implementation | `tools/pllm/` |
| Intended input | One standalone Python file, passed as `test_executor.py --file <path>` |
| Original default repair-loop limit | 5 iterations (`--loop 5`) |

The checkout is retained locally under `third_party/` for inspection only.
It is not part of this thesis repository's source tree.

## Development-record preflight

The following development-split records were selected to cover both
`ModuleNotFoundError` and `ImportError` without touching the reserved
evaluation split:

| Notebook-execution ID | Notebook path | Error type | Failing module |
|---:|---|---|---|
| 8 | `Analysis/Similarity Processes/mesure_similarity.ipynb` | `ModuleNotFoundError` | `sklearn` |
| 10 | `Analysis/Distribution DSL1 DSL2/distribution.ipynb` | `ImportError` | `matplotlib` |
| 174 | `examples/notebooks/Molten_Salt_Comparison.ipynb` | `ImportError` | `scipy` |

All three inputs are Jupyter notebooks (`.ipynb`). Their retained
classification records have `context_status = metadata_only`; they are not
standalone Python-file fixtures.

## Findings

### 1. The original command does not currently start outside its own container

Running `python tools/pllm/test_executor.py --help` from the checkout stops
at import time with:

```text
ModuleNotFoundError: No module named 'langchain_community'
```

This is an environment prerequisite, not evidence that PLLM itself is
broken. The supplied `tools/pllm/Dockerfile` installs this dependency and
expects a dedicated Docker-in-Docker container with a Docker socket and an
Ollama service.

### 2. Its input and execution contract is Python-file-specific

The interface accepts `--file`, extracts imports from that file, copies one
file into a generated Docker image, and writes this command in
`helpers/build_dockerfile.py`:

```text
CMD ["python", "/app/<project_file>"]
```

For each preflight record, that becomes `python /app/<notebook>.ipynb`.
This is not Jupyter notebook execution and cannot reproduce FAIR Jupyter
pipeline semantics. The implementation contains no `.ipynb` parser,
`nbclient`/`nbconvert` step, repository checkout, or support for the
upstream repository-specific Docker build recipe.

### 3. Its environment differs materially from the thesis starting state

PLLM infers a Python version and creates a fresh image beginning with
`FROM python:<inferred-version>`. The thesis evaluation starts from the
FAIR Jupyter pipeline's recorded repository revision and Docker environment.
Using original PLLM unchanged would therefore change both the input type and
the initial environment, so any repair-rate difference could not fairly be
attributed to the repair method.

## Decision

**Original PLLM cannot be run unchanged as a fair comparator on these
notebooks.** This is a task-interface incompatibility, not a claim that
PLLM is ineffective.

Making it applicable would require material changes:

1. execute an `.ipynb` notebook from its original repository environment,
   rather than one copied `.py` file;
2. preserve the repository revision and Docker build recipe;
3. replace PLLM's five-iteration default with the protocol's two-round
   comparison limit; and
4. emit per-notebook, per-round structured logs compatible with the frozen
   evaluation metrics.

Those changes constitute a **PLLM-style baseline reimplementation**. The
thesis must use that term and state the resulting validity limitation.

## Next step

Implement the PLLM-style baseline only against the 13-record development
split, following `docs/pllm_style_baseline_protocol.md`. The reserved
187-record evaluation split remains untouched until the baseline has been
validated and frozen.
