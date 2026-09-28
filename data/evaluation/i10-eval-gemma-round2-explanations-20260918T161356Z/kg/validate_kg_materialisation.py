#!/usr/bin/env python3

"""Explicit pass/fail validation of the full-scale repair_attempts KG
materialisation (mapping/rml_mapping/repair_attempts.rml.ttl run through
Morph-KGC over scripts/export_repair_attempts_csv.py's export of a
repair_attempts SQLite table).

Every check is made against the SQLite table itself as ground truth - not
against the CSV alone and not against Morph-KGC's own triple count - so a
triple that is present, absent, mistyped, or carrying the wrong value is
caught per row, not just in aggregate. The notebook-side check parses the
RDF the *unmodified* upstream notebooks.rml.ttl produced from the real
notebooks.csv/repositories.csv (materialised as its own separate Morph-KGC
process, exactly as run_fairjupyter_kg.sh does), so a repr:hadRepairAttempt
link is only accepted if its subject exists there as an rdf:type
repr:Notebook resource.

Requires rdflib. Exits 0 only when every check passes.
"""

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from rdflib import RDF, XSD, Graph, Literal, Namespace, URIRef

REPR = Namespace("https://w3id.org/reproduceme/")
PAV = Namespace("http://purl.org/pav/")
# NOTE: every upstream FAIR Jupyter mapping (and repair_attempts.rml.ttl,
# which reuses their prefix block) binds prov: to .../ns/prov-o#, not to
# the W3C PROV-O namespace .../ns/prov#. The generated graph therefore
# uses the prov-o# IRIs, and so must this check.
PROV = Namespace("http://www.w3.org/ns/prov-o#")

