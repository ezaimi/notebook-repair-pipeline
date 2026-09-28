# Thesis Demo — Dependency Repair Pipeline

Two static interfaces live in this folder.

| Entry point | What it is |
| --- | --- |
| `index.html` | **Recorded Trace Viewer** (current). Record list + per-record stage-by-stage trace of one recorded run. This is what the thesis figures show. |
| `legacy-app.html` | Earlier multi-page walkthrough (overview, notebook table, repair workspace, evaluation summary, Gemma-vs-Qwen comparison, knowledge graph). Kept as-is; its documentation follows further below. |

Both are plain HTML/CSS/JS: no build step, no framework, no backend, and no
call to Ollama, Docker, PyPI or GitHub. Every screen replays artefacts that an
earlier, actual pipeline execution wrote to disk.

## Running it

From the repository root:

```bash
cd demo-mockup
python -m http.server 8000
```

Then open <http://localhost:8000> for the Recorded Trace Viewer, or
<http://localhost:8000/legacy-app.html> for the earlier interface.

Serve over `http://localhost` rather than double-clicking the file from a
`\\wsl.localhost\...` path: some browsers restrict script loading from
network-style paths and the page then renders blank.

---

# Recorded Trace Viewer (`index.html`)

```
index.html                   page shell
css/pipeline.css             all styling for this interface
js/pipeline-demo.js          record list + trace view, hash-routed
data/pipeline_demo.js        GENERATED — every value shown on screen
build_pipeline_demo_data.py  regenerates data/pipeline_demo.js
```

## What it shows

**Record list** (`#/records`) — the provenance of the run being displayed, a
colour key for the six roles a package name can occupy, one highlighted record
per decision path, and a filterable table of every record in the run.

**Trace view** (`#/trace/<id>[/<round>][/<phase>]`) — one notebook across nine
stages, grouped into three phases:

| Phase | Stages |
| --- | --- |
| `read` | 1 recorded failure · 2 classification and scope · 3 explanation |
| `ground` | 4 candidate generation · 5 PyPI and wheel verification · 6 repository dependency context · 7 repair decision |
| `apply` | 8 fix application and re-execution · 9 result |

A record with a second round gets a round selector and a banner stating why
round 2 ran. A record whose newly exposed error falls outside the
pip-installable scope shows that error's explanation with no following repair
round. Abstentions show the recorded reason instead of a command.

The six roles are colour-coded consistently: requested import, candidate
distribution, verified distribution, selected repair, applied repair, Docker
outcome.

`?shot=1` narrows the measure and enlarges the base font for figure capture;
`?theme=light|dark` forces a theme. Neither changes what is displayed.

## Data provenance

`data/pipeline_demo.js` is generated, never hand-edited, by
`build_pipeline_demo_data.py` from the recorded run

- `data/evaluation/v2-evaluation-20260925T013000Z/` — Gemma (`gemma2:9b` via a
  local Ollama service), evaluation split, `max_rounds = 2`, 187/187 records,
  18/18 integrity checks passed, code commit `0e5c621787`.

Files read (all read-only):

- `<run>/raw/pipeline-runs/<run>.jsonl` — the round-by-round trace: classifier
  input, explanation, deterministic mapping attempts and any model proposal,
  PyPI retrieval with per-release wheel import verification, the repository
  dependency-declaration context, the repair decision, the applied command and
  the Docker re-execution outcome, plus the round-2 trigger with its
  reclassified record and explanation.
- `<run>/manifest.json`, `<run>/validation_report.json` — the provenance strip
  (local absolute paths are not copied).
- `data/context-classification-v2/dependency_error_contexts.jsonl` — notebook
  name, repository URL and commit, classifier confidence, failing cell index.

The script is pure extraction: it never calls an LLM, Docker or PyPI, never
recomputes an outcome, and derives no evaluation metric. Its only
transformation is that the retriever logs one warning per skipped legacy
installer filename, so `pypi.warnings` keeps the first three plus an explicit
"... N further filename warnings omitted" marker.

Regenerate from the repository root:

```bash
python demo-mockup/build_pipeline_demo_data.py          # rewrite the data file
python demo-mockup/build_pipeline_demo_data.py --check  # report drift, write nothing
```

