# Few-Shot Explanation Prompt Test — pkg_resources

## Test case

* Development sample row: `43`
* Prompt strategy: `few_shot`
* Model: `gemma2:9b`
* Error type: `ModuleNotFoundError`
* Failing module: `pkg_resources`
* Traceback: `No module named 'pkg_resources'`
* Cell source: `Not available`

## Prompt

```text
SYSTEM:
You explain Python notebook dependency errors to researchers who may not be programmers.

Write in plain, everyday language. Avoid technical jargon. If a technical term is necessary, explain it briefly.

Use only the information provided. Do not invent package versions, installation commands, file contents, or causes that are not supported by the error.

Write 2–4 short sentences. Do not use headings, bullet points, or JSON.
Do NOT suggest a fix or a command. Only explain what went wrong and why the notebook stopped.

Rules:
- For ModuleNotFoundError, describe the problem as a missing or unavailable dependency.
- Do not describe a ModuleNotFoundError as a version or compatibility problem unless the error explicitly says so.
- For an ImportError stating that a name cannot be imported from an installed package, explicitly say that the notebook likely expects a different version of that package.
- Do not claim that something was installed incorrectly unless that information is provided.
- Do not use placeholders in the response.
- Do not use metaphors or analogies.

EXAMPLE 1 INPUT:
Error type:
ModuleNotFoundError

Module or import involved:
sklearn

Error message or traceback:
No module named 'sklearn'

Failing code cell:
Not available

EXAMPLE 1 OUTPUT:
Your Jupyter notebook encountered an error because it couldn't find a tool called `sklearn`. `sklearn` is a library that helps with machine learning tasks. Because Python couldn't locate `sklearn`, the notebook stopped running.

EXAMPLE 2 INPUT:
Error type:
ImportError

Module or import involved:
scipy

Error message or traceback:
cannot import name 'cumtrapz' from 'scipy.integrate'

Failing code cell:
Not available

EXAMPLE 2 OUTPUT:
Your Jupyter notebook encountered an error because it couldn't find a function called `cumtrapz` within the `scipy` package. `scipy` is a library that provides scientific tools for Python. The notebook likely expects a different version of the `scipy` package than the one currently installed.

USER:
A Jupyter notebook failed because of a dependency-related error.

Error type:
ModuleNotFoundError

Module or import involved:
pkg_resources

Error message or traceback:
No module named 'pkg_resources'

Failing code cell:
Not available

Return only the explanation text.
```

## Model output

```text
Your Jupyter notebook encountered an error because it couldn't find a tool called `pkg_resources`. `pkg_resources` is a library that helps manage Python packages. Because Python couldn't locate `pkg_resources`, the notebook stopped running.
```

## Manual check

* Plain-language explanation: pass
* Correctly identifies missing dependency: pass
* No repair command suggested: pass
* No unsupported version or compatibility claim: pass
* Few-shot format followed: pass
