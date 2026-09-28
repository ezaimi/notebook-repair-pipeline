# Human Evaluation of Dependency-Error Explanations — Questionnaire

Status: **administered.** This questionnaire was transferred into LimeSurvey as four survey variants and given to participants 2026-09-15 through 2026-09-17; 15 complete participants' responses were collected and analyzed. The design below (participant-facing content and appendix) is exactly what was administered, unmodified after the fact. Raw exports live under `data/human-evaluation/raw/` (unmodified); the reshaping and analysis pipeline is `scripts/analyze_human_evaluation.py`; results are reported in the thesis, `sec:v-human-eval-results`.

The first part of this document (up to "End of participant-facing content") is exactly what a participant sees. The appendix after that is for the researcher only and must not be shown to participants.

---

## Participant-facing content

### 1. Study introduction

**Study: How people judge automatically generated explanations of programming errors**

Thank you for taking part in this short study, run as part of a Master's thesis in software engineering.

When a Jupyter Notebook fails to run because of a missing or incompatible Python package, an automated system can generate a short, plain-language explanation of what went wrong. In this study, you will read a few real examples of such errors, along with the explanation generated for each one, and give your honest impression of each explanation.

There are no right or wrong answers — we are interested in your personal impression. The study takes about 20–25 minutes.

### 2. Consent

Please read and confirm before continuing:

- I am taking part in this study voluntarily and can stop at any time without giving a reason.
- No personally identifying information is requested as part of this questionnaire.
- Responses will be reported only in aggregate in the Master's thesis.
- I have read the information above and agree to take part.

☐ I agree to take part in this study.

### 3. About you

*(All optional; used only to help interpret the results.)*

1. How would you describe your general programming experience?
   ☐ None ☐ Beginner ☐ Intermediate ☐ Advanced/Professional

2. How familiar are you with Python specifically?
   ☐ Never used it ☐ Used it a little ☐ Use it regularly

3. How familiar are you with Jupyter Notebooks?
   ☐ Never used them ☐ Used them a few times ☐ Use them regularly

4. How often have you personally run into a "missing package" or "package version" error while programming?
   ☐ Never ☐ Occasionally ☐ Frequently

### 4. Instructions

On the following pages, you will see **6 examples**. Each shows the error a notebook produced when it failed to run, and a short, automatically generated explanation of that error.

After each example, please rate the explanation using the questions provided. Please base your answers only on the explanation shown — not on whether you personally know how to fix the error, and not on any assumption about whether the problem was ever actually fixed. Just tell us how the explanation itself struck you.

Each question uses this scale:

**1 = Strongly disagree, 2 = Disagree, 3 = Neither agree nor disagree, 4 = Agree, 5 = Strongly agree**

### 5. Example [N] of 6

**The error:**

> `[error_type]`: `[error_message]`

**The generated explanation:**

> **What happened:** [summary]
>
> **Why it happened:** [root_cause]
>
> **Evidence:**
> - [evidence item 1]
> - [evidence item 2]
> - [evidence item 3]
>
> **Limitations:** [limitations]

Please rate the explanation above:

| | 1 Strongly disagree | 2 Disagree | 3 Neither agree nor disagree | 4 Agree | 5 Strongly agree |
|---|---|---|---|---|---|
| Q1. From this explanation, I understand why the notebook failed. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q2. This explanation is satisfying. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q3. This explanation has enough detail. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q4. This explanation seems complete. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q5. This explanation is useful for understanding what went wrong. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q6. This explanation seems correct, based on the error shown. | ☐ | ☐ | ☐ | ☐ | ☐ |

*(This block repeats identically for all 6 examples assigned to this participant. The exact content for each example — error type, error message, summary, root_cause, evidence, limitations — is taken verbatim from `data/human-evaluation/human_evaluation_examples.csv`, never edited or improved. A fully worked example, using real content from that file, is shown below.)*

#### Worked example (example_id 1, for illustration)

**The error:**

> `ModuleNotFoundError`: `No module named 'sklearn'`

**The generated explanation:**

> **What happened:** The notebook failed because Python could not find the module 'sklearn'.
>
> **Why it happened:** The notebook imports 'sklearn', which is not available in the execution environment. The classifier also marks this as an import/distribution-name mismatch, meaning the import name may not directly match the package distribution name.
>
> **Evidence:**
> - The error type is ModuleNotFoundError.
> - The error message says: No module named 'sklearn'.
> - The root_cause_hint is import_distribution_name_mismatch.
>
> **Limitations:** Only metadata is available, so the exact failing cell and dependency files cannot be inspected.

### 6. Final feedback (optional)

1. Was anything about the explanations you just read unclear or missing?
   *(free text, optional)*

2. What would make explanations like these more helpful to you?
   *(free text, optional)*

*(These two questions are supplementary, open-ended feedback. They are not part of the validated rating scale used in Section 5 and are analyzed separately, as qualitative comments.)*

### 7. Thank you

Thank you for your time and participation.

---

## End of participant-facing content

Everything below this line is for the researcher only and must not be shown to participants.

---

## Appendix (internal use only)

### A. Literature basis

