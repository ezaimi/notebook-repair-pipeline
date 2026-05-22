# Chapter 3 — State of the Art
**Thesis:** Integrating Open Large Language Models into the Jupyter Notebook Reproducibility Pipeline  
**Author:** Erisa Zaimi — TU Chemnitz, M.Sc. Web Engineering  
**Prepared:** May 2026 | Issue l2

---

## Purpose of This Outline

This document defines the structure, content, and paper assignments for Chapter 3 (State of the Art) of the thesis. It serves as the outline deliverable required by the TU Chemnitz guideline.

Each section lists: the argument to be made, the papers that support it, and the approximate length target.

---

## Chapter Overview

Chapter 3 surveys four areas of prior work that collectively define the landscape this thesis operates in:

1. The reproducibility problem in Jupyter notebooks and how it has been measured
2. Existing approaches to restoring reproducibility through environment inference and containerisation
3. The evolution of Python dependency resolution tools, from knowledge graphs to LLMs
4. LLM-based automated program repair: paradigms, prompt strategies, and notebook-specific work

It closes with a gap analysis that positions this thesis precisely at the intersection of these areas.

**Target length:** ~20 pages  
**Reference style:** IEEE

---

## 3.1 — Computational Reproducibility of Jupyter Notebooks

**Argument:** Reproducibility failure in Jupyter notebooks is a large-scale, well-documented problem — not an edge case. The FAIR Jupyter project addresses this specifically in the biomedical domain.

**Opening paragraph:** Define computational reproducibility in the notebook context. Distinguish between re-executability (does it run?) and reproducibility (does it produce the same outputs?). Establish that this thesis targets re-executability as a precondition for reproducibility.

### 3.1.1 — Scale of the Problem

- Pimentel et al. [4] (MSR 2019): 1.4M notebooks collected; only 24.11% ran without errors; only 4.03% reproduced original results. Establishes the scale and sets the benchmark.
- Samuel & Mietchen [2] (GigaScience 2024): Confirms the same pattern specifically for biomedical publications. This is the source dataset for this thesis — connect directly.
- Samuel & König-Ries [6] (ReproduceMeGit, 2020): Visualisation tool for checking notebook reproducibility on GitHub. Detects failures but does not fix them — sets up the detection-only gap.

**Key point to make:** These studies agree that dependency-related errors are the dominant failure cause, which motivates focusing on exactly that error class.

**~2 pages**

### 3.1.2 — The FAIR Jupyter Pipeline

- Samuel & Mietchen [2] + [3] (FAIR KG, TGDK 2024): Describe the 16-step pipeline and the Knowledge Graph layer built on top of it. This is the system this thesis extends — describe it in enough detail that the reader understands the architecture before reaching Chapter 4.
- Samuel et al. [1] (Docker, arXiv:2604.01072): The most recent extension, containerising each repository before execution. Even after this, residual failures are only logged, not explained or fixed. **This is the entry point for this thesis** — state it explicitly.
- Wilkinson et al. [N10] (FAIR, 2016): One paragraph explaining the FAIR principles as the conceptual foundation of the entire FAIR Jupyter project. All four letters; emphasis on machine-actionability and provenance.
- Barker et al. [N11] (FAIR4RS, 2022): One paragraph extending FAIR to research software specifically. Notebooks are research software; FAIR4RS R (reusable) requires execution environment provenance — this directly motivates the thesis's repair provenance output.

**~3 pages**

---

## 3.2 — Restoring Reproducibility: Environment Inference

**Argument:** Several tools attempt to automatically restore execution environments for Python code. They represent the state of the art before LLMs entered this space.

**Opening paragraph:** Distinguish between detecting failures (Section 3.1) and restoring executability. Frame this section as the pre-LLM technical lineage that PLLM [5] and this thesis build upon.

### 3.2.1 — Static Analysis Approaches

- Wang et al. [10] (SnifferDog, ICSE 2021): Static API analysis to infer required packages; 92.6% environment inference success. Works specifically on notebooks — cite the notebook result.
- Wang et al. [11] (ASE 2020): Foundational reproducibility assessment work. Identifies the environment inference problem formally.

**~1 page**

### 3.2.2 — Knowledge Graph Approaches

Present these in chronological order to show the evolution:

- Horton & Parnin [N1] (DockerizeMe, ICSE 2019): First KG-based approach. Libraries.io + Neo4J. 892/3K gists fixed. Limitation: manual KG construction, no execution validation.
- Ye et al. [N2] (PyEGo, ICSE 2022): Extends to Python interpreter + system libraries. PyKG: 256K nodes, 1.9M relationships. 0.4–3.5× improvement over DockerizeMe. Limitation: KG requires constant updates.
- Cheng et al. [N3] (PyCRE, ICSE 2022): Adds conflict detection — the first tool to explicitly resolve transitive dependency conflicts via constraint solving.
- Cheng et al. [N4] (ReadPyE, IEEE TSE 2024): Naming similarity + iterative validation. 79.75% success. The most recent KG baseline; one of PLLM's two direct comparators.

**Key point:** All KG-based approaches share a fundamental limitation — they cannot reason about packages absent from or outdated in their graph. This motivates the shift to LLMs with live retrieval.

**~2 pages**

---

## 3.3 — LLM-Based Python Dependency Resolution

**Argument:** PLLM demonstrates that RAG-grounded LLMs outperform all KG-based approaches for dependency resolution. It is the direct technical predecessor and primary baseline for this thesis.

- Bartlett et al. [5] (PLLM, 2025): Describe the five-stage pipeline in detail. Emphasise Stage B (RAG: live PyPI query → version data in prompt). Results: Gemma-2 9B + RAG achieves ~81% fix rate; +15.97% over ReadPyE, +21.58% over PyEGo. Especially effective for ML-heavy projects — relevant for the biomedical dataset's dominance of anndata/scanpy.
- Gao et al. [N8] (RAG Survey, 2024): Use this to formally classify PLLM and this thesis's approach within the Naive/Advanced/Modular RAG taxonomy. Both use Naive RAG (direct API lookup) — justify why this is appropriate for the task.
- Tao et al. [N9] (RACG Survey, 2025): API knowledge retrieval as an established RACG modality — validates the PyPI JSON API approach as recognised practice in retrieval-augmented code generation.
- Lewis et al. (RAG, NeurIPS 2020): One paragraph defining the formal RAG framework (parametric + non-parametric memory). Provides the vocabulary for describing the retrieval component precisely.

**Differentiation paragraph:** PLLM operates on standalone Python files; does not embed in a pipeline; uses multi-round iteration; provides no human-readable explanation; does not enrich a KG. This thesis addresses all four gaps. Position explicitly.

**~3 pages**

---

## 3.4 — LLM-Based Automated Program Repair

**Argument:** LLM-based APR is a rapidly maturing field. This section surveys the relevant paradigms and systems, with particular attention to notebook-specific work and prompt engineering strategies that inform this thesis's design.

**Opening paragraph:** Reference Yang et al. [15] as the organising framework — 63 systems, four paradigms. Use their taxonomy as the structural backbone of this section.

### 3.4.1 — Paradigms and Design Trade-offs

- Yang et al. [15] (APR Survey, 2025): Present the four-paradigm taxonomy table. Focus on the procedural pipeline vs. agentic trade-off. Explicitly state: this thesis adopts the procedural pipeline paradigm because agentic frameworks introduce latency and complexity that scale poorly across 6,576 notebooks in batch. The survey validates this choice.
- Reyes et al. [14] (Byam, 2025): Procedural pipeline for Java breaking dependency updates. Multi-granularity evaluation design (build / file / error level) — adopt for this thesis's evaluation.
- Tang et al. [16] (SynFix, ACL 2025): Structured dependency context as LLM input. RelationGraph analogy to this thesis's context assembly (traceback + requirements.txt + imports).

**~2 pages**

### 3.4.2 — Notebook-Specific LLM Repair

- Grotov et al. [7] (Untangling Knots, 2024): First dataset of buggy notebooks + agent design proposal. Dataset as supplementary evaluation resource. Key difference: general code errors, not dependency-specific; interactive, not batch.
- Grotov et al. [8] (Debug Smarter, 2024): Full agent implementation. Statefulness — notebook must be re-run top-to-bottom, not from the failing cell. Feedback loop design informs the ablation study (1-round vs. 2-round in e3).
- Xia & Zhang [12] (ChatRepair, ISSTA 2024): Conversation-driven repair loop; re-execution feedback into next repair prompt. Validates the O3 mechanism. Limitation: requires test suite oracle — flag this as the reason a subset-based ground truth comparison is used in Section 6.4.
- Jupyter AI [13]: Interactive notebook repair assistant. Contrast clearly: designed for manual single-notebook use, not autonomous batch pipeline operation.

**~2 pages**

### 3.4.3 — Prompt Engineering for Code Repair

