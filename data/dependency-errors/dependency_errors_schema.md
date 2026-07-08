# Dependency Error Dataset Schema

| Column | Meaning |
| --- | --- |
| `notebook_execution_id` | ID of the failed notebook execution from `notebook_executions`. |
| `repository_run_id` | ID of the repository run. |
| `repository_id` | Repository ID from the Docker pipeline database. |
| `notebook_id` | Notebook ID from the Docker pipeline database. |
| `notebook_name` | Notebook path/name. |
| `repository_url` | Repository URL recorded during execution. |
| `execution_status` | Execution status recorded by the Docker pipeline. |
| `error_type` | Python exception type, for example `ModuleNotFoundError` or `ImportError`. |
| `error_category` | Pipeline error category. This dataset keeps `DEPENDENCY_ERROR`. |
| `error_message` | Error message stored in the database. |
| `error_cell_index` | Index of the failing notebook cell, if available. |
| `error_count` | Number of errors recorded for the execution. |
| `failing_module` | Module, package, or shared library extracted from the error message. |
| `subtype` | Classified subtype: `missing_package`, `wrong_version`, `system_library`, or `mapping_unknown`. |
| `scope_status` | Whether the row is `usable` or `excluded` for the pip-only v1 repair scope. |
| `exclusion_reason` | Reason why the row was excluded, if applicable. |
| `split` | Dataset split: `dev`, `evaluation`, or `excluded`. |
| `created_at` | Timestamp from the source execution row. |
