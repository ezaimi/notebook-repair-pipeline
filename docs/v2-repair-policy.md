# V2 Repair Policy

## Status

This document freezes the intended design of the revised dependency-repair
pipeline before implementation. It is a policy specification, not an
evaluation result. The implementation, tests, and evaluation configuration
must follow this document unless a later dated revision explains the change.

## Purpose and evaluation status

The initial evaluation identified that a hand-curated import-to-distribution
mapping was too restrictive: imports absent from the mapping were abstained
before PyPI was queried. V2 replaces that rule with a general, verified
resolution procedure. The revised evaluation will use the same 187 records,
so it must be described as a post-feedback revised evaluation, not as an
independent evaluation on an unseen split.

No mapping entry, version rule, or special case may be added because it
improves an individual record in the 187-record evaluation split.

## Component responsibilities

| Component | Responsibility | Must not do |
|---|---|---|
| Error classifier | Classify repair scope and failure kind. | Guess a PyPI package. |
| Resolver/retriever | Resolve and verify an import-to-distribution candidate; retrieve version evidence. | Execute a command. |
| LLMExplainer | Explain the observed failure in plain language. | Apply or approve a repair. |
| Repair decision policy | Select a deterministic repair where evidence is sufficient, or request an LLM proposal only where there is genuine uncertainty. | Trust an unverified name or version. |
| Proposal validator | Enforce the schema and evidence constraints. | Replace a rejected proposal with an undocumented guess. |
| FixApplicator | Apply an already validated command in Docker and re-execute the notebook. | Make an LLM call or choose a package/version. |
| Docker re-execution | Determine the observed repair outcome. | Treat an LLM assertion as proof of success. |

The LLM never executes a command, edits a notebook, or decides whether a
repair succeeded.

## Classification before package lookup

Before any PyPI request, the pipeline must distinguish the following cases:

1. `standard_library`: the requested module belongs to the Python 3.10
   standard library. No PyPI package is proposed.
2. `local_import_path`: repository or notebook context shows that the import
   refers to project code, a local module, or an import-path/working-directory
   problem. No PyPI package is proposed.
3. `third_party_dependency`: neither of the previous cases applies. Only this
   status enters package resolution.
4. `classification_uncertain`: evidence is insufficient to classify the
   import safely. The pipeline abstains rather than treating it as a PyPI
   dependency.

The implementation must use conservative evidence for local imports. A name
that merely looks local is not enough to classify it as local.

## Import-to-distribution resolution

For a `third_party_dependency`, the resolver considers candidates in this
order:

1. An explicit special mapping in `config/package_mapping.v2.yaml`, used only
   where the import and distribution names materially differ (for example,
   `sklearn` to `scikit-learn`).
2. Identity mapping: use the import's top-level name as the distribution
   candidate (for example, `numpy` to `numpy`).
3. PEP 503 normalisation of that candidate, so case and the separator
   characters `.`, `_`, and `-` are treated consistently (for example,
   `dms_variants` to `dms-variants`).
4. A frozen public mapping snapshot (`pipreqs`, source commit and
   Apache-2.0 licence retained under `data/public-import-mapping/`). Its
   distribution is only another candidate and must pass the same wheel
   check; it is not assumed correct merely because a public table says so.
5. If all deterministic candidates fail, the repair LLM may suggest one
   distribution candidate. It remains only a candidate and must pass exactly
   the same verification as every deterministic candidate.

An import is not resolved merely because a project of the same name exists on
PyPI. Before a candidate may reach repair generation, the resolver must
establish both that an eligible distribution exists and that its wheel metadata
or an equivalent verified index indicates that it provides the requested
top-level import. A candidate lacking that evidence receives
`import_not_provided` and no command is generated.

If no candidate passes verification, the result is `mapping_unknown`.

## Version evidence

For a missing-package repair, a verified distribution is installed without a
version pin unless the defined repair policy requires a pin.

For a wrong-version repair, candidates must be derived from releases that are:

