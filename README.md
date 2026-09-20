# Integrating Open Large Language Models into the Jupyter Notebook Reproducibility Pipeline

**Student:** Erisa Zaimi
**Supervisor:** Dr. Sheeba Samuel
**Program:** M.Sc. Web Engineering — TU Chemnitz
**Period:** 2025–2026

## Thesis PDF

**[Download the latest thesis PDF](https://gitlab.hrz.tu-chemnitz.de/vsr/edu/advising/ma-erisa-zaimi/-/jobs/artifacts/i9-llm-model-sensitivity-evaluation/raw/thesis/thesis.pdf?job=build_thesis)**
— or [browse the build artifacts](https://gitlab.hrz.tu-chemnitz.de/vsr/edu/advising/ma-erisa-zaimi/-/jobs/artifacts/i9-llm-model-sensitivity-evaluation/browse/thesis?job=build_thesis).

The PDF is not stored in Git. It is built from the LaTeX sources under `thesis/`
by the GitLab CI job `build_thesis`, and the links above always resolve to the
latest successful build of the `i9-llm-model-sensitivity-evaluation` branch.

## Overview

This thesis extends the [FAIR Jupyter](https://github.com/fusion-jena/FAIR-Jupyter)
reproducibility pipeline, which detects and logs notebook execution failures but
does not explain or repair them. The added layer classifies dependency errors,
explains each one in plain language with a locally served open LLM, and derives a
repair proposal grounded in live PyPI release data rather than in the model's own
memory. Each proposal is applied and validated by rebuilding a Docker environment
and re-executing the notebook from start to finish. Every attempt, including every
abstention, is logged in a structured SQLite table that is exported and mapped to
RDF triples linked to the FAIR Jupyter knowledge graph.

## Pipeline

```
Dependency failure
  → ErrorClassifier     (is it a repairable dependency error?)
  → LLMExplainer        (plain-language explanation)
  → RAGRepairAgent      (PyPI-grounded repair proposal, or abstention)
  → FixApplicator       (apply the fix in a rebuilt Docker environment)
  → Re-execution        (run the notebook top to bottom to validate)
  → ResultLogger        (SQLite table → CSV → RDF)
```

A newly exposed error is carried through one bounded second round, after which the
pipeline stops.

## Repository Structure

```
├── thesis/     # LaTeX sources of the thesis
├── scripts/    # Pipeline components and evaluation tooling
├── tests/      # Automated test suite for those components
├── data/       # Dataset, evaluation runs, and result files
└── docs/       # Design notes and supporting documentation
```

## Progress Tracking

Tasks and milestones are tracked via [GitLab Issues](../../issues).

## References

Full references are listed in the thesis document.
