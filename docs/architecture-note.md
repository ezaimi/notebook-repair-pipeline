# Pipeline Architecture Note
*Written after l1 exploration — May 2026*

## 1. The Existing FAIR Jupyter Pipeline

The base pipeline has 16 steps organized into 4 phases:

### Phase 1 — Discover
1. Search PubMed Central using query `(ipynb OR jupyter OR ipython) AND github`
2. Collect publication metadata via NCBI Entrez API (Biopython, XML format)
3. Extract publication metadata fields (title, DOI, authors, date)
4. Extract GitHub repository links from paper body text

### Phase 2 — Collect
5. Store all metadata in SQLite database (`db.sqlite`)
6. Check whether each linked GitHub repository is still accessible
7. Clone the repository if available
8. Collect execution environment information (requirements.txt, environment.yml, setup.py)

### Phase 3 — Execute
9. Prepare a fresh conda environment per repository
10. Install dependencies as listed in the repository requirements
11. Collect all `.ipynb` files from the repository
12. Run and reproduce each notebook top-to-bottom

### Phase 4 — Analyze
13. Compute diff between original and re-executed notebook outputs (nbdime)
14. Store reproducibility results back into the database
15. Check Python code styling (flakenb)
16. Aggregate and analyze reproducibility results

The pipeline is implemented in `archaeology/` scripts named `r0_main.py`, `r1_...`,
`r2_...` etc., each corresponding roughly to these phases.

---

## 2. Where This Thesis Intervenes (Step 5 in Vision Doc)

The existing pipeline stops at detecting and logging failures.
This thesis adds an LLM-based repair layer that activates after Phase 3
when a notebook execution fails due to a dependency-related error.

The intervention point is: after `executions` table row is written with
a non-null `reason` field matching the target error types.

Target error types (in scope):
- `ModuleNotFoundError`
- `ImportError`
- Version incompatibility errors

Explicitly out of scope:
- `FileNotFoundError` (missing data files — not programmatically fixable)
- `TimeoutError`, `PermissionError`, logical errors in notebook code

---

## 3. Database Schema (Relevant Tables)

The database `db.sqlite` contains 24 tables total.
The tables most relevant to this thesis are:

### `executions` — primary target table
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Primary key |
| `repository_id` | INTEGER | FK to repositories table |
| `notebook_id` | INTEGER | FK to notebooks table |
| `mode` | INTEGER | Execution mode (3 = first run, 5 = reproduction run) |
| `reason` | VARCHAR | Exception type e.g. `ModuleNotFoundError` |
| `msg` | VARCHAR | Full traceback text — contains package name and version info |
| `diff` | INTEGER | Output diff count |
| `cell` | INTEGER | Cell where failure occurred |
| `count` | INTEGER | Execution count |
| `timeout` | BOOLEAN | Whether execution timed out |
| `duration` | FLOAT | Execution time in seconds |
| `processed` | INTEGER | Whether execution was processed |
| `skip` | BOOLEAN | Whether notebook was skipped |

The `msg` column is the primary data source for the LLM repair layer.
It contains the full Python traceback, from which the failing module name
and version conflict details can be extracted via regex.

### Other relevant tables
- `notebooks` — one row per notebook file, links to repository
- `repositories` — one row per GitHub repository, links to publication
- `modules` — imported modules per notebook (from static analysis)

---

## 4. Key Findings from l1 Exploration

### Scale of the problem
- Total notebooks executed: **10,389**
- Notebooks with `ModuleNotFoundError`: **5,562** (53.5%)
- Notebooks with `ImportError`: **1,014** (9.8%)
- Combined dependency failure target: **6,576 notebooks** (63.3%)

### Top missing modules (ModuleNotFoundError)
Extracted by parsing `executions.msg` with regex `No module named '([^']+)'`:

| Rank | Module | Count | Domain |
|---|---|---|---|
| 1 | anndata | 1258 | Single-cell genomics |
| 2 | scanpy | 423 | Single-cell genomics |
| 3 | pandas | 177 | General scientific |
| 4 | cemba_data | 176 | Epigenomics |
| 5 | tensorflow | 149 | Deep learning |
| 6 | Bio | 108 | Bioinformatics (Biopython) |
| 7 | fastai | 103 | Deep learning |
| 8 | ALLCools | 84 | Epigenomics |
| 9 | pybedtools | 78 | Genomics |
| 10 | cobra | 71 | Metabolic modeling |

The dominant pattern is **biomedical/bioinformatics packages**, consistent
with the dataset's origin from PubMed Central. `anndata` alone accounts
for 22% of all `ModuleNotFoundError` cases.

### Top broken imports (ImportError)
Extracted by parsing `executions.msg` for import failure patterns:

| Rank | Module/Name | Count | Notes |
|---|---|---|---|
| 1 | Bio | 44 | Biopython version mismatch |
| 2 | pyspark | 40 | Version/API change |
| 3 | skbio | 20 | Scikit-bio API change |
| 4 | ete3 | 18 | Version mismatch |
| 5 | joblib | 14 | Version mismatch |
| 6 | mdtraj | 12 | MD trajectory analysis |
| 7 | calour | 12 | Microbiome analysis |

Note: `object` (30 occurrences) is a regex parsing artifact, not a real module.

### Key insight for LLM repair design
Several packages appear in **both** error lists (Bio, cobra, scanpy, mdtraj, rdkit).
This means the repair agent must handle two distinct scenarios per package:
- Package completely absent → `pip install <package>`
- Package installed but wrong version → `pip install <package>==<version>`

This is why PyPI-grounded RAG is necessary — the agent needs live version
data to distinguish these cases and suggest the correct pinned version.

---

## 5. Data Available at the Repair Intervention Point

When the pipeline reaches a failed notebook, the following data is
available to pass to the LLM repair agent:

From `executions` table:
- `reason` — the exception class name
- `msg` — full traceback including the specific module that failed

From `notebooks` table (via `notebook_id`):
- Path to the `.ipynb` file

From `repositories` table (via `repository_id`):
- GitHub URL
- Path to cloned repository (for reading requirements files)

From the cloned repository on disk:
- `requirements.txt` / `environment.yml` / `setup.py` — declared dependencies
- The `.ipynb` file itself — for reading import statements in cells

From PyPI (retrieved at repair time via RAG):
- Available versions of the failing package
- Current latest stable version
- Package metadata

This is the full context that will be assembled into the LLM prompt
for both the explanation step and the repair suggestion step.

---

## 6. Connection to Thesis Objectives

| Objective | Data source | Status |
|---|---|---|
| O1 — Error explanation | `executions.reason` + `executions.msg` | Data confirmed available |
| O2 — Fix generation | `msg` + PyPI RAG | Data confirmed available |
| O3 — Fix validation | Re-run notebook, write new `executions` row | Mechanism clear |
| O4 — Benchmark dataset | All of the above → SQLite output table | Schema to be designed |
| O5 — Pipeline integration | Insert after Phase 3 execution step | Integration point identified |
| O6 — Knowledge Graph | RDF triples from repair outcomes | Pending KG schema design |