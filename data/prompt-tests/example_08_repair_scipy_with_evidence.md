# Repair Prompt Test — scipy with version evidence

## Test case

* Development sample row: `174`
* Prompt strategy: `few_shot`
* Model: `gemma2:9b`
* Error type: `ImportError`
* Failing module: `scipy`
* Traceback: `cannot import name 'cumtrapz' from 'scipy.integrate'`
* Current requirements: `Not available`
* Notebook imports: `Not available`
* Python runtime version: `3.10` (controlled test input)
* Prior attempt: `Not available`

## Supplied version evidence

* Latest SciPy version: `1.18.0`
* `scipy.integrate.cumtrapz` was removed in SciPy `1.14.0`.
* SciPy `1.13.1` is available.
* SciPy `1.13.1` requires Python `>=3.9`.
* Therefore, SciPy `1.13.1` is compatible with Python `3.10` and retains `cumtrapz`.

## Prompt

```text
SYSTEM:
You generate safe, structured pip-based repair proposals for Python dependency errors in Jupyter notebooks.

Return ONLY one valid JSON object. Do not include markdown, explanations outside JSON, or additional text.

Allowed actions:
- "install": a third-party dependency is missing and can be installed with pip.
- "pin_version": a package version is likely incompatible, and the provided evidence supports one specific version.
- "none": no safe pip-only fix can be proposed.

Rules:
- Use only the supplied information.
- Do not invent package names, package versions, Python-version compatibility, or PyPI evidence.
- For "install", set "version" to null.
- For "install", "install_name" and "command" must be non-null. The command must be exactly `pip install <install_name>`.
- For "pin_version", "install_name", "version", and "command" must be non-null. The command must be exactly `pip install <install_name>==<version>`.
- For "pin_version", choose a version only when the provided evidence shows that it contains the missing import and supports the provided Python runtime version.
- If a safe version cannot be supported by the supplied evidence, use "none".
- For "none", set "install_name", "version", and "command" to null.
- Do not propose apt, conda, pip uninstall, source-code edits, import replacements, or path changes.
- The import name and pip install name may differ. Return both names.
- Known examples include: sklearn → scikit-learn; umap → umap-learn; pkg_resources → setuptools.
- Do not assume that an import name is also a pip package name. For an unknown import name, use "none" unless a verified import-to-package mapping is provided in the input or listed in the known examples.
- When using "none" because the pip package name is unknown, state in the rationale that the pip package name cannot be safely determined from the available information.

EXAMPLE 1 INPUT:
Error type: ModuleNotFoundError
Failing module: sklearn
Traceback: No module named 'sklearn'

Current requirements file: Not available
Notebook imports: Not available
Available PyPI version data: Not available
Prior repair attempt, if any: Not available

EXAMPLE 1 OUTPUT:
{
  "action": "install",
  "import_name": "sklearn",
  "install_name": "scikit-learn",
  "version": null,
  "command": "pip install scikit-learn",
  "rationale": "The sklearn import is provided by the scikit-learn package.",
  "pypi_evidence": {
    "latest_version": null,
    "chosen_version": null,
    "requires_python": null
  }
}

EXAMPLE 2 INPUT:
Error type: ImportError
Failing module: scipy
Traceback: cannot import name 'cumtrapz' from 'scipy.integrate'

Current requirements file: Not available
Notebook imports: Not available
Available PyPI version data: Not available
Prior repair attempt, if any: Not available

EXAMPLE 2 OUTPUT:
{
  "action": "none",
  "import_name": "scipy",
  "install_name": null,
  "version": null,
  "command": null,
  "rationale": "A compatible SciPy version cannot be safely selected without version evidence.",
  "pypi_evidence": {
    "latest_version": null,
    "chosen_version": null,
    "requires_python": null
  }
}

Return exactly this JSON structure:
{
  "action": "install | pin_version | none",
  "import_name": "string",
  "install_name": "string or null",
  "version": "string or null",
  "command": "string or null",
  "rationale": "one short sentence",
  "pypi_evidence": {
    "latest_version": "string or null",
    "chosen_version": "string or null",
    "requires_python": "string or null"
  }
}

USER:
Dependency error context:
Error type: ImportError
Failing module: scipy
Traceback: cannot import name 'cumtrapz' from 'scipy.integrate'

Current requirements file:
Not available

Notebook imports:
Not available

Python runtime version:
3.10

Available PyPI and compatibility evidence:
- Latest SciPy version: 1.18.0
- scipy.integrate.cumtrapz was removed in SciPy 1.14.0.
- SciPy 1.13.1 is available.
- SciPy 1.13.1 requires Python >=3.9.
- Therefore, SciPy 1.13.1 is compatible with Python 3.10 and retains cumtrapz.

Prior repair attempt, if any:
Not available

Suggest the safest valid pip-only repair.
```

## Model output

```json
{
  "action": "pin_version",
  "import_name": "scipy",
  "install_name": "scipy",
  "version": "1.13.1",
  "command": "pip install scipy==1.13.1",
  "rationale": "SciPy 1.13.1 is compatible with Python 3.10 and retains cumtrapz.",
  "pypi_evidence": {
    "latest_version": "1.18.0",
    "chosen_version": "1.13.1",
    "requires_python": ">=3.9"
  }
}
```

## Manual check

* Valid JSON: pass
* Allowed action: pass
* Correctly selects `pin_version`: pass
* Chosen version is supported by supplied evidence: pass
* Python-version compatibility is supported by supplied evidence: pass
* Required pin command present: pass
* PyPI evidence fields are complete: pass
* No unsupported package name, version, or command invented: pass
* Few-shot format followed: pass
* Action-dependent schema rules: pass
