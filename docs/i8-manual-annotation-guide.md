# I8 Manual Annotation Guide

This guide explains exactly what to fill in on the two frozen manual
ground-truth sample files. The sample **selection** (which record IDs /
import names appear) is frozen and must not change — see
`docs/i8-evaluation-methodology.md` and `scripts/freeze_manual_samples.py`.
Only the blank columns described below are yours to fill in.

**Do not look at, or use, any downstream repair outcome (fixed /
still_failing / apply_error) when deciding a label below.** These are
classification/resolution-correctness judgments about the *input* alone —
whether the classifier's decision or the PyPI mapping was correct given
only the error message and import name, independent of whether the
pipeline later happened to repair the notebook. A record can be correctly
classified `usable` and still end up `still_failing`, and a misclassified
record can coincidentally get "fixed" by a spurious proposal — mixing the
two would corrupt the classifier/resolution evaluation with information
from an unrelated downstream component.

**Do not copy the `predicted_*` / `pipeline_resolved_distribution` column
into the manual column just because it looks reasonable.** Those columns
are reference context only. Decide the label independently by reading the
`error_type`/`error_message` (classifier sample) or by checking the real
PyPI package yourself (resolution sample), then write down what you
actually believe is correct — including when that agrees with the
prediction.

## 1. `data/manual-ground-truth/classifier_ground_truth_sample.csv`

49 rows (10 `system_library` + 4 `mapping_unknown`, exhaustive; 15
`wrong_version` + 20 `missing_package`, stratified). Three columns to
fill, one row at a time:

| Column | What to write |
|---|---|
| `manual_scope_status` | `usable` if this is genuinely a pip-installable dependency problem in scope for automated repair; `excluded` if it genuinely requires a system library, is an ambiguous local/module-path import, or otherwise falls outside pip-only repair scope. Judge this from `error_type`/`error_message` alone. |
| `manual_subtype` | One of `missing_package`, `wrong_version`, `system_library`, `mapping_unknown` (or a new label if none of these genuinely fit — write it and add a note). |
| `manual_failing_module` | The **top-level** failing dependency/module the classifier is intended to extract — not the full dotted submodule path, even when the error message names a specific submodule. Not necessarily identical to `predicted_failing_module`; write down what you independently believe is correct. |

**Top-level-module rule, applied consistently to every row:** if the error
names a submodule (`package.submodule...`), record only the top-level
package name. This keeps the metric well-defined and reproducible instead
of depending on how deep into a dotted path a given error message happens
to go.

| Error message names | `manual_failing_module` |
|---|---|
| `scipy.integrate` | `scipy` |
| `scipy.sparse.sputils` | `scipy` |
| `bokeh.tile_providers` | `bokeh` |
| `mpl_toolkits.axes_grid` | `mpl_toolkits` |
| `utils.image_processor` | `utils` |
| `libxcb.so.1` (already top-level) | `libxcb.so.1` |

For a shared-library error (`lib*.so.N: cannot open shared object file: No
such file or directory`), the module is the library filename at the start
of the message (e.g. `libxcb.so.1`) — never a word copied from later in
the boilerplate text (e.g. "directory").

Use `notes` for anything ambiguous or worth flagging (e.g. "could be
either wrong_version or missing_package, message is unclear").

## 2. `data/manual-ground-truth/pypi_resolution_sample.csv`

20 rows (8 import names already mapped in `config/package_mapping.yaml`
and actually exercised by the dataset, plus the 12 most frequently
exercised import names that are **not** mapped — several of these,
e.g. `rpy2`, `cana`, `celloracle`, `keras`, `statsmodels`, are plausibly
real PyPI packages the current static mapping simply doesn't cover; that
gap is expected and must not be fixed as part of labeling this sample).
One column to fill:

| Column | What to write |
|---|---|
| `manual_correct_distribution` | The PyPI distribution name you believe is actually correct for this `import_name`, checked independently (e.g. against pypi.org) — regardless of what `pipeline_resolved_distribution` shows, including when it is blank. If no real PyPI distribution provides this import, leave it blank and say so in `notes`. |

Use `notes` for anything worth flagging (e.g. "package renamed/deprecated
on PyPI", "ambiguous — multiple candidate distributions").

## Interpreting the resulting metrics — sample, not population

Both samples are deliberately **not** simple random samples of their
respective populations, so any accuracy computed from them describes
**performance on that sample**, not a population-wide estimate, unless
stated otherwise:

- The classifier sample (49 rows) intentionally oversamples the rare
  subtypes (`system_library`, `mapping_unknown` taken exhaustively;
  `wrong_version`/`missing_package` stratified) — report results as, e.g.,
  "subtype classification accuracy was X% (Y/49) on the stratified
  49-record manual validation sample", never as "population-wide subtype
  accuracy". A prevalence-weighted re-estimate is only valid when the
  population weights come from an *independent* source — subtype counts
  taken from this same pipeline's own classification of all 214 records do
  not qualify (see `scripts/manual_ground_truth_scoring.py`'s
  `PREVALENCE_WEIGHTED_ACCURACY_CAVEAT`) — so that number must not appear
  in thesis-ready reporting unless a properly justified estimator replaces
  it.
- The PyPI resolution sample (20 rows) is a **diagnostic** sample —
  already-mapped names, frequent unmapped names, and a few ambiguous
  cases — not a representative random sample of every import name the
  pipeline will ever see. Report its accuracy as, e.g., "distribution-
  resolution accuracy on the 17 manually resolvable cases in the frozen
  20-name diagnostic sample", never as population-wide PyPI resolution
  accuracy.

## Optional: abstention correctness (bounded sample, later)

If/when a bounded manual review of abstained repair cases is done (per
`docs/i8-evaluation-methodology.md` §5, diagnostic only, not part of these
two frozen CSVs), the judgment is: given only the input error and the
retrieved PyPI evidence available at the time, was abstaining the right
call, or did a workable fix plausibly exist? This is a separate, later,
smaller exercise — no file for it exists yet.

## When to do this

Ideally, fill in both CSVs **before** inspecting any of the final
187-record evaluation results, so the labels can't be (even
unconsciously) influenced by what the pipeline achieved on the reserved
split.
