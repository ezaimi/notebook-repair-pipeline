# l2 — Deep Literature Review: APR, RAG, KG
**Thesis:** Integrating Open LLMs into the Jupyter Notebook Reproducibility Pipeline  
**Author:** Erisa Zaimi — TU Chemnitz, M.Sc. Web Engineering  
**Issue:** l2 | **Period:** 2026-05-10 → 2026-05-20  
**Version:** 3 — complete merged edition: full notes for all 30 references  
**Prepared:** May 2026

---

## Scope Note

This document covers **30 references** with full detailed notes for every paper. References [1]–[16] plus Lewis et al. and PROV-O are the original Vision Doc references (Track E). References [N1]–[N12] were identified during independent literature review and represent essential coverage that the Vision Doc does not include (Tracks A–D). The distinction matters for the thesis: the Related Work chapter must show independent literature discovery, not just citation of supervisor-suggested sources.

**Track A** — Python dependency resolution lineage (pre-LLM tools, [N1]–[N4])  
**Track B** — LLM APR: prompt engineering and model comparison ([N5]–[N7])  
**Track C** — Retrieval-Augmented Generation: foundations and code-specific surveys ([N8]–[N9])  
**Track D** — FAIR principles and knowledge graphs ([N10]–[N12])  
**Track E** — Vision Doc papers: full notes for [1]–[16], Lewis et al., PROV-O  
**Track F** — Synthesis: comparison table, positioning paragraph, design decisions, reading priorities

---

## Track A — Python Dependency Resolution: Pre-LLM Lineage

This track covers the historical progression of tools for automatically inferring and fixing Python dependency environments. These four papers form the direct technical ancestry of PLLM [5] and must be covered in thesis Section 3.3 to position the contribution correctly.

---

### [N1] Horton & Parnin (2019) — DockerizeMe
**Full title:** DockerizeMe: Automatic Inference of Environment Dependencies for Python Code Snippets  
**Reference:** ICSE 2019. doi:10.1109/ICSE.2019.00047. arXiv:1905.11127.  
**Authors:** Eric Horton, Chris Parnin (NC State University)

#### Core Contribution
The founding paper of Python automated dependency inference. DockerizeMe builds a **knowledge graph** using Libraries.io data stored in Neo4J, encoding package-to-module mappings and version relationships. For a given Python snippet, it queries this graph to infer required packages and outputs a Dockerfile for execution.

#### Key Findings
- Over 50% of public Python gists on GitHub fail with an import error in a clean environment.
- DockerizeMe resolves import errors in **892 out of ~3,000 gists** from the Gistable dataset — a ~30% improvement over the naive baseline.
- Knowledge acquisition is **not fully automated** — manual curation is required for the knowledge graph.
- Does not validate by execution; does not compare results against expected outputs.

#### Relevance to This Thesis
DockerizeMe is the **root of the dependency resolution tree** that ends with PLLM [5]. It establishes the Gistable dataset as the standard benchmark for this problem space. The knowledge-graph-based approach it introduces is what PyEGo [N2], PyCRE [N3], and ReadPyE [N4] improve upon, and what PLLM [5] eventually outperforms with RAG. Thesis Section 3.3 should trace this lineage from DockerizeMe to PLLM.

#### Thesis Chapter Placement
Section 3.3 (automated dependency resolution, pre-LLM baseline).

---

### [N2] Ye et al. (2022) — PyEGo
**Full title:** Knowledge-Based Environment Dependency Inference for Python Programs  
**Reference:** ICSE 2022. doi:10.1145/3510003.3510127.  
**Authors:** Hongjie Ye, Wei Chen, Wensheng Dou, Guoquan Wu, Jun Wei

#### Core Contribution
PyEGo extends DockerizeMe's knowledge-graph approach by building **PyKG** — a Neo4J graph with ~256,000 nodes and 1.9 million relationships, covering third-party packages, the Python interpreter, and system libraries jointly. It is the first tool to handle all three dependency types together.

#### Key Findings
- 34% of Python programs require specific Python interpreter versions; 24% require specific system libraries — yet prior tools (DockerizeMe, SnifferDog) only address third-party packages.
- PyEGo achieves **0.4× to 3.5× higher accuracy** than state-of-the-art approaches on 2,891 gists, 100 projects, and 4,836 Jupyter notebooks.
- Evaluated on the **same Gistable benchmark** as DockerizeMe, making results directly comparable.
- Requires frequent KG updates to stay current with PyPI releases — a known maintenance burden.

#### Relevance to This Thesis
PyEGo is **PLLM's primary baseline** — the paper PLLM directly competes against (+21.58% more fixes). Knowing PyEGo's mechanism (KG constraint solving) explains why RAG outperforms it: PyEGo can only suggest versions it has in the graph; RAG queries live PyPI data. This contrast is a key justification for the live-API retrieval design in thesis Step 2.

#### Thesis Chapter Placement
Section 3.3 (automated dependency resolution).

---

### [N3] Cheng, Zhu & Hu (2022) — PyCRE
**Full title:** Conflict-aware Inference of Python Compatible Runtime Environments with Domain Knowledge Graph  
**Reference:** ICSE 2022. doi:10.1145/3510003.3510078. arXiv:2201.07029.  
**Authors:** Wei Cheng, Xiangrong Zhu, Wei Hu (Nanjing University)

#### Core Contribution
PyCRE designs a **domain-specific ontology** for Python packages and builds knowledge graphs for 10,000+ packages in both Python 2 and Python 3. The key innovation is **conflict detection**: rather than just inferring packages, PyCRE explicitly checks for transitive dependency conflicts before outputting an environment specification.

#### Key Findings
- Addresses a major gap in prior tools: DockerizeMe and SnifferDog infer packages independently, ignoring conflicts between them.
- Uses SAT-solver-style constraint resolution over the KG to find conflict-free version combinations.
- Both PyCRE and PyEGo appeared at ICSE 2022, representing the state of the art in pre-LLM dependency resolution.

#### Relevance to This Thesis
PyCRE's conflict-awareness anticipates the version incompatibility error type that this thesis targets (in addition to ModuleNotFoundError and ImportError). Its KG ontology design is also a reference point for the RDF schema design in i6, since it shows how package-level relationships can be structured semantically.

#### Thesis Chapter Placement
Section 3.3 (automated dependency resolution, pre-LLM baseline).

---

### [N4] Cheng, Hu & Ma (2024) — ReadPyE
**Full title:** Revisiting Knowledge-Based Inference of Python Runtime Environments: A Realistic and Adaptive Approach  
**Reference:** IEEE Transactions on Software Engineering, vol. 50, no. 2, pp. 258–279, 2024. doi:10.1109/TSE.2023.3346474.  
**Authors:** Wei Cheng, Wei Hu, Xiaoxing Ma (Nanjing University)

#### Core Contribution
ReadPyE is the most recent KG-based baseline and the second PLLM baseline. It addresses the **incomplete domain knowledge** problem that limits PyEGo and PyCRE: when a module is unknown to the KG, these tools fail silently. ReadPyE introduces:
- A **naming similarity measure** to match unknown modules to candidate packages even when the module-to-package mapping is absent from the graph.
- **Iterative validation and adjustment**: the environment is tested, validation logs are parsed, and the configuration is adjusted based on matched exception templates.

