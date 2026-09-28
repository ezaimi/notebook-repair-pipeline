# Full-scale knowledge-graph materialisation of the final Gemma run

Generated 2026-09-20 from the final, authoritative Gemma-2 9B evaluation run
`i10-eval-gemma-round2-explanations-20260918T161356Z`, using the already
implemented and pilot-validated export/mapping chain **unchanged**:

- `scripts/export_repair_attempts_csv.py` (sha256 `4ca15ffe…d05b00b2e`, unmodified)
- `mapping/rml_mapping/repair_attempts.rml.ttl` (sha256 `eb0d32fd…9fd1aa069dc16`, unmodified)
- Morph-KGC 2.10.0, invoked once for this one mapping file exactly as the
  upstream `run_fairjupyter_kg.sh` does (one `python -m morph_kgc <config.ini>`
  process per mapping file, N-Triples output); rdflib 7.2.1 for validation.

No evaluation run was re-executed and no result value was changed. The source
database `../raw/repair_attempts.sqlite` (sha256 `a4f0416b…b9174f`) was only
read (`mode=ro`). The upstream FAIR Jupyter KG checkout was read, never written.

## Files

| file | what it is |
|---|---|
| `repair_attempts.csv` | export of all 235 `repair_attempts` rows (`id`, `notebook_id`, + the 18 table columns), `notebook_id` resolved per row via the i2 classification dataset |
| `repair_attempts.nt` | Morph-KGC output: 3,478 triples (N-Triples, as the upstream build script emits). Line order varies between Morph-KGC processes; the triple set is identical (compare after `sort`) |
| `repair_attempts.ttl` | the same 3,478 triples re-serialised as prefixed Turtle with rdflib (isomorphic to the `.nt`), for reading |
| `repair_attempts_config.ini` | the Morph-KGC configuration used (paths relative to the scratch working directory, see below) |
| `morph_kgc.log` | Morph-KGC's own log of the run (per-rule triple counts) |
| `validate_kg_materialisation.py` | the 24 explicit pass/fail checks run over the output, against the SQLite table as ground truth |
| `kg_validation_report.json` | the result of those checks, with input hashes and tool versions: 24/24 passed |

## Counts

| quantity | value |
|---|---|
| `repair_attempts` rows in SQLite | 235 (187 Round 1 + 48 Round 2) |
| CSV rows exported | 235 |
| triples generated | 3,478 |
| `repr:RepairAttempt` resources (each also `prov:Activity`) | 235 |
| `repr:hadRepairAttempt` notebook → repair links | 235, to 187 distinct notebooks |
| Round-1 / Round-2 resources (`repr:round` "1" / "2") | 187 / 48 |
| `repr:fixOutcome` (executed fix applications) | 73 |
| `repr:exception` / `repr:msg` (post-repair error present) | 70 / 70 |
| `repr:explanation` | 208 (27 Round-1 rows have no explanation: explainer timeouts / service error) |
| `prov:endedAtTime` (`xsd:dateTime`) | 235 |
| upstream `notebooks.rml.ttl` (unmodified) over the real `notebooks.csv`/`repositories.csv` | 627,127 triples, 27,271 `repr:Notebook`; all 187 linked notebook IRIs present |

The per-predicate triple counts equal the SQLite non-NULL counts of the
corresponding columns exactly; every literal equals its SQLite value
byte-for-byte (JSON columns also compared after parsing).

## How it was run

Working directory laid out as the mapping expects (`data/repair_attempts.csv`,
`mapping/rml_mapping/repair_attempts.rml.ttl`), then:

```
python scripts/export_repair_attempts_csv.py \
  --db-path data/evaluation/i10-eval-gemma-round2-explanations-20260918T161356Z/raw/repair_attempts.sqlite \
  --i2 data/context-classification/dependency_error_contexts.jsonl \
  --output <workdir>/data/repair_attempts.csv

cd <workdir> && python -m morph_kgc repair_attempts_config.ini      # -> repair_attempts.nt
# separate process, unmodified upstream mapping, real upstream CSVs:
python -m morph_kgc notebooks_config.ini                             # -> notebooks.nt (627,127 triples)

python validate_kg_materialisation.py \
  --db-path .../raw/repair_attempts.sqlite --csv repair_attempts.csv --rdf repair_attempts.nt \
  --notebooks-rdf notebooks.nt --notebooks-csv <upstream>/data/notebooks.csv \
  --mapping mapping/rml_mapping/repair_attempts.rml.ttl --report kg_validation_report.json
```

`notebooks.nt` (66 MB) is not kept here; it is regenerated from the upstream
checkout in seconds and its sha256 is recorded in `kg_validation_report.json`.

## Vocabulary note

The `prov:` prefix in `repair_attempts.rml.ttl` is bound to
`http://www.w3.org/ns/prov-o#`, because every one of the 22 upstream FAIR
Jupyter mappings binds it that way (and two of them already emit `prov:`
terms under it). The generated `prov:Activity` / `prov:endedAtTime` IRIs
therefore follow the existing graph's convention rather than the W3C
namespace `http://www.w3.org/ns/prov#`. This was inherited deliberately with
the upstream prefix block and is unchanged here.
