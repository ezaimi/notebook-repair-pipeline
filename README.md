# MA Thesis: Integrating Open LLMs into the Jupyter Notebook Reproducibility Pipeline

**Student:** Erisa Zaimi  
**Supervisor:** Dr. Sheeba Samuel  
**Program:** M.Sc. Web Engineering — TU Chemnitz  
**Period:** 2025–2026

## Overview

This repository contains all materials for my Master's thesis, which extends the [FAIR Jupyter](https://github.com/fusion-jena/FAIR-Jupyter) reproducibility pipeline with an LLM-based layer that automatically explains and repairs dependency-related failures in Jupyter notebooks.

## Repository Structure

```
├── thesis/          # LaTeX source and PDF drafts
├── src/             # Pipeline extension source code
├── data/            # Benchmark dataset (errors, fixes, outcomes)
├── notebooks/       # Experiment notebooks
├── docs/            # Additional documentation and vision document
└── gantt/           # Project timeline and Gantt chart
```

## Scope

- Detect dependency errors (`ModuleNotFoundError`, `ImportError`, version conflicts)
- Generate plain-language explanations via a local open-source LLM
- Suggest and apply fixes using PyPI-grounded RAG
- Validate fixes by re-executing notebooks
- Enrich the FAIR Jupyter Knowledge Graph with repair provenance (RDF triples)

## Progress Tracking

Tasks and milestones are tracked via [GitLab Issues](../../issues). See `gantt/` for the project timeline.

## Setup

_To be documented as the implementation progresses._

## References

Full references are listed in the thesis document (`thesis/`).