- compatible with the pipeline's Python 3.10 runtime;
- not pre-releases or fully yanked releases; and
- uploaded on or before the recorded repository commit date or another
  documented repository publication date.

The old, dataset-specific compatibility registry is not used as the source of
a V2 wrong-version decision. If no trustworthy date is available, the result
is `date_evidence_unavailable` and the pipeline abstains rather than silently
substituting a latest-release rule.

## Repository dependency files

Repository dependency files remain necessary to reconstruct the baseline
Docker environment. The pipeline installs the supported repository dependency
files before it applies a proposed repair.

For V2, the relevant declaration for the resolved distribution is also
extracted before repair selection. It is labelled as one of:

- `declared_constraint_absent`;
- `declared_constraint_compatible`;
- `declared_constraint_conflict`; or
- `declared_constraint_unparsable`.

This declaration is non-authoritative context: it cannot create a package
mapping, prove that a version is correct, or override verified PyPI evidence.
It is included as labelled context in an LLM repair prompt where a repair
proposal is requested.

A conflict does not silently disappear. It is stored with the proposal,
FixApplicator result, and evaluation metrics. A conflicting proposal may still
be tested in the isolated Docker environment because the declared version can
itself be the source of the observed dependency failure. Docker re-execution,
not the declaration, determines the outcome.

## Repair-decision policy and LLM use

The default policy is deliberately deterministic whenever evidence supplies a
single safe action:

- A verified ordinary missing package produces a deterministic `install`
  action.
- A wrong-version failure with multiple verified date-anchored candidates may
  request an LLM proposal selecting from that exact candidate set.
- An import unresolved after deterministic resolution may request an LLM
  distribution suggestion, but the proposal cannot proceed unless resolver
  verification accepts it.
- Where evidence is insufficient, the only permitted outcome is abstention.

The LLM returns structured data only. `install_name` must equal a verified
resolved distribution, and any version must occur in the verified candidate
set. The validator rejects invented names, versions, commands, and actions.
FixApplicator constructs the final `python -m pip install ...` argument list
deterministically from validated fields.

## Execution and reproducibility

Each repair is tested in a clean Docker reconstruction. Before V2, the input
records are enriched from the upstream metadata database: requirements files
are fetched only at the recorded repository commit, and the recorded commit
date is retained for version filtering. The V2 FixApplicator requires a
recorded commit; it skips a record with an explicit
`recorded_repository_commit_unavailable` status rather than running the
repository's current default branch.

Every evaluation manifest must record the code and configuration hashes,
repository-metadata database hash, model and serving settings, hardware, OS,
Docker version, Ollama version, and PyPI evidence source/date or frozen-cache
hash.

The main evaluation retains a two-round cap. A three-to-five-round experiment,
if performed, is a separately labelled round-budget sensitivity experiment and
does not silently alter the main protocol.

## Required statuses and artefacts

At minimum, the revised trace must distinguish:

- `standard_library`;
- `local_import_path`;
- `classification_uncertain`;
- `mapping_unknown`;
- `import_not_provided`;
- `date_evidence_unavailable`;
- each declared-constraint status; and
- the existing proposal, Docker, targeted-error, and full-notebook outcomes.

The trace must preserve the retrieval evidence, wheel/index verification
evidence, dependency-file context, LLM request/response where applicable,
validated command, and Docker result for every decision.

## Implementation acceptance criteria

V2 is ready for the 13-record development run only when automated tests show
that it:

1. never queries PyPI for confirmed standard-library or local imports;
2. resolves verified identity and PEP 503-normalised candidates;
3. retains special mappings for genuine name mismatches;
4. rejects a PyPI distribution that does not provide the requested import;
5. never accepts an LLM-invented distribution or version;
6. records dependency-file compatibility/conflict state; and
7. constructs and executes commands only through FixApplicator after all
   validation checks pass.
8. uses a recorded repository commit and commit date for every V2 execution
   or reports an explicit non-execution status.
