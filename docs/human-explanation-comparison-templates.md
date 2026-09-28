# LLM versus deterministic explanation comparison: survey materials

Status: **new study material; not yet administered.** This document does not alter
the original human evaluation. It is a separate, blinded comparison that may be
given only to new participants after the study wording and consent procedure have
been checked.

## What to give participants

Use the same consent, background questions, instructions, six Likert-scale items,
and optional feedback questions as in
`docs/human-explanation-evaluation-questionnaire.md`. Do not tell a participant
whether an individual explanation is from the LLM or from the deterministic
template. Call each one simply **The explanation**.

Assign each new participant one of Variants A--D in round-robin order. The exact
assignment is stored in
`data/human-evaluation/comparison/human_evaluation_comparison_assignments.csv`.
Each variant contains six cases: three LLM explanations and three deterministic
ones. Every one of the twelve errors is shown twice across the complete design,
once in each form, but no person sees both forms for the same error.

The LLM explanations are the unchanged fields in
`data/human-evaluation/human_evaluation_examples.csv`. The deterministic texts
below are the baseline explanations. In the survey tool, show the error followed
by exactly one explanation selected by the assignment file.

Use this participant-facing introduction in place of the original introduction's
reference to one system:

> When a Jupyter Notebook fails because of a Python dependency problem, an
> automated system can generate a short, plain-language explanation of what went
> wrong. In this study, you will read real examples of such errors together with
> an automatically generated explanation. Please rate each explanation based only
> on the information shown. There are no right or wrong answers.

For every example, retain the original questions Q1--Q6 and the 1--5 scale. Do
not show a package-install command, a repair outcome, an LLM confidence value, or
the words "LLM", "template", or "baseline" to participants.

## Deterministic baseline explanations

These explanations follow fixed rules. Their wording is intentionally uniform:
the error type and message identify what Python could not load; the limitations
state what the available evidence cannot establish. They do **not** propose a
repair, because the comparison concerns the explanation component, not the repair
component.

### Example 1 — execution 62

**Error:** `ModuleNotFoundError: No module named 'sklearn'`

**Explanation:** Python could not find the module `sklearn` when the notebook was
executed. This means that the requested import was not available in the current
environment. The message identifies the missing import, but it does not by itself
show whether the required package is absent or whether the import name differs
from the package distribution name. The exact failing cell and dependency files
are not available, so the reason for the missing import cannot be determined
further.

### Example 2 — execution 79

**Error:** `ModuleNotFoundError: No module named 'cv2'`

**Explanation:** Python could not find the module `cv2` when the notebook was
executed. This means that the requested import was not available in the current
environment. The message identifies the missing import, but it does not by itself
show whether the required package is absent or whether the import name differs
from the package distribution name. The exact failing cell and dependency files
are not available, so the reason for the missing import cannot be determined
further.

### Example 3 — execution 94

**Error:** `ModuleNotFoundError: No module named 'google'`

**Explanation:** Python could not find the module `google` when the notebook was
executed. This means that the requested import was not available in the current
environment. The error message identifies the missing module, but it does not
show why that module is unavailable. The exact failing cell and dependency files
are not available, so this explanation cannot determine the required package or
the appropriate repair.

### Example 4 — execution 118

**Error:** `ModuleNotFoundError: No module named 'cana'`

**Explanation:** Python could not find the module `cana` when the notebook was
executed. This means that the requested import was not available in the current
environment. The error message identifies the missing module, but it does not
show why that module is unavailable. The exact failing cell and dependency files
are not available, so this explanation cannot determine the required package or
the appropriate repair.

### Example 5 — execution 172

**Error:** `ModuleNotFoundError: No module named 'idpgan'`

**Explanation:** Python could not find the module `idpgan` when the notebook was
executed. This means that the requested import was not available in the current
environment. The error message identifies the missing module, but it does not
show why that module is unavailable. The exact failing cell and dependency files
are not available, so this explanation cannot determine the required package or
the appropriate repair.