#### Key Findings
- Resolves environment-related exceptions for **79.75% of single-file snippets**, 93% of Python projects, and 63.34% of program pairs.
- The iterative validation loop is conceptually similar to what PLLM [5] does with LLMs, but using rule-based exception template matching instead.
- Still limited to its KG's coverage — cannot reason about packages released after the last KG update.

#### Relevance to This Thesis
ReadPyE is **PLLM's second baseline** (+15.97% more fixes by PLLM). The iterative exception-template approach is the non-LLM equivalent of this thesis's repair loop. The comparison between ReadPyE's rule-based iteration and PLLM's LLM-based iteration is exactly the argument for why LLMs are better: they can generalise across new packages that don't yet exist in any fixed knowledge base — critical for a dataset as specialised as FAIR Jupyter's biomedical notebooks (anndata, scanpy, cemba_data are niche packages with limited KG coverage).

#### Thesis Chapter Placement
Section 3.3 (automated dependency resolution, immediate predecessor of LLM-based approaches).

---

## Track B — Automated Program Repair (APR): LLM Methods

*(Papers [5], [7], [8], [9], [12], [14], [15], [16] from the Vision Doc are documented in the v1 notes. Only new papers added below.)*

---

### [N5] Anonymous et al. (2025) — Empirical LLM Evaluation for APR
**Full title:** Empirical Evaluation of Large Language Models in Automated Program Repair  
**Reference:** arXiv:2506.13186, June 2025.  
**Authors:** (Multiple authors — published 2025)

#### Core Contribution
The most comprehensive empirical comparison of open-source LLMs specifically for automated program repair to date. Tests **four LLMs** — CodeLlama, LLaMA, StarCoder, DeepSeek-Coder — across sizes from 7B to 33B parameters, covering two bug scenarios (enterprise and algorithmic), three languages (Java, C/C++, Python), and **four prompt engineering strategies**, generating and analysing over **600,000 patches** across six benchmark datasets.

#### Key Findings
- Code-specialised models (CodeLlama, DeepSeek-Coder) consistently outperform general-purpose models (LLaMA) of comparable size on repair tasks.
- **Prompt strategy** has a comparable or larger impact on repair quality than model size — choosing the right prompting approach matters more than scaling up the model.
- Python-specific repair results are included — relevant given this thesis's target language.
- DeepSeek-Coder performs competitively with CodeLlama-34B at smaller sizes, making it a strong candidate for local deployment under NFR1.

#### Design Decisions Informed
- **LLM selection for l4**: directly informs the candidate shortlist. Based on this paper, the evaluation set should include at minimum: CodeLlama-13B, DeepSeek-Coder-7B/13B, and Gemma-2 9B (from PLLM [5] results).
- **Prompt strategy comparison**: the four strategies tested in this paper (zero-shot, few-shot, CoT, structured) map directly onto the prompt strategy experiment in l4.

#### Thesis Chapter Placement
Section 3.4 (LLM selection evidence), l4 design reference.

---

### [N6] Wei et al. (2022) — Chain-of-Thought Prompting
**Full title:** Chain-of-Thought Prompting Elicits Reasoning in Large Language Models  
**Reference:** NeurIPS 2022. arXiv:2201.11903.  
**Authors:** Jason Wei, Xuezhi Wang, Dale Schuurmans, Maarten Bosma, Brian Ichter, Fei Xia, Ed Chi, Quoc Le, Denny Zhou (Google Brain)

#### Core Contribution
The foundational paper showing that providing a model with **a series of intermediate reasoning steps** as part of the prompt — rather than asking directly for the answer — significantly improves performance on complex multi-step reasoning tasks. A simple few-shot chain-of-thought prompt (8 examples with reasoning steps) unlocks reasoning abilities that cannot be achieved with standard prompting at any scale.

#### Key Findings
- CoT prompting produces **striking empirical gains** on arithmetic, commonsense, and symbolic reasoning tasks — e.g., GPT-3 540B with CoT achieves 57% on GSM8K vs. 17% without.
- These gains emerge at scale: CoT does not help small models (<10B parameters) and mainly benefits models ≥100B.
- For smaller models, **zero-shot CoT** ("Let's think step by step") is an alternative.

#### Relevance to This Thesis
CoT is the standard structured prompting technique for tasks requiring multi-step reasoning — exactly what error explanation and fix generation require. The explanation step (Step 1) and fix suggestion step (Step 2) both require the LLM to reason through: (a) what the error means, (b) why it happened, (c) what package version is needed, (d) what the fix command should be. CoT prompting structures this as intermediate steps.

**Important constraint**: the original CoT gains are on very large models (100B+). For the open, locally deployable models used in this thesis (7–13B range), the impact may be smaller — but structured output prompting (asking the LLM to reason before answering) still helps with format consistency.

#### Thesis Chapter Placement
Section 3.4 (prompt strategy background), l4 prompt design reference.

---

### [N7] Dinh et al. (2024) — CodePromptEval
**Full title:** The Impact of Prompt Programming on Function-Level Code Generation  
**Reference:** arXiv:2412.20545, December 2024.  
**Authors:** Multiple authors

#### Core Contribution
Introduces **CodePromptEval**, a dataset of 7,072 prompts evaluating five prompt techniques — few-shot examples, persona assignment, chain-of-thought, function signature inclusion, and list-of-packages — on three LLMs (GPT-4o, Llama3, Mistral) for function-level code generation. Measures effect on correctness, similarity, and quality.

#### Key Findings
- Certain prompt techniques significantly influence code quality — but **combining multiple techniques does not necessarily improve** results further.
- **Few-shot examples** and **function signature inclusion** are the most consistently useful individual techniques.
- Including the **list of required packages** in the prompt is specifically useful for dependency-aware generation — directly relevant to this thesis.
- Interactions between techniques are complex and model-dependent.

#### Relevance to This Thesis
This paper provides empirical grounding for the **prompt strategy experiment** in l4. The finding that "list of packages" positively influences code generation quality is directly applicable to the repair prompt design: including the list of imports from the failing notebook, the requirements.txt content, and the PyPI metadata (retrieved by RAG) in the prompt is supported by this evidence. The finding that combining too many techniques can hurt performance cautions against over-engineering the prompt.

#### Thesis Chapter Placement
Section 3.4 (prompt engineering background), l4 design reference.

---

## Track C — Retrieval-Augmented Generation

*(Lewis et al. 2020 is documented in v1 notes. New papers added below.)*

---

### [N8] Gao et al. (2024) — RAG Survey
**Full title:** Retrieval-Augmented Generation for Large Language Models: A Survey  
**Reference:** arXiv:2312.10997 (submitted Dec 2023, revised Mar 2024, v5).  
**Authors:** Yunfan Gao, Yun Xiong, Xinyu Gao, Kangxiang Jia, Jinliu Pan, Yuxi Bi, Yi Dai, Jiawei Sun, Qianyu Guo, Meng Wang, Haofen Wang (Tongji University / Fudan University)

#### Core Contribution
The standard survey for RAG architectures in the LLM era. Defines a **three-tier taxonomy** of RAG paradigms:

| Tier | Name | Description |
|---|---|---|
| 1 | Naive RAG | Simple retrieve → generate; suffers from irrelevant retrieval and hallucination |
| 2 | Advanced RAG | Pre-retrieval query optimisation + post-retrieval re-ranking; addresses naive limitations |
| 3 | Modular RAG | Flexible pipeline with swappable retrieval, memory, routing, and generation modules |