- Wei et al. [N6] (Chain-of-Thought, NeurIPS 2022): Foundational CoT paper. Multi-step reasoning through intermediate steps. Applied to error explanation (Step 1) and fix generation (Step 2) in this thesis. Note the scale caveat: gains are stronger at 100B+ models; for 7–13B open models, structured output prompting is the practical form.
- Dinh et al. [N7] (CodePromptEval, 2024): Five prompt techniques evaluated on Llama3, Mistral, GPT-4o. Key finding: including list-of-packages in prompt improves dependency-aware code generation — directly justifies including the traceback + requirements.txt + imports in the repair prompt.
- Szalontai et al. [9] (Fine-tuning CodeLlama, ICRIC 2024): Code-specialised models at smaller sizes outperform larger general models; prompt design has comparable impact to model size. Justifies evaluating CodeLlama and DeepSeek-Coder as candidates in l4.
- Anonymous et al. [N5] (Empirical LLM APR, 2025): 600K+ patches across CodeLlama, LLaMA, StarCoder, DeepSeek-Coder. Confirms code-specialised models lead on Python repair; four prompt strategies compared. Direct input to LLM selection in l4.

**~2 pages**

---

## 3.5 — Gap Analysis and Contribution of This Thesis

**Argument:** The combination of capabilities required by this thesis does not exist in any single prior system. This section makes that case explicitly and positions each objective against the literature.

**Structure:** Prose argument (not bullet points), building from the four tracks above to a single clear conclusion.

**The argument to make in this section:**

Tools for detecting and documenting reproducibility failures at scale exist [1, 2, 3]. Tools for inferring Python execution environments exist, progressing from KG-based [N1, N2, N3, N4] to LLM+RAG [5]. LLM agents for fixing errors in notebooks specifically have been demonstrated [7, 8]. Interactive repair assistants exist [13]. RAG consistently improves LLM repair quality across all paradigms [15, N8].

Yet no existing system:
- Embeds LLM-based repair autonomously inside a reproducibility pipeline
- Operates in batch over thousands of notebooks without human intervention
- Combines dependency-targeted RAG repair with human-readable error explanation
- Records repair provenance as FAIR-compliant RDF triples back into a Knowledge Graph

PLLM [5] is the closest — but it operates on standalone Python files, not pipeline-embedded notebooks; uses multi-round iteration that cannot scale to thousands of cases; provides no explanation; enriches no KG. Grotov et al. [7, 8] are closest for notebooks — but require an interactive kernel and produce no structured output. Neither addresses the FAIR Jupyter pipeline's specific residual failure case [1].

**Close with:** A table mapping each thesis objective (O1–O6 from the Vision Doc) to the gap it fills and the prior work it builds on.

| Objective | Gap filled | Prior work built on |
|---|---|---|
| O1 — Error Explanation | No prior system explains failures in plain language in a pipeline context | Grotov [7, 8], Jupyter AI [13] |
| O2 — Fix Generation with RAG | No prior system embeds PyPI RAG repair inside a reproducibility pipeline | PLLM [5], Lewis et al. |
| O3 — Fix Validation | Re-execution validation not done autonomously in batch | ChatRepair [12], Grotov [8] |
| O4 — Benchmark Dataset | No benchmark exists for dependency repair in biomedical Jupyter notebooks | Grotov [7], Pimentel [4] |
| O5 — Pipeline Integration | FAIR Jupyter pipeline stops at logging; no repair layer exists | Samuel [1, 2, 3] |
| O6 — KG Enrichment | No system records repair provenance as FAIR RDF triples | Samuel KG [3], PROV-O, Wilkinson [N10] |

**~2 pages**

---

## Chapter 3 Summary Paragraph

*(Required by TU Chemnitz guidelines — each chapter ends with a half-page summary)*

Summarise the four tracks: the reproducibility problem is large-scale and dependency-dominated; environment inference has evolved from manual KGs to live-RAG LLMs; LLM APR is maturing with procedural pipelines being optimal for batch; notebook-specific repair exists but remains interactive and non-pipeline. The gap this thesis fills is clear, specific, and unaddressed by any combination of existing work.

---

## Paper Assignment by Section

| Section | Papers |
|---|---|
| 3.1.1 | [2], [4], [6] |
| 3.1.2 | [1], [2], [3], [N10], [N11] |
| 3.2.1 | [10], [11] |
| 3.2.2 | [N1], [N2], [N3], [N4] |
| 3.3 | [5], [N8], [N9], Lewis et al. |
| 3.4.1 | [14], [15], [16] |
| 3.4.2 | [7], [8], [12], [13] |
| 3.4.3 | [9], [N5], [N6], [N7] |
| 3.5 | All of the above (synthesis) |

**Total papers cited in Chapter 3: 28 out of 30**  
*(PROV-O and [N12] dataset record appear in Chapter 5 — Step 5 and evaluation setup)*