### Example 6 — execution 211

**Error:** `ModuleNotFoundError: No module named 'gnomad'`

**Explanation:** Python could not find the module `gnomad` when the notebook was
executed. This means that the requested import was not available in the current
environment. The error message identifies the missing module, but it does not
show why that module is unavailable. The exact failing cell and dependency files
are not available, so this explanation cannot determine the required package or
the appropriate repair.

### Example 7 — execution 252

**Error:** `ModuleNotFoundError: No module named 'StringIO'`

**Explanation:** Python could not find the module `StringIO` when the notebook
was executed. This means that the requested import was not available in the
current environment. The message identifies the missing import, but it does not
show whether the cause is a missing dependency, an import-name difference, or
code written for a different Python environment. The exact failing cell and
dependency files are not available, so the cause cannot be determined further.

### Example 8 — execution 282

**Error:** `ModuleNotFoundError: No module named 'pygenn'`

**Explanation:** Python could not find the module `pygenn` when the notebook was
executed. This means that the requested import was not available in the current
environment. The error message identifies the missing module, but it does not
show why that module is unavailable. The exact failing cell and dependency files
are not available, so this explanation cannot determine the required package or
the appropriate repair.

### Example 9 — execution 398

**Error:** `ModuleNotFoundError: No module named 'celloracle'`

**Explanation:** Python could not find the module `celloracle` when the notebook
was executed. This means that the requested import was not available in the
current environment. The error message identifies the missing module, but it
does not show why that module is unavailable. The exact failing cell and
dependency files are not available, so this explanation cannot determine the
required package or the appropriate repair.

### Example 10 — execution 163

**Error:** `ImportError: cannot import name 'isshape' from 'scipy.sparse.sputils'`

**Explanation:** Python found the SciPy package, but it could not find the name
`isshape` in `scipy.sparse.sputils`. This is an import error rather than a missing
package error: the notebook expects a name that the installed SciPy version does
not provide. The error is therefore consistent with an API or version
incompatibility. The installed SciPy version and full notebook context are not
available, so this explanation cannot identify the exact compatible version.

### Example 11 — execution 175

**Error:** `ImportError: cannot import name 'cumtrapz' from 'scipy.integrate'`

**Explanation:** Python found the SciPy package, but it could not find the name
`cumtrapz` in `scipy.integrate`. This is an import error rather than a missing
package error: the notebook expects a name that the installed SciPy version does
not provide. The error is therefore consistent with an API or version
incompatibility. The installed SciPy version and full notebook context are not
available, so this explanation cannot identify the exact compatible version.

### Example 12 — execution 197

**Error:** `ImportError: cannot import name 'VisibleDeprecationWarning' from 'numpy'`

**Explanation:** Python found the NumPy package, but it could not find the name
`VisibleDeprecationWarning` in `numpy`. This is an import error rather than a
missing package error: the notebook expects a name that the installed NumPy
version does not provide. The error is therefore consistent with an API or
version incompatibility. The installed NumPy version and full notebook context
are not available, so this explanation cannot identify the exact compatible
version.

## Researcher-only implementation checklist

1. Create four survey variants from the assignment CSV. The error text always
   comes from `human_evaluation_examples.csv`.
2. If `explanation_method` is `llm`, use the original `summary`, `root_cause`,
   `evidence`, and `limitations` fields exactly as in the administered study.
3. If `explanation_method` is `template`, use the matching baseline text above.
   Present it under the same neutral heading, **The explanation**.
4. Randomise the display order of the six cases within each variant if the survey
   system supports it. Preserve the method assignment.
5. Record every new response in
   `data/human-evaluation/comparison/human_evaluation_comparison_response_template.csv`.
   Do not combine these ratings with the original LLM-only study.
6. Report the result as a small, descriptive, between-participant comparison.
   State the number of new participants and ratings per method. Do not claim
   statistically significant or general superiority from a small sample.
