# Study: How people judge explanations of programming errors

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


## Questionnaire variant D

## Example 1 of 6

**The error:**

> `ModuleNotFoundError`: `No module named 'idpgan'`

**The explanation:**

> Python could not find the module `idpgan` when the notebook was executed. This means that the requested import was not available in the current environment. The error message identifies the missing module, but it does not show why that module is unavailable. The exact failing cell and dependency files are not available, so this explanation cannot determine the required package or the appropriate repair.

Please rate the explanation above:

| Statement | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Q1. From this explanation, I understand why the notebook failed. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q2. This explanation is satisfying. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q3. This explanation has enough detail. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q4. This explanation seems complete. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q5. This explanation is useful for understanding what went wrong. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q6. This explanation seems correct, based on the error shown. | ☐ | ☐ | ☐ | ☐ | ☐ |

## Example 2 of 6

**The error:**

> `ModuleNotFoundError`: `No module named 'StringIO'`

**The explanation:**

> **What happened:** The notebook failed because Python could not find the module 'StringIO'.
> 
> **Why it happened:** The notebook imports 'StringIO', which is not available in the execution environment.
> 
> **Evidence:**
> - The error type is ModuleNotFoundError.
> - The error message says: No module named 'StringIO'.
> - The root_cause_hint is direct_missing_package.
> 
> **Limitations:** Only metadata is available, so the exact failing cell and dependency files cannot be inspected.

Please rate the explanation above:

| Statement | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Q1. From this explanation, I understand why the notebook failed. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q2. This explanation is satisfying. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q3. This explanation has enough detail. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q4. This explanation seems complete. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q5. This explanation is useful for understanding what went wrong. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q6. This explanation seems correct, based on the error shown. | ☐ | ☐ | ☐ | ☐ | ☐ |

## Example 3 of 6

**The error:**

> `ModuleNotFoundError`: `No module named 'pygenn'`

**The explanation:**

> Python could not find the module `pygenn` when the notebook was executed. This means that the requested import was not available in the current environment. The error message identifies the missing module, but it does not show why that module is unavailable. The exact failing cell and dependency files are not available, so this explanation cannot determine the required package or the appropriate repair.

Please rate the explanation above:

| Statement | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Q1. From this explanation, I understand why the notebook failed. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q2. This explanation is satisfying. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q3. This explanation has enough detail. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q4. This explanation seems complete. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q5. This explanation is useful for understanding what went wrong. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q6. This explanation seems correct, based on the error shown. | ☐ | ☐ | ☐ | ☐ | ☐ |

## Example 4 of 6

**The error:**

> `ModuleNotFoundError`: `No module named 'celloracle'`

**The explanation:**

> **What happened:** The notebook execution failed because Python could not find the module 'celloracle'.
> 
> **Why it happened:** The notebook imports 'celloracle', which is not available in the execution environment.
> 
> **Evidence:**
> - The error type is ModuleNotFoundError.
> - The error message says: No module named 'celloracle'.
> - The root_cause_hint is direct_missing_package.
> 
> **Limitations:** Only metadata is available, so the exact failing cell and dependency files cannot be inspected.

Please rate the explanation above:

| Statement | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Q1. From this explanation, I understand why the notebook failed. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q2. This explanation is satisfying. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q3. This explanation has enough detail. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q4. This explanation seems complete. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q5. This explanation is useful for understanding what went wrong. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q6. This explanation seems correct, based on the error shown. | ☐ | ☐ | ☐ | ☐ | ☐ |

## Example 5 of 6

**The error:**

> `ImportError`: `cannot import name 'cumtrapz' from 'scipy.integrate' (/tmp/.local/lib/python3.10/site-packages/scipy/integrate/__init__.py)`

**The explanation:**

> Python found the SciPy package, but it could not find the name `cumtrapz` in `scipy.integrate`. This is an import error rather than a missing-package error: the notebook expects a name that the installed SciPy version does not provide. The error is therefore consistent with an API or version incompatibility. The installed SciPy version and full notebook context are not available, so this explanation cannot identify the exact compatible version.

Please rate the explanation above:

| Statement | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Q1. From this explanation, I understand why the notebook failed. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q2. This explanation is satisfying. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q3. This explanation has enough detail. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q4. This explanation seems complete. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q5. This explanation is useful for understanding what went wrong. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q6. This explanation seems correct, based on the error shown. | ☐ | ☐ | ☐ | ☐ | ☐ |

## Example 6 of 6

**The error:**

> `ImportError`: `cannot import name 'VisibleDeprecationWarning' from 'numpy' (/tmp/.local/lib/python3.10/site-packages/numpy/__init__.py)`

**The explanation:**

> **What happened:** The notebook failed because it tried to import 'VisibleDeprecationWarning' from 'numpy', but that name was not available.
> 
> **Why it happened:** This is likely caused by a package API or version incompatibility, where the notebook expects a warning class that is not present in the installed NumPy package version.
> 
> **Evidence:**
> - The error type is ImportError.
> - The error message says that 'VisibleDeprecationWarning' could not be imported from 'numpy'.
> - The root_cause_hint is version_or_api_incompatibility.
> 
> **Limitations:** Only metadata is available, so the exact failing cell and dependency files cannot be inspected. The installed NumPy version is not available, so the exact compatibility mismatch cannot be verified.

Please rate the explanation above:

| Statement | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Q1. From this explanation, I understand why the notebook failed. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q2. This explanation is satisfying. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q3. This explanation has enough detail. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q4. This explanation seems complete. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q5. This explanation is useful for understanding what went wrong. | ☐ | ☐ | ☐ | ☐ | ☐ |
| Q6. This explanation seems correct, based on the error shown. | ☐ | ☐ | ☐ | ☐ | ☐ |

## Optional final feedback

1. Was anything about the explanations you just read unclear or missing?

2. What would make explanations like these more helpful to you?