## Records used in the thesis figures

| Record | Decision path it exercises |
| --- | --- |
| #198 | model chose a version among verified releases; Docker reported `fixed` |
| #306 | second round: the first repair exposed a new eligible dependency error |
| #79 | curated `cv2` → `opencv-python` mapping, then a system-library error that is explained only |
| #52 | distribution exists on PyPI, but no wheel evidence that it provides the import → abstain |
| #24 | every deterministic source failed; the model's proposal failed verification → abstain |
| #145 | the model proposed a distribution name that then passed verification |

---

# Earlier interface (`legacy-app.html`)

The documentation below describes the earlier multi-page walkthrough, which is
unchanged and still served from `legacy-app.html`. It replays a different pair
of recorded runs.

## How to run it (one command)

From the repository root:

```bash
cd demo-mockup
python -m http.server 8000
```

Then open **http://localhost:8000** in a browser.

(Any static file server works — `npx serve .`, VS Code's "Live Server" extension,
etc. A plain `python3` / `py -m http.server` also works on Windows.)

Do **not** just double-click `index.html` from a `\\wsl.localhost\...` network
path — some browsers apply extra restrictions to script loading from network-style
paths and the page can render blank. Serving over `http://localhost` avoids this
entirely and is the reliable option for the meeting/defense.

## What's inside

```
demo-mockup/
  index.html            single-page app shell (sidebar + router)
  css/style.css         all styling
  js/
    app.js              hash router (#/dashboard, #/notebooks, #/workspace/<id>[/<stage>],
                        #/evaluation, #/comparison, #/kg, #/settings)
    dashboard.js         Overview page (final Gemma results, pipeline with Round 2, showcase cases)
    notebooks.js         Notebook Failures table + quick filters
    workspace.js         Repair Workspace (the centerpiece: Round 1, Round-2 section, story rail)
    evaluation.js         Evaluation Summary page + Gemma-vs-Qwen comparison page
    kg.js                 Knowledge Graph (one notebook's RDF neighborhood)
    settings.js           theme toggle + provenance cards for both recorded runs
    format.js             shared formatting/render helpers
  data/
    cases.js             187 full per-notebook pipeline traces (Gemma i10, round-by-round,
                         incl. the Round-2 reclassified record and its explanation)
    notebook_list.js     all 187 Notebook Failures table rows + filter flags
    evaluation.js         frozen metrics for Gemma i10 and Qwen i11, the paired
                          comparison, provenance, dataset stats, human study
  build_demo_data.py     regenerates all three data files
```

Nothing here talks to Ollama, Docker, PyPI, or GitHub. Every screen replays a
**recorded run** — a real trace produced by an earlier, actual pipeline execution.

## Data provenance

`demo-mockup/data/*.js` is generated (not hand-written) by `build_demo_data.py`
from these repository outputs. The demo replays two recorded runs:

- **Main run (every notebook replay):** Gemma-2 9B (`gemma2:9b` via Ollama),
  `data/evaluation/i10-eval-gemma-round2-explanations-20260918T161356Z/`
- **Sensitivity run (comparison page only):** Qwen3.6-35B-A3B-MLX-8bit via Kiste,
  `data/evaluation/i11-eval-qwen-round2-explanations-20260919T131359Z/`

Both processed 187/187 evaluation notebooks with `max_rounds = 2`, passed all 18
integrity checks, and executed from commit `46d90aa4ac41617bf4b88cabb346ac1248e811d0`.

Files read (all read-only):

- `<run>/raw/pipeline-runs/<run>.jsonl` — round-by-round trace per notebook:
  classifier input, the Round-1 explanation, PyPI retrieval, repair proposal, fix
  application, re-execution outcome, the Round-2 trigger decision with the
  reclassified `round2_record` **and its own Round-2 explanation**, and the
  executed Round-2 entry where one exists.
- `<run>/summary/per_notebook_comparison.csv` — per-notebook final categories and
  targeted-error-resolved flags.
