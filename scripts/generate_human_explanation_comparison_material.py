"""Generate blinded participant-facing survey variants for the explanation comparison.

The source LLM fields are the frozen, previously administered explanation texts.
The baseline texts are deterministic, fixed templates defined below.  The generated
files deliberately contain no indication of which source produced an explanation.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "data/human-evaluation/human_evaluation_examples.csv"
ASSIGNMENTS = ROOT / "data/human-evaluation/comparison/human_evaluation_comparison_assignments.csv"
OUTPUT_DIR = ROOT / "docs/human-explanation-comparison-variants"

BASELINES = {
    1: "Python could not find the module `sklearn` when the notebook was executed. This means that the requested import was not available in the current environment. The message identifies the missing import, but it does not by itself show whether the required package is absent or whether the import name differs from the package distribution name. The exact failing cell and dependency files are not available, so the reason for the missing import cannot be determined further.",
    2: "Python could not find the module `cv2` when the notebook was executed. This means that the requested import was not available in the current environment. The message identifies the missing import, but it does not by itself show whether the required package is absent or whether the import name differs from the package distribution name. The exact failing cell and dependency files are not available, so the reason for the missing import cannot be determined further.",
    3: "Python could not find the module `google` when the notebook was executed. This means that the requested import was not available in the current environment. The error message identifies the missing module, but it does not show why that module is unavailable. The exact failing cell and dependency files are not available, so this explanation cannot determine the required package or the appropriate repair.",
    4: "Python could not find the module `cana` when the notebook was executed. This means that the requested import was not available in the current environment. The error message identifies the missing module, but it does not show why that module is unavailable. The exact failing cell and dependency files are not available, so this explanation cannot determine the required package or the appropriate repair.",
    5: "Python could not find the module `idpgan` when the notebook was executed. This means that the requested import was not available in the current environment. The error message identifies the missing module, but it does not show why that module is unavailable. The exact failing cell and dependency files are not available, so this explanation cannot determine the required package or the appropriate repair.",
    6: "Python could not find the module `gnomad` when the notebook was executed. This means that the requested import was not available in the current environment. The error message identifies the missing module, but it does not show why that module is unavailable. The exact failing cell and dependency files are not available, so this explanation cannot determine the required package or the appropriate repair.",
    7: "Python could not find the module `StringIO` when the notebook was executed. This means that the requested import was not available in the current environment. The message identifies the missing import, but it does not show whether the cause is a missing dependency, an import-name difference, or code written for a different Python environment. The exact failing cell and dependency files are not available, so the cause cannot be determined further.",
    8: "Python could not find the module `pygenn` when the notebook was executed. This means that the requested import was not available in the current environment. The error message identifies the missing module, but it does not show why that module is unavailable. The exact failing cell and dependency files are not available, so this explanation cannot determine the required package or the appropriate repair.",
    9: "Python could not find the module `celloracle` when the notebook was executed. This means that the requested import was not available in the current environment. The error message identifies the missing module, but it does not show why that module is unavailable. The exact failing cell and dependency files are not available, so this explanation cannot determine the required package or the appropriate repair.",
    10: "Python found the SciPy package, but it could not find the name `isshape` in `scipy.sparse.sputils`. This is an import error rather than a missing-package error: the notebook expects a name that the installed SciPy version does not provide. The error is therefore consistent with an API or version incompatibility. The installed SciPy version and full notebook context are not available, so this explanation cannot identify the exact compatible version.",
    11: "Python found the SciPy package, but it could not find the name `cumtrapz` in `scipy.integrate`. This is an import error rather than a missing-package error: the notebook expects a name that the installed SciPy version does not provide. The error is therefore consistent with an API or version incompatibility. The installed SciPy version and full notebook context are not available, so this explanation cannot identify the exact compatible version.",
    12: "Python found the NumPy package, but it could not find the name `VisibleDeprecationWarning` in `numpy`. This is an import error rather than a missing-package error: the notebook expects a name that the installed NumPy version does not provide. The error is therefore consistent with an API or version incompatibility. The installed NumPy version and full notebook context are not available, so this explanation cannot identify the exact compatible version.",
}

INTRODUCTION = """# Study: How people judge explanations of programming errors

