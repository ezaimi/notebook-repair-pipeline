# Evidence-Grounded Dependency Repair for Jupyter Notebooks

This repository contains the implementation, evaluation artefacts, and LaTeX
source for Erisa Zaimi's M.Sc. Web Engineering thesis at TU Chemnitz, supervised
by Dr. Sheeba Samuel. The work extends the FAIR Jupyter reproducibility pipeline
with a conservative workflow for explaining and repairing Python dependency
failures in Jupyter notebooks.

## Thesis PDF

The thesis PDF is deliberately not versioned in Git. GitLab CI builds it from
`thesis/` and publishes it as a six-month job artifact:

- [Download the latest successful thesis build](https://gitlab.hrz.tu-chemnitz.de/vsr/edu/advising/ma-erisa-zaimi/-/jobs/artifacts/i9-llm-model-sensitivity-evaluation/raw/thesis/thesis.pdf?job=build_thesis)
- [Browse the thesis build artifacts](https://gitlab.hrz.tu-chemnitz.de/vsr/edu/advising/ma-erisa-zaimi/-/jobs/artifacts/i9-llm-model-sensitivity-evaluation/browse/thesis?job=build_thesis)

The links require access to this GitLab project and resolve to the latest
successful build of the `i9-llm-model-sensitivity-evaluation` branch.

## What the pipeline does

The pipeline separates explanation, repair decisions, and validation. It does
not accept an LLM response as proof that a repair works.

```text
Dependency failure
  -> ErrorClassifier       classify failure type and repair scope
  -> LLMExplainer          generate a structured plain-language explanation
  -> Resolver/Retriever    verify package and version evidence from PyPI
  -> Repair policy         select an evidence-backed action or abstain
  -> Proposal validator    enforce schema and evidence constraints
  -> FixApplicator         apply the validated action in Docker
  -> Re-execution          run the notebook from the first cell
  -> ResultLogger          store SQLite, CSV, and RDF-compatible results
```

An explanation is attempted for every encountered dependency error. Repairs are
proposed only when the evidence supports them; otherwise the system records an
abstention. When a repair exposes a different dependency error, the pipeline
allows one bounded second round. Docker re-execution is the final outcome
check.

## Repository layout

```text
thesis/       LaTeX source, bibliography, and figures for the thesis
scripts/      pipeline components, evaluators, data preparation, and analysis
config/       versioned pipeline and experiment configurations
prompts/      LLM explanation and repair prompt templates
schemas/      structured-output schemas
mapping/      RML mapping for repair-attempt RDF materialisation
data/         frozen inputs, evaluation summaries, and derived artefacts
docs/         design decisions, protocols, freeze records, and study material
tests/        automated tests for pipeline and analysis components
```

The repository intentionally excludes secrets, machine-specific paths, raw
runtime scratch output, local editor files, and the generated thesis PDF. See
`.gitignore` for the exact rules.

## Requirements

- Python 3.10 or later
- Docker Engine, for repair application and notebook re-execution
- An Ollama installation with the configured Gemma model for the default local
  evaluation setup
- Optional: access to the configured Qwen-compatible endpoint for the
  model-sensitivity evaluation
- The upstream FAIR Jupyter metadata database when reproducing Docker runs;
  use `config/fix_applicator.evaluation.example.yaml` as the path-free template
  and keep any local override out of Git

Install the Python dependencies and run the automated tests:

```bash
python -m venv .venv
source .venv/bin/activate              # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q
```

## Evaluation and reproducibility

The committed artefacts preserve the frozen inputs and reported results used by
the thesis. Evaluation commands deliberately require explicit configuration and
access to Docker, model services, and the upstream metadata database; they are
therefore documented rather than presented as a one-command quick start.

Start with these documents:

- [V2 repair policy](docs/v2-repair-policy.md): scope, safety rules, and
  component responsibilities.
- [Pipeline orchestrator](docs/pipeline-orchestrator.md): command-line workflow
  and recorded artefacts.
- [I9 Gemma--Qwen comparison](docs/i9-qwen-vs-gemma-comparison.md): paired
  model-sensitivity evaluation over the same 187 notebook records.
- [Human-explanation questionnaire](docs/human-explanation-evaluation-questionnaire.md):
  initial reader-study design and analysis notes.

The final evaluation uses 187 reserved notebook records, at most two repair
rounds per notebook, and a frozen evaluation configuration. The RDF output is
materialised locally from the final evaluation table and structurally validated;
publishing it as a reusable graph is outside this repository's current scope.

## Build the thesis locally

With a LaTeX distribution and `latexmk` installed:

```bash
cd thesis
latexmk -pdf -interaction=nonstopmode -file-line-error thesis.tex
```

The output is `thesis/thesis.pdf`. It remains ignored by Git and is published
by the GitLab `build_thesis` job instead.

## Project status

The thesis implementation and evaluation artefacts are complete. GitLab Issues
remain available for historical task tracking.