- `<run>/summary/evaluation_summary.json` — every aggregate on the Overview,
  Evaluation Summary and comparison pages (explanation completion / schema
  validity, abstentions, proposal validity, grounding, targeted resolution,
  Round-2 funnel, final outcomes, classifier and PyPI manual-validation scores).
- `<run>/manifest.json`, `<run>/validation_report.json` — provenance cards
  (absolute local paths are not copied).
- `data/dependency-errors/dependency_errors.csv`, `statistics.json` — notebook
  metadata and dataset-composition counts (214 / 200 / 13 / 187).
- `data/context-classification/dependency_error_contexts.jsonl` — classifier
  confidence and, where available, the real traceback / failing cell source.
- `data/human-evaluation/analysis/human_evaluation_final_report.json` — the
  human study (15 participants, 90 evaluations, 540 ratings, 88.9 % agree,
  α = 0.928), which rated a frozen pool of 12 original-failure Gemma explanations
  only. Round-2 and Qwen explanations were not rated.
- `mapping/rml_mapping/repair_attempts.rml.ttl` — predicate names used in the
  Knowledge Graph view.

The Gemma-vs-Qwen page compares the two raw traces field by field. In the
recorded runs the 13 notebooks 189–201 differ only in the Round-1 pinned NumPy
version (Gemma `1.26.3`, Qwen `1.26.4`, both grounded candidates under `<2.0.0`);
every downstream outcome is identical.

Regenerate from the frozen artifacts (repository root):

```bash
python3 demo-mockup/build_demo_data.py          # rewrite the three data files
python3 demo-mockup/build_demo_data.py --check  # report differences, write nothing
```

The script is pure extraction. It never calls an LLM, Docker, or PyPI, and never
recomputes an evaluation outcome. The one transformation: PyPI retrieval logs one
"unparseable filename" warning per skipped sdist/wheel, so `retrieval.warnings`
keeps the first 3 plus an explicit "... N more ... omitted" marker.

## What the Repair Workspace shows

Round 1: Original Failure → Classification → LLM Explanation → [repair-eligible
gate] → Retrieval & Repair Proposal → Fix Application → Re-execution. If
re-execution exposed a genuinely new error, a Round-2 section opens: Newly
Exposed Failure → Reclassification → New Explanation (of the new error, never
the original) → [repair-eligible gate] → Retrieval & Repair Proposal → Fix
Application → Re-execution → Final Result. The gate is not a pipeline
component: it is the orchestrator's decision derived from the classification
(subtype + scope), drawn as a small pill. For a newly exposed error outside
the pip-only scope the Round-2 row reads New Error → Reclassify → New
Explanation → not repair-eligible → stop. Two rounds is the hard cap. A newly exposed error outside the
pip-only scope (`system_library`, `out_of_scope`) is explained but not repaired;
its explanation is trace-only and creates no Round-2 repair row (notebooks #79
and #134 in the final run). Stages can be deep-linked as
`#/workspace/<case id>/<stage number>`.

## Execution environment note

Provenance-specific checkout is supported by FixApplicator and was validated
separately. In the final WSL evaluation runs, repository metadata was unavailable
to FixApplicator because of a local path mismatch, so repositories were cloned
from their default branches. This applied equally to Gemma and Qwen. The demo
shows this in the Settings / Evaluation "Execution environment note" panels and as
`commit_checkout_status: skipped_no_commit` on each fix-application step.

## Presenting it

- **Overview** opens on the final Gemma results and ten showcase notebooks
  (#164, #158, #163, #79, #134, #21, #203, #189, #445, #370), each a real record.
- **Notebook Failures** lists all 187 notebooks; the quick filter finds Round-2
  triggered / repair-eligible / repaired / abstained records, the two
  explained-but-not-eligible records, Round-1 abstentions, targeted-error
  resolutions, still-failing, infrastructure and method failures, and the 27
  explanation runtime failures.
- **Repair Workspace** → *Next* / *Play Replay* walks through Round 1 and, where
  one exists, the Round-2 section. The right-hand "story" rail lists every stage
  and the Final Result card keeps "targeted error resolved" and "notebook fully
  fixed" apart.
- **Gemma vs Qwen** puts the two runs side by side, explanation and repair
  metrics separately, and lists the 13 NumPy version-selection differences.
