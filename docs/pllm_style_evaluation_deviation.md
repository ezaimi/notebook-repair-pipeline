# PLLM-Style Evaluation Deviation and Replacement Run

The run `pllm-style-evaluation-20260922T181950Z` completed all 187
evaluation records, but it is **discarded for comparison and thesis
reporting**. Its trace is retained for auditability and is not deleted.

## Reason

Its offline PyPI cache was prepared only from the 85 explicit distribution
references in PLLM's module-link table. Some evaluation inputs, such as
`pyrosm`, are absent from that table. The baseline correctly falls back to
the import root for these inputs, but that root was missing from the frozen
cache. With live access disabled, the resulting cache miss became an
abstention before a repair could be attempted.

This changed the baseline's effective Round-1 coverage and would make its
178 final abstentions misleading. The defect was discovered while analysing
the completed trace, before any comparison was calculated or reported.

## Correction

A replacement shared cache was prepared before the replacement evaluation:

- all 85 explicit PLLM module-link distributions; and
- every deterministic initial distribution lookup for the 187 evaluation
  records, using PLLM's own lookup rule.

The corrected cache is
`data/pllm-style-baseline/shared-comparison-pypi-cache.json`. It has 130
entries (115 resolved, 15 cached `not_found`) and is locked with
`allow_network: false` in `config/pllm_style_baseline.comparison.yaml`.

This correction changes only evidence coverage, not the baseline's prompt,
model, repair budget, parsing, or execution logic. The new baseline run and
the thesis repair-layer rerun must both use this same immutable raw PyPI
snapshot before a paired comparison is interpreted.