The six Likert items in Section 5 are adapted from the **Explanation Satisfaction Scale** in Hoffman, R. R., Mueller, S. T., Klein, G., & Litman, J. (2023). *Measures for explainable AI: Explanation goodness, user satisfaction, mental models, curiosity, trust, and human-AI performance.* Frontiers in Computer Science, 5, Article 1096257. https://doi.org/10.3389/fcomp.2023.1096257

Six of the original scale's seven items are retained, each domain-adapted (from "how the [software, algorithm, tool] works" to "why the notebook failed"); the seventh original item ("This explanation ... tells me how to use it") is deliberately excluded, because the explanation component this thesis evaluates is intentionally not responsible for telling the user how to repair the problem — that is a separate component's job. Full item-by-item mapping is in the study-design summary (Appendix C) and in the thesis methodology section.

Q6 ("This explanation seems correct, based on the error shown.") is a substantial adaptation of the original scale's accuracy item and is reported throughout as **perceived correctness** — never as technical, objective, or factual correctness. A participant's rating reflects only how correct the explanation *appears* to the reader, not a verification against the notebook's true root cause.

The System Causability Scale (Holzinger, Carrington & Müller, 2020, KI – Künstliche Intelligenz 34(2), 193–198) was considered as an alternative and rejected: its items presuppose an interactive explanation interface with adjustable detail, comparison across multiple explanations, and domain-specific references (e.g. medical guidelines), none of which apply to this thesis's static, one-shot, plain-language explanations.

### B. Response scale note

Hoffman et al.'s own published scale numbers responses 1 = agree strongly → 5 = disagree strongly. This study uses the reverse, conventional direction (1 = strongly disagree → 5 = strongly agree) for participant clarity and consistent analysis. The five qualitative anchors and every item's wording are otherwise unchanged from the source.

### C. Sampling and study-design summary

- 12 examples total, drawn only from the frozen final evaluation split (`data/evaluation/i8-eval-final-rerun-20260913T113423Z/`), never from development-split records, and never from notebook_execution_ids 21, 24, 25, 26, 29 (already used in earlier explanation-only development activity).
- **Diversity-constrained stratified sampling**: examples are stratified by subtype, but the number drawn per subtype is constrained by how many genuinely distinct error signatures exist in the eligible population, not fixed at an equal split. The eligible `wrong_version` population (18 records) contains only 3 distinct (failing_module, error_message) signatures; all 3 are included exactly once. The remaining 9 pool slots are drawn from `missing_package`, whose eligible population (162 records, 41 distinct failing modules) supports full diversity. The result is **9 missing_package + 3 wrong_version**, not a 6/6 split.
- Selection procedure: Python `random.Random(seed=42)`, deterministic sampling over sorted candidate lists — distinct modules (missing_package) or distinct signatures (wrong_version) chosen first, then one representative notebook_execution_id per chosen module/signature. Full procedure recorded in `scripts/analyze_human_explanation_evaluation.py`'s module docstring and in the thesis methodology text.
- Selection never consulted repair outcome, Round-2 status, or any other automated-evaluation result.
- Frozen example pool (`data/human-evaluation/human_evaluation_examples.csv`): notebook_execution_ids 62, 79, 94, 118, 172, 211, 252, 282, 398 (missing_package) and 163, 175, 197 (wrong_version).
- Four balanced survey variants (`data/human-evaluation/human_evaluation_variants.csv`), each with 6 examples; every one of the 12 examples appears in exactly 2 of the 4 variants, so exposure is balanced without needing a shared "anchor" example design.
- Participants are assigned variants by simple round-robin (P01→A, P02→B, P03→C, P04→D, P05→A, ...). Presentation order of the 6 examples within a participant's variant should be randomized by the survey tool where possible.
- Target: 15–20 participants with general programming experience; Python/Jupyter familiarity desirable, not required; no ML/XAI/LLM expertise required.

### D. Analysis (run; results in the thesis)

For each of Q1–Q6: n, median, IQR, full 1–5 frequency distribution, and % rating 4–5 ("Agree"/"Strongly agree"), reported (A) overall, (B) by subtype, and (C) per example (appendix-level detail). Because the pool contains 9 distinct missing_package cases but only 3 distinct wrong_version cases, subtype-level comparisons are explicitly descriptive and must not be presented as comparing two equally-diverse samples.

Cronbach's alpha is computed across Q1–Q6 as a **supplementary internal-consistency** statistic only — it describes whether the six adapted items behaved consistently together *in this dataset*, not whether participants agree with each other, and not whether the study itself is valid. No composite "explanation quality score" is computed by default, regardless of the alpha value; item-level results remain the primary output. See `scripts/analyze_human_evaluation.py` (raw-export loading, variant mapping, completeness filtering, reshaping) and `scripts/analyze_human_explanation_evaluation.py` (item/subtype/example statistics, Cronbach's alpha) for the exact, executed implementation.

No inferential significance testing was performed. No claim beyond this specific sample of participants and examples is intended. Final results, with all figures recomputed from the raw exports, are reported in the thesis (`sec:v-human-eval-results`) and in `data/human-evaluation/analysis/`.
