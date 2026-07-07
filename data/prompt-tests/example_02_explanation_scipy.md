# Explanation Prompt Test — scipy

## Test case

* Development sample row: `174`
* Prompt strategy: `zero_shot`
* Model: `gemma2:9b`
* Error type: `ImportError`
* Failing module: `scipy`
* Traceback: `cannot import name 'cumtrapz' from 'scipy.integrate'`
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

USER:
A Jupyter notebook failed because of a dependency-related error.

Error type:
ImportError

Module or import involved:
scipy

Error message or traceback:
cannot import name 'cumtrapz' from 'scipy.integrate'

Failing code cell:
Not available

Return only the explanation text.
```

## Model output

```text
Your Jupyter notebook encountered an error because it couldn't find a function called `cumtrapz` within the `scipy` package. `scipy` is a library that provides scientific tools for Python. The notebook likely expects a different version of the `scipy` package than the one currently installed.
```

## Manual check

* Plain-language explanation: pass
* Correctly identifies likely version compatibility issue: pass
* No repair command suggested: pass
* No unsupported specific version claim: pass