Covers the tripartite RAG framework: **retrieval** (dense/sparse/hybrid), **augmentation** (how retrieved content is injected), and **generation** (how the LLM uses the context).

#### Key Findings
- RAG addresses three core LLM limitations: hallucination, outdated knowledge, and opaque reasoning.
- The **retriever-generator interface** — how retrieved content is formatted and injected into the prompt — is as important as retrieval quality.
- For domain-specific knowledge (e.g. PyPI package metadata), deterministic lookup (API call) is more reliable than similarity search; this is the Naive RAG variant and it is the right choice when the query is a precise identifier.
- Knowledge freshness is RAG's key advantage over fine-tuning: the retrieval corpus can be updated without retraining.

#### Relevance to This Thesis
This survey provides the **formal architectural vocabulary** for describing the PyPI RAG component in the thesis. The system this thesis builds is a **Naive RAG** variant (direct API lookup, no vector index) which is appropriate for the task. The thesis should explicitly classify its approach within the Gao et al. taxonomy and justify why Naive RAG suffices: the query is always a precise package name (no ambiguity requiring similarity search) and freshness is critical (PyPI releases change weekly).

#### Thesis Chapter Placement
Section 3.3 (RAG foundations, taxonomy reference), Section 5 Step 2 (design classification).

---

### [N9] Tao et al. (2025) — RACG Survey
**Full title:** Retrieval-Augmented Code Generation: A Survey with Focus on Repository-Level Approaches  
**Reference:** arXiv:2510.04905, October 2025 (v2: January 2026).  
**Authors:** Yicheng Tao et al.

#### Core Contribution
The first survey specifically on **Retrieval-Augmented Code Generation (RACG)**, covering retrieval strategies, generation paradigms, retrieval modalities (code, documentation, API specs, test cases), training paradigms, and evaluation protocols across repository-level approaches.

#### Key Findings
- RAG applied to code is most effective when retrieved context matches the **semantic level** of the task: API-level retrieval helps with API usage questions; version-level retrieval helps with compatibility questions.
- Repository-level context (related files, imports, dependency graphs) significantly outperforms snippet-level context for complex code generation tasks.
- The survey identifies **API knowledge retrieval** as a specific modality — retrieving API documentation and version specs for the packages involved in the target code — exactly what this thesis's PyPI RAG does.

#### Relevance to This Thesis
RACG provides the software-engineering-specific RAG context that the general Gao et al. survey [N8] lacks. The survey's API knowledge retrieval modality validates the PyPI JSON API approach as an established RACG pattern. This is the citation to use in Section 3.3 when arguing that live API metadata retrieval is a recognised and effective RAG strategy for code-related tasks.

#### Thesis Chapter Placement
Section 3.3 (RAG for code, validation of PyPI API approach).

---

## Track D — FAIR Principles and Knowledge Graphs

---

### [N10] Wilkinson et al. (2016) — The FAIR Guiding Principles
**Full title:** The FAIR Guiding Principles for Scientific Data Management and Stewardship  
**Reference:** Scientific Data, vol. 3, article 160018, 2016. doi:10.1038/sdata.2016.18.  
**Authors:** Mark D. Wilkinson, Michel Dumontier, IJsbrand Jan Aalbersberg, et al. (FORCE11 Working Group — 50+ authors from academia, industry, funding agencies)

#### Core Contribution
Defines the **FAIR principles** — the most widely adopted framework for research data management. FAIR stands for:

| Principle | Requirement |
|---|---|
| **F**indable | Data has persistent identifiers; metadata is registered/indexed |
| **A**ccessible | Data and metadata are retrievable via open protocols; metadata persists even if data is removed |
| **I**nteroperable | Metadata uses formal, shared vocabularies; cross-references to other datasets |
| **R**eusable | Data has clear usage licenses; provenance is detailed; meets domain-relevant standards |

Crucially: *"The FAIR Principles put specific emphasis on enhancing the ability of machines to automatically find and use the data."* FAIRness is not just for human readers — it is machine-actionable FAIRness.

#### Relevance to This Thesis
This is the **foundational paper** that the entire FAIR Jupyter project is built on. The thesis title refers to the "FAIR Jupyter pipeline" — without citing this paper, the thesis lacks its conceptual foundation. Specifically:
- The thesis's KG enrichment contribution (O6) directly serves the **R** (Reusable) principle: repair provenance makes the reproducibility dataset more reusable by explaining why failures occurred.
- The benchmark dataset (O4) serves the **F** and **A** principles: structured, queryable, with persistent identifiers.
- The open model requirement (NFR1) aligns with the **A** principle: data and methods accessible without proprietary lock-in.

Not citing Wilkinson et al. in a thesis about the FAIR Jupyter pipeline would be a serious omission noticed immediately by any examiner.

#### Thesis Chapter Placement
Section 1 (Introduction — first paragraph), Section 3 (background on FAIR), Section 5 Step 5 (KG Enrichment rationale).

---

### [N11] Barker et al. (2022) — FAIR4RS Principles
**Full title:** Introducing the FAIR Principles for Research Software  
**Reference:** Scientific Data, vol. 9, article 622, 2022. doi:10.1038/s41597-022-01710-x.  
**Authors:** Michelle Barker, Neil P. Chue Hong, Daniel S. Katz, Anna-Lena Lamprecht, Carlos Martinez-Ortiz, Fotis Psomopoulos, et al. (RDA FAIR4RS Working Group — 500+ contributors)

#### Core Contribution
Adapts the FAIR Data Principles specifically to **research software**, recognising that software has unique characteristics — executability, composite nature, continuous versioning — that require modification of the original FAIR principles. The **FAIR4RS Principles** (v1.0, 2022) are:

- **F**: Software and its metadata are findable (with version-specific identifiers)
- **A**: Software and metadata are accessible (via open, standardised protocols)
- **I**: Software uses and supports interoperability via community standards
- **R**: Software is reusable (with clear license, community standards, provenance)

Key addition vs. FAIR data: software must be **executable** to be reusable, not just downloadable — provenance must include execution environment information.

#### Relevance to This Thesis
Jupyter notebooks are research software. The reproducibility failures this thesis addresses are precisely FAIR4RS failures: notebooks are not reusable (cannot be re-executed) because their dependency environment is not documented. The FAIR4RS emphasis on **execution environment provenance** is the technical motivation for the entire FAIR Jupyter pipeline. The thesis's contribution extends this: not only documenting that a notebook fails (existing pipeline) but documenting *why* it fails and *what fixes work* (this thesis), which is execution environment provenance at a deeper level.

#### Thesis Chapter Placement
Section 1 (motivation — FAIR research software context), Section 3 (background), O6 KG enrichment rationale.

---

