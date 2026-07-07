# Repair Prompt Test — umap

## Test case

* Development sample row: `61`
* Prompt strategy: `zero_shot`
* Model: `gemma2:9b`
* Error type: `ModuleNotFoundError`
* Failing module: `umap`
* Traceback: `No module named 'umap'`
* Current requirements: `Not available`
* Notebook imports: `Not available`
* PyPI version data: `Not available`
* Prior attempt: `Not available`

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
Failing module: umap
Traceback: No module named 'umap'

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
  "action": "install",
  "import_name": "umap",
  "install_name": "umap-learn",
  "version": null,
  "command": "pip install umap-learn",
  "rationale": "The package umap is commonly installed as umap-learn.",
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
* Correct import-to-install mapping: pass
* Required install command present: pass
* No invented package version: pass
* Safe pip-only proposal: pass
* Action-dependent schema rules: pass