Thank you for taking part in this short study, run as part of a Master's thesis
in software engineering.

When a Jupyter Notebook fails because of a Python dependency problem, an
automated system can generate a short, plain-language explanation of what went
wrong. In this study, you will read real examples of such errors together with
an automatically generated explanation. Please rate each explanation based only
on the information shown. There are no right or wrong answers.

## Consent

- I am taking part voluntarily and can stop at any time without giving a reason.
- No personally identifying information is requested in this questionnaire.
- Responses will be reported only in aggregate in the Master's thesis.
- I have read this information and agree to take part.

☐ I agree to take part.

## About you (all optional)

1. General programming experience: ☐ None ☐ Beginner ☐ Intermediate
   ☐ Advanced/Professional
2. Python familiarity: ☐ Never used it ☐ Used it a little ☐ Use it regularly
3. Jupyter Notebook familiarity: ☐ Never used them ☐ Used them a few times
   ☐ Use them regularly
4. Experience with missing-package or package-version errors: ☐ Never
   ☐ Occasionally ☐ Frequently

## Instructions

You will see six examples. Each example contains an error produced by a notebook
and an explanation of that error. Base your answers only on the explanation
shown, not on whether you personally know how to fix the error and not on whether
you think the notebook was eventually repaired.

Please rate every statement on this scale:

**1 = Strongly disagree, 2 = Disagree, 3 = Neither agree nor disagree,
4 = Agree, 5 = Strongly agree**

"""

RATING_TABLE = """| Statement | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Q1. From this explanation, I understand why the notebook failed. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q2. This explanation is satisfying. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q3. This explanation has enough detail. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q4. This explanation seems complete. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q5. This explanation is useful for understanding what went wrong. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q6. This explanation seems correct, based on the error shown. | ☐ | ☐ | ☐ | ☐ | ☐ |
"""


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def llm_text(example: dict[str, str]) -> str:
    evidence = example["evidence"].split(" | ")
    bullets = "\n".join(f"- {item}" for item in evidence)
    return (
        f"**What happened:** {example['summary']}\n\n"
        f"**Why it happened:** {example['root_cause']}\n\n"
        f"**Evidence:**\n{bullets}\n\n"
        f"**Limitations:** {example['limitations']}"
    )


def main() -> None:
    examples = {row["example_id"]: row for row in load_csv(EXAMPLES)}
    assignments = load_csv(ASSIGNMENTS)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for variant in ("A", "B", "C", "D"):
        rows = sorted(
            (row for row in assignments if row["survey_variant"] == variant),
            key=lambda row: int(row["example_order_slot"]),
        )
        content = [INTRODUCTION, f"## Questionnaire variant {variant}\n"]
        for position, assignment in enumerate(rows, start=1):
            example = examples[assignment["example_id"]]
            if assignment["explanation_method"] == "llm":
                explanation = llm_text(example)
            else:
                explanation = BASELINES[int(assignment["example_id"])]
            content.extend(
                [
                    f"## Example {position} of 6\n",
                    "**The error:**\n",
                    f"> `{example['error_type']}`: `{example['error_message']}`\n",
                    "**The explanation:**\n",
                    f"> {explanation.replace(chr(10), chr(10) + '> ')}\n",
                    "Please rate the explanation above:\n",
                    RATING_TABLE,
                ]
            )
        content.extend(
            [
                "## Optional final feedback\n",
                "1. Was anything about the explanations you just read unclear or missing?\n",
                "2. What would make explanations like these more helpful to you?\n",
            ]
        )
        (OUTPUT_DIR / f"variant_{variant}.md").write_text(
            "\n".join(content), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
