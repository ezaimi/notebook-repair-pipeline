# Few-Shot Repair Prompt Test — dms_variants

## Test case

- Development sample row: `50`
- Prompt strategy: `few_shot`
- Model: `gemma2:9b`
- Error type: `ModuleNotFoundError`
- Failing module: `dms_variants`
- Traceback: `No module named 'dms_variants'`
- Current requirements: `Not available`
- Notebook imports: `Not available`
- PyPI version data: `Not available`
- Prior attempt: `Not available`

## Prompt

```text
SYSTEM:
You generate safe, structured pip-based repair proposals for Python dependency errors in Jupyter notebooks.

Return ONLY one valid JSON object. Do not include markdown, explanations outside JSON, or additional text.

Allowed actions:
- "install": a third-party dependency is missing and can be installed with pip.
- "pin_version": a package version is likely incompatible, and the provided PyPI data supports one specific version.
- "none": no safe pip-only fix can be proposed.

Rules:
- Use only the supplied information.
- Do not invent package names, package versions, Python-version compatibility, or PyPI evidence.
- For "install", set "version" to null.
- For "install", "install_name" and "command" must be non-null. The command must be exactly `pip install <install_name>`.
- For "pin_version", "install_name", "version", and "command" must be non-null. The command must be exactly `pip install <install_name>==<version>`.
- For "pin_version", "version" must be a non-null version supported by the provided PyPI data.
- If a safe version cannot be supported by the supplied PyPI data, use "none".
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
Error type: ModuleNotFoundError
Failing module: dms_variants
Traceback: No module named 'dms_variants'

Current requirements file:
Not available

Notebook imports:
Not available

Available PyPI version data:
Not available

Prior repair attempt, if any:
Not available

Suggest the safest valid pip-only repair.

```

## Model output

```json

{
  "action": "none",
  "import_name": "dms_variants",
  "install_name": null,
  "version": null,
  "command": null,
  "rationale": "The pip package name for dms_variants cannot be safely determined.",
  "pypi_evidence": {
    "latest_version": null,
    "chosen_version": null,
    "requires_python": null
  }
}

```


## Manual check

* Valid JSON: pass
* Allowed action: pass
* Correctly abstains when the pip package name is unknown: pass
* No package name or version invented: pass
* No unsafe command proposed: pass
* Few-shot format followed: pass
* Action-dependent schema rules: pass