# column -> predicate, exactly as repair_attempts.rml.ttl maps them
PREDICATES = {
    "failing_module": REPR.failingModule,
    "subtype": REPR.subtype,
    "explanation": REPR.explanation,
    "action": REPR.fixAction,
    "install_name": REPR.installName,
    "version": REPR.fixVersion,
    "command": REPR.fixCommand,
    "rationale": REPR.fixRationale,
    "pypi_evidence": REPR.pypiEvidence,
    "outcome": REPR.fixOutcome,
    "new_error_type": REPR.exception,
    "new_error_message": REPR.msg,
    "llm_model": REPR.llmModel,
    "prompt_strategy": REPR.promptStrategy,
    "round": REPR.round,
    "run_id": REPR.runId,
    "created_at": PROV.endedAtTime,
}
REPAIR_IRI = re.compile(r"^https://w3id\.org/reproduceme/repairattempt_(\d+)$")
NOTEBOOK_IRI_PREFIX = "https://w3id.org/reproduceme/notebook_"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def short(term):
    return (
        str(term)
        .replace("https://w3id.org/reproduceme/", "repr:")
        .replace("http://www.w3.org/ns/prov-o#", "prov:")
        .replace("http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdf:")
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db-path", required=True, help="repair_attempts SQLite database (ground truth)")
    parser.add_argument("--csv", required=True, help="CSV written by scripts/export_repair_attempts_csv.py")
    parser.add_argument("--rdf", required=True, help="N-Triples produced by Morph-KGC from repair_attempts.rml.ttl")
    parser.add_argument("--notebooks-rdf", required=True,
                        help="N-Triples produced by the unmodified upstream notebooks.rml.ttl (separate Morph-KGC run)")
    parser.add_argument("--notebooks-csv", required=True, help="upstream data/notebooks.csv")
    parser.add_argument("--mapping", default=None, help="repair_attempts.rml.ttl (recorded by hash in the report)")
    parser.add_argument("--report", default=None, help="write the JSON report here")
    args = parser.parse_args()

    checks = []

    def check(name, passed, detail=""):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        print(("PASS " if passed else "FAIL ") + name + (f"  -- {detail}" if detail else ""))

    # --- 1. syntax -------------------------------------------------------
    g = Graph()
    g.parse(args.rdf, format="nt")
    g_ttl = Graph()
    g_ttl.parse(args.rdf, format="turtle")
    with open(args.rdf, encoding="utf-8") as f:
        raw_lines = sum(1 for line in f if line.strip())
    check("rdf_parses_as_ntriples", True, f"{len(g)} triples")
    check("rdf_parses_as_turtle_with_same_triple_count", len(g_ttl) == len(g), f"{len(g_ttl)} triples")
    check("no_duplicate_triples_in_file", raw_lines == len(g), f"file lines={raw_lines} graph={len(g)}")

    # --- ground truth ------------------------------------------------------
    conn = sqlite3.connect(f"file:{args.db_path}?mode=ro", uri=True)
    cols = [r[1] for r in conn.execute("pragma table_info(repair_attempts)")]
    db = {r[0]: dict(zip(cols, r)) for r in conn.execute("select * from repair_attempts order by id")}
    with open(args.csv, newline="", encoding="utf-8") as f:
        csv_rows = {int(r["id"]): r for r in csv.DictReader(f)}
    check("csv_row_ids_equal_sqlite_row_ids", set(csv_rows) == set(db), f"csv={len(csv_rows)} sqlite={len(db)}")
    notebook_of = {i: int(r["notebook_id"]) for i, r in csv_rows.items()}
    expected_iri = {i: URIRef(f"https://w3id.org/reproduceme/repairattempt_{i}") for i in db}

    # --- 2/3. resources --------------------------------------------------
    repair_subjects = set(g.subjects(RDF.type, REPR.RepairAttempt))
    activity_subjects = set(g.subjects(RDF.type, PROV.Activity))
    check("one_repair_attempt_resource_per_sqlite_row",
          repair_subjects == set(expected_iri.values()), f"{len(repair_subjects)} resources / {len(db)} rows")
    check("every_repair_attempt_typed_repr_RepairAttempt_and_prov_Activity",
          repair_subjects == activity_subjects, f"prov:Activity={len(activity_subjects)}")
    ids_from_iris = sorted(int(REPAIR_IRI.match(str(s)).group(1)) for s in repair_subjects if REPAIR_IRI.match(str(s)))
    check("no_duplicate_repair_attempt_iris", ids_from_iris == sorted(db) and len(ids_from_iris) == len(repair_subjects))
    other_subjects = set(g.subjects()) - repair_subjects
    check("only_other_subjects_are_notebook_iris",
          all(str(s).startswith(NOTEBOOK_IRI_PREFIX) for s in other_subjects), f"{len(other_subjects)} notebook subjects")

    # --- 4. notebook -> repair links --------------------------------------
    links = list(g.triples((None, REPR.hadRepairAttempt, None)))
    link_subjects = defaultdict(list)
    for s, _, o in links:
        link_subjects[o].append(s)
    bad_links = [
        (i, [str(s) for s in link_subjects.get(iri, [])])
        for i, iri in expected_iri.items()
        if link_subjects.get(iri, []) != [URIRef(f"{NOTEBOOK_IRI_PREFIX}{notebook_of[i]}")]
    ]
    linked_notebooks = {s for s, _, _ in links}
    check("every_repair_attempt_linked_from_exactly_its_own_notebook",
          not bad_links and len(links) == len(db), f"{len(links)} links, {len(linked_notebooks)} distinct notebooks; bad={bad_links[:3]}")
    check("every_link_object_is_a_typed_repair_attempt", all(o in repair_subjects for _, _, o in links))

    # --- 5. notebook IRIs exist in the upstream KG ---------------------------
    gn = Graph()
    gn.parse(args.notebooks_rdf, format="nt")
    upstream_notebooks = set(gn.subjects(RDF.type, REPR.Notebook))
    missing = [str(s) for s in linked_notebooks if s not in upstream_notebooks]
    check("linked_notebook_iris_exist_as_repr_Notebook_in_upstream_notebooks_mapping_output",
          not missing, f"{len(linked_notebooks)} linked / {len(upstream_notebooks)} upstream repr:Notebook ({len(gn)} triples); missing={missing[:3]}")
    with_repo = sum(1 for s in linked_notebooks if (s, PAV.retrievedFrom, None) in gn)
    check("linked_notebooks_carry_pav_retrievedFrom_in_upstream_output", with_repo == len(linked_notebooks), f"{with_repo}/{len(linked_notebooks)}")
    with open(args.notebooks_csv, newline="", encoding="utf-8") as f:
        source_ids = {r["id"] for r in csv.DictReader(f)}
    check("linked_notebook_ids_present_in_upstream_notebooks_csv", all(str(notebook_of[i]) in source_ids for i in db))

    # --- 6-9. per-row reconstruction against SQLite ------------------------
    mismatches, empty_literals, unexpected, datetime_bad = [], [], [], []
    known = set(PREDICATES.values()) | {RDF.type}
    for i, iri in expected_iri.items():
        row = db[i]
        po = defaultdict(list)
        for p, o in g.predicate_objects(iri):
            po[p].append(o)
        unexpected.extend((i, str(p)) for p in po if p not in known)
        for column, predicate in PREDICATES.items():
            value, objects = row[column], po.get(predicate, [])
            if value is None:
                if objects:
                    mismatches.append((i, column, "triple present for NULL column"))
                continue
            if len(objects) != 1 or not isinstance(objects[0], Literal):
                mismatches.append((i, column, f"expected exactly one literal, got {len(objects)}"))
                continue
            literal = objects[0]
            if str(literal) == "":
                empty_literals.append((i, column))
            if str(literal) != str(value):
                mismatches.append((i, column, "value differs from SQLite"))
            if column == "created_at":
                if literal.datatype != XSD.dateTime or not isinstance(literal.toPython(), datetime):
                    datetime_bad.append((i, str(literal.datatype)))
            elif literal.datatype is not None:
                mismatches.append((i, column, f"unexpected datatype {literal.datatype}"))
        for column in ("explanation", "pypi_evidence"):
            if row[column] is not None and po.get(PREDICATES[column]):
                if json.loads(str(po[PREDICATES[column]][0])) != json.loads(row[column]):
                    mismatches.append((i, column, "JSON differs from SQLite"))
    check("every_literal_equals_its_sqlite_value", not mismatches, f"mismatches={mismatches[:5]}")
    check("null_columns_produce_no_triple_and_no_empty_string_literal", not empty_literals and not any(m[2].startswith("triple present") for m in mismatches),
          f"empty literals={len(empty_literals)}")
    check("no_unexpected_predicates_on_repair_attempts", not unexpected, f"{unexpected[:3]}")
    check("prov_endedAtTime_typed_xsd_dateTime_and_parseable_on_every_row",
          not datetime_bad and len(list(g.triples((None, PROV.endedAtTime, None)))) == len(db), f"bad={datetime_bad[:3]}")

    predicate_counts = Counter(p for _, p, _ in g)
    expected_counts = {
        predicate: conn.execute(f"select count(*) from repair_attempts where {column} is not null").fetchone()[0]
        for column, predicate in PREDICATES.items()
    }
    count_mismatch = {short(p): (predicate_counts[p], n) for p, n in expected_counts.items() if predicate_counts[p] != n}
    check("per_predicate_triple_count_equals_sqlite_non_null_count", not count_mismatch, str(count_mismatch))

    error_subjects = set(g.subjects(REPR.exception, None)) | set(g.subjects(REPR.msg, None))
    expected_error = {expected_iri[i] for i in db if db[i]["new_error_type"] is not None or db[i]["new_error_message"] is not None}
    check("post_repair_error_predicates_only_where_values_exist", error_subjects == expected_error, f"{len(error_subjects)} resources")
    outcome_subjects = set(g.subjects(REPR.fixOutcome, None))
    check("fixOutcome_only_on_rows_with_recorded_outcome",
          outcome_subjects == {expected_iri[i] for i in db if db[i]["outcome"] is not None}, f"{len(outcome_subjects)} resources")

    # --- rounds ----------------------------------------------------------------
    round1 = set(g.subjects(REPR.round, Literal("1")))
    round2 = set(g.subjects(REPR.round, Literal("2")))
    check("round_literal_partitions_resources_into_round1_and_round2",
          round1 == {expected_iri[i] for i in db if db[i]["round"] == 1}
          and round2 == {expected_iri[i] for i in db if db[i]["round"] == 2}
          and (round1 | round2) == repair_subjects and round1.isdisjoint(round2),
          f"round1={len(round1)} round2={len(round2)}")
    round2_notebooks = {s for s, _, o in links if o in round2}
    round1_notebooks = {s for s, _, o in links if o in round1}
    check("every_round2_notebook_also_has_a_round1_resource", round2_notebooks <= round1_notebooks, f"{len(round2_notebooks)} round-2 notebooks")
    run_ids = {str(o) for o in g.objects(None, REPR.runId)}
    models = {str(o) for o in g.objects(None, REPR.llmModel)}
    strategies = {str(o) for o in g.objects(None, REPR.promptStrategy)}
    check("single_run_id_model_and_prompt_strategy", len(run_ids) == 1 and len(models) == 1 and len(strategies) == 1,
          f"{sorted(run_ids)} {sorted(models)} {sorted(strategies)}")

    # --- union graph: the two mappings' notebook nodes coincide ----------------
    union = gn + g
    query = """
        SELECT (COUNT(DISTINCT ?nb) AS ?notebooks) (COUNT(DISTINCT ?ra) AS ?attempts) WHERE {
          ?nb a <https://w3id.org/reproduceme/Notebook> ;
              <https://w3id.org/reproduceme/hadRepairAttempt> ?ra .
          ?ra a <https://w3id.org/reproduceme/RepairAttempt> }"""
    notebooks_hit, attempts_hit = [(int(r.notebooks), int(r.attempts)) for r in union.query(query)][0]
    check("sparql_over_union_reaches_every_repair_attempt_from_a_typed_notebook",
          notebooks_hit == len(linked_notebooks) and attempts_hit == len(db),
          f"union={len(union)} triples; notebooks={notebooks_hit} attempts={attempts_hit}")

    summary = {
        "sqlite_rows": len(db),
        "sqlite_round1_rows": sum(1 for r in db.values() if r["round"] == 1),
        "sqlite_round2_rows": sum(1 for r in db.values() if r["round"] == 2),
        "csv_rows": len(csv_rows),
        "triples": len(g),
        "repair_attempt_resources": len(repair_subjects),
        "notebook_to_repair_links": len(links),
        "distinct_linked_notebooks": len(linked_notebooks),
        "round1_resources": len(round1),
        "round2_resources": len(round2),
        "upstream_notebooks_triples": len(gn),
        "upstream_repr_Notebook_resources": len(upstream_notebooks),
        "union_triples": len(union),
        "predicate_counts": {short(p): n for p, n in sorted(predicate_counts.items(), key=lambda kv: short(kv[0]))},
        "checks_passed": sum(1 for c in checks if c["passed"]),
        "checks_total": len(checks),
    }
    print("\nSUMMARY")
    for key, value in summary.items():
        if key != "predicate_counts":
            print(f"  {key:36s} {value}")

    if args.report:
        import rdflib
        try:
            from importlib.metadata import version as pkg_version
            morph_version = pkg_version("morph_kgc")
        except Exception:  # morph_kgc need not be installed to run this check
            morph_version = None
        report = {
            "inputs": {
                "db_path": str(args.db_path), "db_sha256": sha256(args.db_path),
                "csv_path": str(args.csv), "csv_sha256": sha256(args.csv),
                "rdf_path": str(args.rdf), "rdf_sha256": sha256(args.rdf),
                "notebooks_rdf_path": str(args.notebooks_rdf), "notebooks_rdf_sha256": sha256(args.notebooks_rdf),
                "notebooks_csv_path": str(args.notebooks_csv), "notebooks_csv_sha256": sha256(args.notebooks_csv),
                "mapping_path": args.mapping, "mapping_sha256": sha256(args.mapping) if args.mapping else None,
            },
            "tools": {"python": sys.version.split()[0], "rdflib": rdflib.__version__, "morph_kgc": morph_version},
            "summary": summary,
            "checks": checks,
        }
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nreport written to {args.report}")

    sys.exit(0 if all(c["passed"] for c in checks) else 1)


if __name__ == "__main__":
    main()