### [N12] Samuel & Mietchen (2024) — FAIR Jupyter Dataset on Zenodo
**Note:** This is the Zenodo dataset record that accompanies [2] and [3]. It is the actual data artefact used in this thesis. It should be cited separately from the papers.  
**Reference:** Zenodo dataset. doi:10.5281/zenodo.XXXXXXX (retrieve exact DOI from the fairjupyter repo).  
**Why it needs its own citation:** Citing the dataset separately from the paper is required under FAIR data principles (F2: data is described with rich metadata including a persistent identifier distinct from the paper's DOI). The thesis uses the dataset directly, not just the methods described in the paper.

#### Thesis Chapter Placement
Section 5 (Step 1 — data source), evaluation setup in Section 6.

---


## Track E — Vision Doc Papers: Full Notes

Full detailed notes for the 18 references from the Vision Doc, covering Tracks A (APR), B (RAG), and C (KG/FAIR Jupyter).

---

## Track A — Automated Program Repair (APR)

---

### [15] Yang et al. (2025) — APR Survey
**Full title:** A Survey of LLM-based Automated Program Repair: Taxonomies, Design Paradigms, and Applications  
**Reference:** arXiv:2506.23749, June 2025. Accepted at ACM TOSEM.  
**Authors:** Boyang Yang, Zijian Cai, Fengling Liu, Bach Le, Lingming Zhang, Tegawendé F. Bissyandé, Yang Liu, Haoye Tian

#### Core Contribution
The most comprehensive taxonomy of LLM-based APR to date, covering 63 systems published between January 2022 and June 2025. Organises repair systems into **four paradigms** defined by (a) whether model parameters are updated and (b) who controls the repair loop:

| Paradigm | Parameter update | Control authority | Typical latency | Batch-scalable? |
|---|---|---|---|---|
| Fine-tuning | Yes | Model | Low at inference | Yes |
| Prompting | No | Human / static prompt | Very low | Yes |
| Procedural pipeline | No | Deterministic script | Low–medium | Yes |
| Agentic framework | No | LLM agent (dynamic) | High | Poorly |

Two **cross-cutting layers** strengthen any paradigm: retrieval-augmented context and static/dynamic analysis augmentation.

#### Key Findings
- Agentic frameworks achieve the best results on multi-hunk and cross-file bugs but introduce significantly higher latency and complexity, making them expensive at scale.
- Procedural pipelines offer reproducible, controllable repair with moderate overhead — best fit for batch processing over thousands of notebooks.
- Retrieval- and analysis-augmented contexts improve repair quality across all four paradigms regardless of the base approach.
- Evaluation practice varies widely across papers; the survey proposes consolidating around pass@k on SWE-bench and Defects4J.

#### Design Decisions Informed
- **Paradigm choice:** This thesis adopts the **procedural pipeline** paradigm. The Yang et al. taxonomy directly justifies this: agentic latency and complexity scale poorly over 6,576 notebooks in batch. This is cited explicitly in thesis Section 3.4 and in the ablation study rationale (e3).
- **Augmentation layer:** The survey confirms that RAG strengthens any paradigm. This validates the PyPI-grounded RAG component described in Section 5, Step 2.

#### Thesis Chapter Placement
Section 3.4 (LLM-based Debugging and Repair), design rationale in Section 5 (Proposed Approach), evaluation framing in Section 6.1.

---

### [7] Grotov et al. (2024a) — Untangling Knots
**Full title:** Untangling Knots: Leveraging LLM for Error Resolution in Computational Notebooks  
**Reference:** arXiv:2405.01559, March 2024. Accepted at CHI 2024 Workshop on Human-Notebook Interactions.  
**Authors:** Konstantin Grotov, Sergey Titov, Yaroslav Zharov, Timofey Bryksin (JetBrains Research)

#### Core Contribution
First paper to specifically address LLM-based error resolution for the non-linear structure of computational notebooks. Two concrete contributions:
1. A **dataset of 10,000 Python notebooks with at least one thrown exception**, collected from GitHub and made publicly available.
2. An outline of the **agent-based approach** for LLM usage in notebooks, with research questions and quality estimation methodology.

#### Key Findings from the Dataset
- Most common error types in the 10,000 notebook dataset: **NameError (25%)**, followed by TypeError, AttributeError, and ModuleNotFoundError.
- NameError dominates because of the non-linear execution order characteristic of notebooks — cells are re-run out of order, leaving variables undefined.
- The dataset is valuable for evaluating error types that may not appear frequently enough in the FAIR Jupyter biomedical dataset (which is dominated by dependency errors).

#### Key Findings on the Agent Approach
- Proposes iterative LLM agent: observe error → generate fix → apply → re-execute → repeat.
- Identifies three key research questions for notebook repair agents: (RQ1) which error types can be resolved, (RQ2) what metrics evaluate agent performance in notebook context, (RQ3) how to handle notebook statefulness.

#### Design Decisions Informed
- The **dataset** from this paper is a candidate supplementary evaluation source for error types underrepresented in the FAIR Jupyter corpus (see evaluation Section 6.1 and benchmark dataset O4).
- The iterative agent design is acknowledged but **not adopted** in this thesis: Yang et al. [15] confirm agentic approaches are poorly suited for batch scale. The single-round procedural choice is directly contrasted against [7] in Section 3.5.
- RQ2 (what metrics to use) informs the evaluation design: beyond binary success/failure, per-cell failure location and error-type breakdown are tracked.

#### Thesis Chapter Placement
Section 3.4, Section 3.5 (gap statement), supplementary evaluation dataset note in Section 6.1.

---

### [8] Grotov et al. (2024b) — Debug Smarter, Not Harder
**Full title:** Debug Smarter, Not Harder: AI Agents for Error Resolution in Computational Notebooks  
**Reference:** arXiv:2410.14393, October 2024.  
**Authors:** Konstantin Grotov, Artem Borzilov, Maksim Krivobok, Timofey Bryksin, Yaroslav Zharov (JetBrains Research)

#### Core Contribution
Full implementation of the agent outlined in [7]. The agent is designed specifically for **notebook statefulness**: it captures runtime kernel state after each cell execution, not just the static cell text. The agent observes error output after each execution attempt, decides what to change, applies the fix, and tries again.

#### Key Findings
- Statefulness is the critical differentiator for notebook repair vs. script repair: the same cell can succeed or fail depending on which other cells have been run.
- The feedback-driven loop (execute → observe error → modify → re-execute) is the core mechanism enabling improvement over single-shot repair.
- The system is designed for **interactive use** — it requires a running Jupyter kernel and user context. It is not designed for autonomous batch processing.

#### Design Decisions Informed
- The **feedback loop principle** (re-execution output informs next repair step) is adopted in a reduced form in this thesis: after applying a fix and re-executing, the outcome is recorded and can be used in a two-round repair (the ablation study in e3).
- The **interactive requirement** is the key distinction: this thesis's system operates autonomously in batch without a running kernel or user, which is exactly the gap [8] leaves open.
- The statefulness insight informs the re-execution step design: the notebook must be re-executed top-to-bottom, not from the failing cell, to correctly test the fix.

#### Thesis Chapter Placement
Section 3.4, Section 3.5, design note in Section 5 (Step 3 — Fix Application and Re-execution).

---

### [12] Xia & Zhang (2024) — ChatRepair
**Full title:** Automated Program Repair via Conversation: Fixing 162 out of 337 Bugs for $0.42 Each using ChatGPT  
**Reference:** ISSTA 2024. doi:10.1145/3650212.3680323  
**Authors:** Chunqiu Steven Xia, Lingming Zhang

#### Core Contribution
ChatRepair uses a **conversation-driven repair loop**: it generates a code patch, runs the test suite, and if the patch fails, feeds the test failure back into the conversation as context for the next repair attempt. This feedback-driven iteration is the key innovation over single-shot prompting.

#### Key Findings
- Fixed 162 out of 337 bugs (48.1%) on Defects4J using ChatGPT, at an average cost of $0.42 per bug.
- Conversation history (previous failed patches + test output) significantly improves repair rate over single-shot prompting.
- The approach requires a **test suite** to validate patches — the oracle for "is the fix correct" is test passage, not output comparison.

#### Design Decisions Informed
- The **feedback loop structure** directly informs the ablation study design (e3): this thesis tests whether feeding the re-execution error output back for a second repair round improves success rate over single-shot, exactly as ChatRepair does with test feedback.
- The **test-suite oracle** problem is acknowledged in Section 6.4: unlike Defects4J, real-world notebooks do not have test suites. The validation oracle in this thesis is notebook re-execution success, not test passage. For a subset of notebooks with known correct environments, a stronger oracle is possible.
- The cost analysis motivates the use of open local models (NFR1): proprietary API costs at the scale of 6,576 notebooks would be substantial.

#### Thesis Chapter Placement
Section 3.4, Section 5 (Step 3), Section 6.1 (ablation), Section 6.4 (baseline comparison caveat).

---

### [5] Bartlett, Liem & Panichella (2025) — PLLM
**Full title:** The Last Dependency Crusade: Solving Python Dependency Conflicts with LLMs  
**Reference:** arXiv:2501.16191, January 2025 (v2: October 2025). Accepted at AgenticSE @ ASE 2025.  
**Authors:** Antony Bartlett, Cynthia Liem, Annibale Panichella

#### Core Contribution
PLLM is the closest existing work to this thesis. It is a **five-stage RAG pipeline** that iteratively resolves Python dependency conflicts using open LLMs augmented with live PyPI metadata. Key stages:

- **Stage A:** Infer required module names and Python version from the source file.
- **Stage B:** Assign versions to each module. With RAG: query PyPI for live metadata to avoid hallucinated versions. Without RAG: LLM infers versions from context.
- **Stage C:** Build and test the environment.
- **Stage D:** Observe execution feedback; if failure, parse error message with NLP.
- **Stage E:** Refine predictions and retry.

Evaluated on the **Gistable HG2.9K dataset** (real-world Python gists, not notebooks).

#### Key Findings
- RAG **consistently improves fix rates** across all tested LLMs.
- Best performing configuration: **Gemma-2 9B + RAG**.
- Outperforms knowledge-graph-based baselines: +15.97% over ReadPyE, +21.58% over PyEGo.
- Particularly effective for **machine learning projects** with complex dependencies (tensorflow, scipy).
- Standard library modules must be filtered before querying PyPI (they have no PyPI page).

#### PyPI RAG Implementation Details (critical for l5)
- Query structure: send package name to `https://pypi.org/pypi/<name>/json`.
- Fields used from response: `info.version` (latest), `releases` keys (all available versions), `info.requires_python`.
- PyPI metadata is injected into the prompt alongside the error context to prevent hallucinated version numbers.
- Import name ↔ install name mismatches are handled (e.g. `import cv2` → `pip install opencv-python`).

#### Design Decisions Informed
- **Primary baseline** for the e6 evaluation: PLLM is open-source and can be run on the FAIR Jupyter notebook set for direct comparison.
- **RAG design template:** Stage B of PLLM is the direct template for Step 2 of this thesis. The PyPI query structure and field inventory from PLLM are adopted.
- **Key differentiation:** PLLM is a standalone tool applied to general Python files; this thesis embeds equivalent RAG capability inside the FAIR Jupyter pipeline, with pipeline-sourced context (executions.msg, requirements.txt, notebook imports) enriching the prompt.
- The iterative multi-round design of PLLM is the motivation for the ablation study: does an additional repair round justify the extra latency?

#### Thesis Chapter Placement
Section 3.3 (primary reference), Section 5 (Step 2 design), Section 6.4 (primary baseline), l5 implementation reference.

---

### [14] Reyes et al. (2025) — Byam
**Full title:** Byam: Fixing Breaking Dependency Updates with Large Language Models  
**Reference:** arXiv:2505.07522, May 2025 (v3: February 2026).  
**Authors:** Frank Reyes, May Mahmoud, Federico Bono, Sarah Nadi, Benoit Baudry, Martin Monperrus

#### Core Contribution
Byam addresses **breaking dependency updates in Java projects**: when a library's API changes across versions, client code that depended on the old API breaks. Byam uses LLMs with context-rich prompts (build process diagnostics + API diffs between dependency versions) to generate updated client code. Evaluated on the **BUMP dataset**.

#### Key Findings
- Context richness is the key driver of success: the richest prompt configuration (P8, including full API diff + compilation error location) fixes **27% of full builds** and **78% of individual compilation errors**.
- A simpler zero-shot approach achieves only 19%, confirming that structured dependency context in the prompt matters.
- Multi-granularity evaluation at three levels: **build level** (full fix), **file level** (which files were repaired), **individual error level** (compilation error count before vs. after).
- Five LLMs tested: Gemini-2.0 Flash, GPT-4o-mini, o3-mini, Qwen2.5-32b, DeepSeek V3.

#### Relevance to This Thesis
- Byam targets Java + API-level breaking changes; this thesis targets Python + package-level dependency errors. The problem spaces are related but not identical.
- The **multi-granularity evaluation** structure is the key methodological borrowing: this thesis adopts a similar three-level breakdown — notebook level (fully fixed), cell level (failure cell moved or eliminated), error-type level (ModuleNotFoundError vs. ImportError repair rates).
- The principle of including **structured dependency context** in the prompt (rather than just the raw error) is confirmed by Byam and applied in this thesis's context assembly step.

#### Thesis Chapter Placement
Section 3.3 (comparative reference), evaluation design Section 6.1.

---

### [16] Tang et al. (2025) — SynFix
**Full title:** SynFix: Dependency-Aware Program Repair via RelationGraph Analysis  
**Reference:** Findings of ACL 2025, pp. 4878–4894, Vienna, Austria.  
**Authors:** Xunzhu Tang, Jiechao Gao, Jin Xu, Tiezhu Sun, Yewei Song, Saad Ezzini, Wendkûuni C. Ouédraogo, Jacques Klein, Tegawendé F. Bissyandé

#### Core Contribution
SynFix constructs a **RelationGraph** from a repository: nodes are code components (files, functions, classes), edges are dependency relationships (imports, calls, inheritances). When a bug is localised, SynFix expands one hop from the buggy node to retrieve the most relevant dependent components as additional context for the LLM patch generation step. This ensures repairs are consistent across interdependent components.

#### Key Findings
- Resolves **52.33%** of SWE-bench Lite (300 issues), **55.8%** of SWE-bench Verified (500 issues), **29.86%** of full SWE-bench (2,294 issues).
- Outperforms SWE-Agent, Agentless, and AutoCodeRover.
- The RelationGraph approach shifts repair from iterative exploration to **structured, deterministic localisation** — closer to the procedural pipeline paradigm than to agentic frameworks.

#### Relevance to This Thesis
- SynFix addresses general software bugs across a codebase; this thesis addresses a narrower, more structured problem (dependency imports in notebooks).
- The core principle — **include structured dependency context in the prompt** — is adopted. In this thesis, the analogous "RelationGraph context" is the set of: failing import statement, requirements.txt/environment.yml, other imports in the notebook, and PyPI metadata. This is simpler than a full RelationGraph but serves the same purpose of grounding the repair in dependency relationships.

#### Thesis Chapter Placement
Section 3.4 (mentioned as context-aware repair reference), prompt design justification in Section 5 Step 2.

---

### [9] Szalontai et al. (2024) — Fine-Tuning CodeLlama
**Full title:** Fine-Tuning CodeLlama to Fix Bugs  
**Reference:** Proc. ICRIC 2024, Lecture Notes in Electrical Engineering, vol. 1195, Springer.  
**Authors:** B. Szalontai et al.

#### Core Contribution
Systematic comparison of code-specialized vs. general-purpose LLMs for bug-fixing tasks. CodeLlama (7B, 13B, 34B) fine-tuned on bug-fix pairs is compared against larger general models.

#### Key Findings
- Smaller models **specifically trained on code** (CodeLlama) can match or outperform larger general-purpose models for code repair tasks.
- **Prompt design has a significant impact** on repair quality — the same model with different prompt formats produces substantially different results.
- Fine-tuning on a task-specific dataset improves precision, but the fine-tuned model is less generalizable.

#### Design Decisions Informed
- **LLM selection rationale** (l4): this paper motivates evaluating CodeLlama alongside general-purpose open models. The finding that code-specialized models perform well even at smaller sizes is important given NFR1 (open, locally deployable models only) and NFR4 (batch scalability).
- **Prompt sensitivity** directly motivates the prompt strategy design in l4: different prompt formats (zero-shot, few-shot, chain-of-thought, structured XML output) should be compared on a held-out sample before committing to a final prompt design.

#### Thesis Chapter Placement
Section 3.4, LLM selection justification in Section 5 (model choice), l4 design reference.

---

## Track B — Retrieval-Augmented Generation (RAG)

---

### Lewis et al. (2020) — Original RAG Paper
**Full title:** Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks  
**Reference:** NeurIPS 2020. arXiv:2005.11401.  
**Authors:** Patrick Lewis, Ethan Perez, Aleksandra Piktus, Fabio Petroni, Vladimir Karpukhin, Naman Goyal, Heinrich Küttler, Mike Lewis, Wen-tau Yih, Tim Rocktäschel, Sebastian Riedel, Douwe Kiela (Meta AI / UCL / NYU)

#### Core Contribution
Introduces RAG as a general framework combining **parametric memory** (pre-trained seq2seq model) with **non-parametric memory** (dense vector index of an external document corpus, queried via Maximum Inner Product Search). The model is fine-tuned end-to-end: for a query x, the top-K documents are retrieved, treated as latent variables, and the generator marginalises over predictions given each document.

Two formulations:
- **RAG-Sequence:** same retrieved documents condition the entire generated sequence.
- **RAG-Token:** different documents can condition each token position.

#### Key Findings
- RAG models outperform parametric-only seq2seq baselines on three open-domain QA benchmarks.
- Generated text is more **specific, diverse, and factual** than purely parametric baselines.
- The non-parametric memory can be updated without retraining: swap the document index.

#### Relevance to This Thesis
This paper provides the **formal vocabulary** for describing the RAG component in the thesis. The PyPI RAG in this thesis is a simplified, non-learned variant: instead of a dense vector index, it uses the **PyPI REST API as the retriever** (deterministic lookup by package name, no similarity search needed). The retrieved "documents" are PyPI JSON responses for the failing package. This simplification is justified because the query is always a single package name — similarity search adds no value over a direct API call.

The thesis should describe its RAG component in Lewis et al. terms: the **retriever** is the PyPI JSON API, the **document corpus** is PyPI package metadata, the **generator** is the open LLM, and the **query** is the failing package name extracted from the traceback.

#### Thesis Chapter Placement
Section 3.3 (RAG foundations), formal description in Section 5 Step 2.

---

### PyPI REST API — Technical Reference (not a paper)
**Endpoint:** `https://pypi.org/pypi/<package-name>/json`  
**Relevant fields for the RAG retriever:**

| Field path | Content | Use in prompt |
|---|---|---|
| `info.name` | Canonical package name | Confirm install name vs. import name |
| `info.version` | Latest stable version | Suggest pinned version for install |
| `info.requires_python` | Python version constraint | Environment compatibility check |
| `info.requires_dist` | List of dependencies | Transitive dependency context |
| `info.summary` | One-line description | Human-readable context in explanation step |
| `releases` | Dict of all released versions | Suggest closest compatible version |
| `releases.<ver>[*].upload_time` | Release date per version | Identify chronologically compatible version |
| `info.yanked` | Whether latest is yanked | Avoid suggesting yanked versions |

**Import name ↔ install name mismatches (must handle):**

| Import name | Install name |
|---|---|
| `cv2` | `opencv-python` |
| `PIL` | `Pillow` |
| `sklearn` | `scikit-learn` |
| `Bio` | `biopython` |
| `skbio` | `scikit-bio` |

A lookup table for common mismatches should be maintained as part of the RAG retriever component. For unknown mappings, the `import_name → install_name` inference can be delegated to the LLM (as PLLM does in Stage A).

**Design decision — direct API vs. vector store:**
A cached vector store (e.g. FAISS index of PyPI metadata snapshots) is not needed. The PyPI API returns live data in under 200ms per request and the query is always a deterministic package name lookup. For yanked or deleted packages, a fallback to the package history in `releases` is sufficient.

#### Thesis Chapter Placement
Section 5 Step 2 (implementation detail), l5 schema definition.

---

## Track C — Knowledge Graph / RDF

---

### [3] Samuel & Mietchen (2024) — FAIR Jupyter KG
**Full title:** FAIR Jupyter: A Knowledge Graph Approach to Semantic Sharing and Granular Exploration of a Computational Notebook Reproducibility Dataset  
**Reference:** Transactions on Graph Data and Knowledge, 2024.  
**Authors:** Sheeba Samuel, Daniel Mietchen

#### Core Contribution
Serialises the results of the FAIR Jupyter reproducibility pipeline into RDF triples, creating a queryable Knowledge Graph. The KG makes notebook reproducibility data FAIR (Findable, Accessible, Interoperable, Reusable) at the triple level: each notebook execution, its outcome, and its dependency metadata are represented as structured RDF.

#### Existing KG Structure (relevant predicates)
The KG uses a combination of standard vocabularies and a custom namespace:

- **Notebook identity:** each notebook has a URI linking to its repository and publication.
- **Execution results:** triples record execution success/failure, diff count, execution time.
- **Dependencies:** imported modules are recorded as triples linking notebook to module entities.
- **Publications:** DOI, authors, date linked via established bibliographic ontologies.

#### Gap for This Thesis (O6)
The existing KG records **what happened** (success/failure, error type) but not **what was attempted to fix it** or **what the outcome of the fix was**. This thesis adds a new layer of **repair provenance triples**:

```
<notebook_uri> :hadRepairAttempt <repair_event_uri> .
<repair_event_uri> a :RepairAttempt ;
    :errorType "ModuleNotFoundError" ;
    :failingModule "anndata" ;
    :appliedFix "pip install anndata==0.9.2" ;
    :fixOutcome "success" ;
    :llmModel "codellama-13b" ;
    :repairTimestamp "2026-07-15T14:22:00Z" .
```

#### Vocabulary Alignment Decision
- Existing FAIR Jupyter predicates for execution outcome should be **reused** where possible.
- New predicates for repair-specific information (fix type, LLM used, outcome) require a new namespace extension.
- **PROV-O** (`prov:Activity`, `prov:wasGeneratedBy`, `prov:used`) is a strong fit for representing the repair event as a provenance activity — see below.

#### Thesis Chapter Placement
Section 3.1 (measuring reproducibility background), Section 5 Step 5 (KG Enrichment), i6 implementation.

---

### [2] Samuel & Mietchen (2024) — GigaScience Pipeline
**Full title:** Computational Reproducibility of Jupyter Notebooks from Biomedical Publications  
**Reference:** GigaScience, vol. 13, p. giad113, 2024. doi:10.1093/gigascience/giad113  
**Authors:** Sheeba Samuel, Daniel Mietchen

#### Core Contribution
Large-scale empirical study of reproducibility rates for Jupyter notebooks associated with peer-reviewed biomedical publications. Introduces the 16-step, 4-phase FAIR Jupyter pipeline (the pipeline this thesis extends). Dataset: 10,389 notebooks from biomedical publications on PubMed Central.

#### Key Findings
- Low reproducibility rates in the biomedical domain, consistent with Pimentel et al. [4]'s general findings.
- Dependency-related errors (ModuleNotFoundError, ImportError) are the dominant failure cause.
- The pipeline produces the `db.sqlite` database with the `executions` table that this thesis reads.

#### Relevance to This Thesis
This is the **source dataset and pipeline** for this thesis. The l1 exploration confirmed: 5,562 notebooks with ModuleNotFoundError (53.5%), 1,014 with ImportError (9.8%), totalling 6,576 target notebooks (63.3%). The intervention point is after Phase 3 of this pipeline.

#### Thesis Chapter Placement
Section 1 (Introduction), Section 3.1, Section 5 (pipeline context).

---

### [1] Samuel et al. (2025) — Docker Containerisation
**Full title:** Containing the Reproducibility Gap: Automated Repository-Level Containerization for Scholarly Jupyter Notebooks  
**Reference:** arXiv:2604.01072  
**Authors:** Sheeba Samuel, Daniel Mietchen, Hoa Lo, Martin Gaedke

#### Core Contribution
Extends the FAIR Jupyter pipeline by wrapping each repository in a Docker container before running notebooks, recovering many notebooks that previously failed due to environment conflicts. Represents the current state-of-the-art of the pipeline as of 2025.

#### Key Gap (direct entry point for this thesis)
Even after containerisation, **notebooks that still fail just get their error logged** — no explanation, no fix. The Docker paper explicitly stops at logging the residual failure. This residual failure case is the thesis's entry point.

#### Thesis Chapter Placement
Section 3.2 (Restoring Reproducibility), Section 3.5 (gap statement), Section 1 (motivation).

---

### PROV-O — W3C Provenance Ontology
**Reference:** W3C Recommendation, April 2013. https://www.w3.org/TR/prov-o/  
**Core concepts relevant to this thesis:**

| PROV-O class/property | Use in repair KG |
|---|---|
| `prov:Activity` | The repair attempt itself |
| `prov:Entity` | The notebook (input), the fix (output), the error record |
| `prov:Agent` | The LLM used for repair |
| `prov:wasGeneratedBy` | Fix suggestion ← repair activity |
| `prov:used` | Repair activity used the error traceback + PyPI metadata |
| `prov:wasAssociatedWith` | Repair activity associated with the LLM agent |
| `prov:startedAtTime` / `prov:endedAtTime` | Repair attempt timestamps |

**Alignment decision:** Use PROV-O for the activity/provenance layer (repair event, timestamps, agent). Use the existing FAIR Jupyter namespace for notebook identity and error metadata. Define new predicates only for repair-specific domain data (fix type, outcome, LLM model name).

#### Thesis Chapter Placement
Section 5 Step 5 (KG Enrichment), i6 implementation.

---


---

## Track F — Synthesis (Updated)

---

### F1 — Full APR + Dependency Resolution Comparison Table

| Paper | Year | Approach type | Language | Uses RAG? | Batch? | Notebook? | Key metric |
|---|---|---|---|---|---|---|---|
| DockerizeMe [N1] | 2019 | KG-based inference | Python | ✗ | ✓ | ✗ | 892/3K gists fixed |
| SnifferDog [10] | 2021 | Static API analysis | Python (notebooks) | ✗ | ✓ | ✓ | 92.6% env inferred |
| PyEGo [N2] | 2022 | KG constraint solving | Python | ✗ | ✓ | ✓ | 0.4–3.5× vs. DockerizeMe |
| PyCRE [N3] | 2022 | KG + conflict resolution | Python | ✗ | ✓ | ✓ | Resolves conflicts |
| ReadPyE [N4] | 2024 | KG + iterative validation | Python | ✗ | ✓ | ✗ | 79.75% single-file |
| PLLM [5] | 2025 | RAG + LLM pipeline | Python | ✓ PyPI | ✓ | ✗ | +15–21% over KG baselines |
| Grotov [7] | 2024 | Agent (proposed) | Python (notebooks) | ✗ | ✗ | ✓ | Dataset + RQs |
| Grotov [8] | 2024 | Agent (implemented) | Python (notebooks) | ✗ | ✗ | ✓ | Repair rate by error type |
| ChatRepair [12] | 2024 | Conv. pipeline | Java/Python | ✗ | Limited | ✗ | 162/337 Defects4J |
| Byam [14] | 2025 | Prompt pipeline | Java | ✗ | ✓ | ✗ | 27% build / 78% error |
| SynFix [16] | 2025 | RelationGraph pipeline | General | Analysis-augmented | Limited | ✗ | 52% SWE-bench Lite |
| Szalontai [9] | 2024 | Fine-tuning | Java | ✗ | ✓ | ✗ | Patch accuracy |
| **This thesis** | **2026** | **RAG + LLM pipeline** | **Python (notebooks)** | **✓ PyPI** | **✓** | **✓** | **Re-exec success rate** |

**Reading the table:** This thesis is the only entry that is simultaneously: (a) LLM-based with RAG, (b) batch-capable, (c) notebook-specific, and (d) embedded in a reproducibility pipeline. That uniqueness is the contribution.

---

### F2 — Positioning Paragraph (Updated — for thesis Section 3.5)

The individual building blocks needed to close the FAIR Jupyter reproducibility repair gap are well-established in the literature. The progression of Python dependency tools — DockerizeMe [N1], PyEGo [N2], PyCRE [N3], ReadPyE [N4] — demonstrates that automated dependency inference is solvable, but knowledge-graph-based approaches are limited by their static graphs and cannot reason about unknown or recently released packages. PLLM [5] supersedes these by using RAG-grounded LLMs to query live PyPI metadata, achieving +15–21% improvement over the best KG baselines. Pipelines for detecting and documenting reproducibility failures at scale exist [1, 2, 3]. LLM agents specifically targeting notebook errors have been demonstrated by Grotov et al. [7, 8]. Interactive notebook repair tools exist (Jupyter AI [13]). Yet none of these systems are both embedded in a reproducibility pipeline and capable of autonomous batch repair with structured provenance output. The FAIR Jupyter pipeline stops at detecting failures; Grotov et al. require an interactive kernel and cannot scale to batch; PLLM operates on standalone Python files without pipeline context. This thesis closes that specific intersection: a RAG-grounded LLM repair layer embedded in the FAIR Jupyter pipeline, operating in batch over thousands of notebooks, recording repair provenance as FAIR-compliant RDF triples [N10, N11] that extend the FAIR Jupyter Knowledge Graph [3].

---

### F3 — Confirmed Design Decisions (Updated)

| Decision | Justification | Source(s) |
|---|---|---|
| Procedural pipeline paradigm (not agentic) | Agentic latency scales poorly in batch over 6,576 notebooks | Yang et al. [15] |
| Single-round default, two-round as ablation | Added round may improve results; empirical trade-off to measure | ChatRepair [12], Yang et al. [15] |
| PyPI REST API as RAG retriever (no vector store) | Direct name lookup; no similarity search needed; always live | PLLM [5], Gao et al. [N8] — Naive RAG |
| Gemma-2 9B as primary LLM candidate | Best PLLM configuration; open and locally deployable | PLLM [5], Szalontai [9] |
| CodeLlama / DeepSeek-Coder as secondary candidates | Code-specialised models competitive; strong at Python repair | Szalontai [9], [N5] |
| CoT prompting for explanation step | Structured reasoning improves multi-step LLM outputs | Wei et al. [N6] |
| Include package list + imports in prompt | List-of-packages inclusion improves dependency-aware code generation | CodePromptEval [N7] |
| Re-execute notebook top-to-bottom after fix | Statefulness means partial re-run cannot validate fix correctly | Grotov [8] |
| PROV-O for repair provenance RDF layer | Standard W3C vocabulary aligning with FAIR KG conventions | PROV-O, Wilkinson [N10] |
| PLLM as primary baseline | Open source; same task; can run on same notebook set | PLLM [5] |
| Multi-granularity evaluation (notebook/cell/error-type) | More informative than binary; matches established methodology | Byam [14] |
| Position approach as Naive RAG (not Advanced/Modular) | Direct API lookup; complexity not justified for this task | Gao et al. [N8] |
| Cite FAIR4RS for notebook-as-software framing | Notebooks are research software; execution env = reusability | Barker et al. [N11] |

---

### F4 — Reading Priority List (for remaining time today)

| Priority | Paper | Why urgent | Format |
|---|---|---|---|
| 🔴 Must read today | PLLM [5] arXiv:2501.16191 | Primary baseline; RAG template for l5 | Full PDF |
| 🔴 Must read today | Yang et al. [15] arXiv:2506.23749 | Paradigm taxonomy; justifies all design choices | Full PDF |
| 🟡 Read this week | Grotov [8] arXiv:2410.14393 | Re-execution design detail | Full PDF |
| 🟡 Read this week | Gao et al. [N8] arXiv:2312.10997 | RAG taxonomy for l5 description | Sections 1–3 |
| 🟡 Read this week | Wilkinson et al. [N10] doi:10.1038/sdata.2016.18 | FAIR foundation — must be able to explain all 15 principles | Full PDF (short) |
| 🟡 Read this week | Barker et al. [N11] doi:10.1038/s41597-022-01710-x | FAIR4RS — explains software-specific FAIR | Full PDF (short) |
| 🟢 Skim | DockerizeMe [N1] arXiv:1905.11127 | Know the KG approach; understand what PLLM beats | Abstract + Results |
| 🟢 Skim | PyEGo [N2] ICSE 2022 | Know PyKG structure; understand PLLM's baseline | Abstract + Table 2 |
| 🟢 Skim | ReadPyE [N4] IEEE TSE 2024 | Know iterative validation; understand PLLM's other baseline | Abstract + Sections 3–4 |
| 🟢 Skim | Wei et al. [N6] arXiv:2201.11903 | CoT foundations; know Figure 1 and main result table | Abstract + Section 3 |
| 🟢 Skim | Grotov [7] arXiv:2405.01559 | Dataset details; error type distribution | Abstract + Section 2 |
| 🔵 Optional | PyCRE [N3] arXiv:2201.07029 | Conflict-awareness concept | Abstract only |
| 🔵 Optional | RACG Survey [N9] arXiv:2510.04905 | API retrieval as RACG modality | Section on API retrieval |
| 🔵 Optional | CodePromptEval [N7] arXiv:2412.20545 | Prompt technique evidence | Results tables |
| 🔵 Optional | Empirical LLM APR [N5] arXiv:2506.13186 | LLM comparison data | Results tables |

---

### F5 — Complete Reference List

**Vision Doc References:**
[1] S. Samuel, D. Mietchen, H. Lo, M. Gaedke. arXiv:2604.01072.  
[2] S. Samuel, D. Mietchen. GigaScience, vol. 13, p. giad113, 2024.  
[3] S. Samuel, D. Mietchen. TGDK 2024.  
[4] J. F. Pimentel et al. MSR 2019.  
[5] A. Bartlett, C. Liem, A. Panichella. arXiv:2501.16191, 2025.  
[6] S. Samuel, B. König-Ries. arXiv:2006.12110, 2020.  
[7] K. Grotov et al. arXiv:2405.01559, 2024.  
[8] K. Grotov et al. arXiv:2410.14393, 2024.  
[9] B. Szalontai et al. ICRIC 2024, LNEE vol. 1195, Springer.  
[10] J. Wang, L. Li, A. Zeller. ICSE 2021.  
[11] J. Wang et al. ASE 2020.  
[12] C. S. Xia, L. Zhang. ISSTA 2024. doi:10.1145/3650212.3680323.  
[13] Jupyter AI. GitHub 2023.  
[14] F. Reyes et al. arXiv:2505.07522, 2025.  
[15] B. Yang et al. arXiv:2506.23749, 2025.  
[16] X. Tang et al. ACL 2025, pp. 4878–4894.  
[—] P. Lewis et al. NeurIPS 2020. arXiv:2005.11401.  
[—] PROV-O. W3C Recommendation, April 2013.

**Newly Discovered References:**  
[N1] E. Horton, C. Parnin. ICSE 2019. doi:10.1109/ICSE.2019.00047.  
[N2] H. Ye et al. ICSE 2022. doi:10.1145/3510003.3510127.  
[N3] W. Cheng, X. Zhu, W. Hu. ICSE 2022. doi:10.1145/3510003.3510078. arXiv:2201.07029.  
[N4] W. Cheng, W. Hu, X. Ma. IEEE TSE, vol. 50, no. 2, 2024. doi:10.1109/TSE.2023.3346474.  
[N5] Empirical LLM APR study. arXiv:2506.13186, 2025.  
[N6] J. Wei et al. NeurIPS 2022. arXiv:2201.11903.  
[N7] CodePromptEval. arXiv:2412.20545, 2024.  
[N8] Y. Gao et al. arXiv:2312.10997, 2024.  
[N9] Y. Tao et al. arXiv:2510.04905, 2025.  
[N10] M. D. Wilkinson et al. Scientific Data, vol. 3, 160018, 2016. doi:10.1038/sdata.2016.18.  
[N11] M. Barker et al. Scientific Data, vol. 9, 622, 2022. doi:10.1038/s41597-022-01710-x.  
[N12] FAIR Jupyter dataset. Zenodo (retrieve exact DOI from fairjupyter repo).
