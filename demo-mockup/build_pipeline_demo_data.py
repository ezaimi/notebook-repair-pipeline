#!/usr/bin/env python3
"""Generate the static data file for the Pipeline Trace demo.

Pure extraction: reads the stored artefacts of one recorded pipeline run and
writes ``data/pipeline_demo.js``. It never calls an LLM, Docker, PyPI, GitHub
or Ollama, never recomputes an outcome, and never derives an evaluation
metric. Every value it emits is copied from a stored field.

Usage (from the repository root):

    python demo-mockup/build_pipeline_demo_data.py
    python demo-mockup/build_pipeline_demo_data.py --check   # diff only

Source run: the recorded Gemma/Ollama run of the pipeline. Its trace carries
the deterministic mapping attempts, the PyPI/wheel import verification, the
repository dependency-declaration context and the Docker re-execution outcome
that the demo has to show.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUN_ID = "v2-evaluation-20260925T013000Z"
RUN_DIR = REPO / "data" / "evaluation" / RUN_ID
TRACE = RUN_DIR / "raw" / "pipeline-runs" / f"{RUN_ID}.jsonl"
MANIFEST = RUN_DIR / "manifest.json"
VALIDATION = RUN_DIR / "validation_report.json"
CONTEXTS = REPO / "data" / "context-classification-v2" / "dependency_error_contexts.jsonl"
OUT = Path(__file__).resolve().parent / "data" / "pipeline_demo.js"

MAX_WARNINGS = 3

# Records singled out on the dashboard because each one exercises a different
# branch of the recorded pipeline. The captions are descriptive labels for the
# branch; every displayed value still comes from the record's own trace.
HIGHLIGHTS = [
    (198, "Version selected by the model from verified releases, repair confirmed by Docker"),
    (306, "Second round: the first repair exposed a new eligible dependency error"),
    (79, "Curated import mapping, then a newly exposed system-library error that is explained only"),
    (52, "Distribution exists on PyPI, but no wheel evidence that it provides the import"),
    (24, "Every deterministic source failed; the model's proposal did not pass verification"),
    (145, "Model proposed a distribution name that then passed verification"),
]

# Human-readable labels for the deterministic mapping methods recorded in the
# trace, so a reader does not have to know the internal identifiers.
MAPPING_LABELS = {
    "explicit_mismatch_mapping": "Curated mapping table",
    "identity_pep503": "Same-name / PEP 503 lookup",
    "public_import_mapping": "Public import mapping (pipreqs)",
    "llm_proposed_then_verified": "Model proposal, then verified",
}


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def trim_warnings(warnings) -> list[str]:
    """Keep the first few PyPI filename warnings plus an explicit marker.

    The retriever logs one warning per skipped legacy installer filename; a
    record can carry hundreds. Dropping them silently would misrepresent the
    trace, so the omission is stated.
    """
    warnings = list(warnings or [])
    if len(warnings) <= MAX_WARNINGS:
        return warnings
    hidden = len(warnings) - MAX_WARNINGS
    return warnings[:MAX_WARNINGS] + [f"... {hidden} further filename warnings omitted"]


def explanation_payload(entry) -> dict | None:
    """Flatten one stored explanation entry."""
    if not entry:
        return None
    result = entry.get("explanation_result") or {}
    body = result.get("explanation_json") or {}
    llm = entry.get("llm") or {}
    return {
        "status": result.get("status"),
        "summary": body.get("summary"),
        "root_cause": body.get("root_cause"),
        "evidence": list(body.get("evidence") or []),
        "failing_module": body.get("failing_module"),
        "confidence": body.get("explanation_confidence"),
        "limitations": body.get("limitations"),
        "model": llm.get("llm_model"),
        "prompt_template": llm.get("prompt_template"),
        "prompt_strategy": llm.get("prompt_strategy"),
        "attempts": result.get("attempts"),
        "latency_ms": result.get("latency_ms"),
        "tokens_input": result.get("tokens_input"),
        "tokens_output": result.get("tokens_output"),
        "validation_errors": list(result.get("validation_errors") or []),
        "error": result.get("error"),
    }


def build_mapping(i4: dict) -> dict:
    """Deterministic candidate generation, plus a model proposal if one ran."""
    retrieval = i4.get("retrieval_result") or {}
    resolver = retrieval.get("resolver") or {}
    attempts = []
    for attempt in resolver.get("deterministic_attempts") or []:
        method = attempt.get("mapping_method")
        attempts.append({
            "distribution_name": attempt.get("distribution_name"),
            "mapping_method": method,
            "mapping_label": MAPPING_LABELS.get(method, method),
            "status": attempt.get("status"),
            "error": attempt.get("error"),
        })

    proposal = i4.get("mapping_proposal")
    verification = i4.get("mapping_verification") or {}
    llm = i4.get("llm") or {}
    model_proposal = None
    if proposal:
        model_proposal = {
            "suggested_distribution": proposal.get("suggested_distribution"),
            "rationale": proposal.get("rationale"),
            "model": llm.get("model"),
            "role": llm.get("role"),
            "prompt_template": llm.get("prompt_template"),
            "schema_valid": (i4.get("mapping_schema_validation") or {}).get("valid"),
            "verification_status": verification.get("status") or None,
            "verified_distribution": verification.get("distribution_name"),
            "package_found": verification.get("package_found"),
            "source_endpoint": verification.get("source_endpoint"),
            "verified_candidate_count": len(verification.get("candidate_versions") or []),
        }

    method = resolver.get("mapping_method")
    return {
        "resolved_method": method,
        "resolved_method_label": MAPPING_LABELS.get(method, method),
        "scope_status": (resolver.get("scope") or {}).get("status"),
        "scope_reason": (resolver.get("scope") or {}).get("reason"),
        "repository_date": resolver.get("repository_date"),
        "deterministic_attempts": attempts,
        "model_proposal": model_proposal,
    }


def build_pypi(i4: dict) -> dict:
    """PyPI existence check and the per-release wheel import evidence."""
    retrieval = i4.get("retrieval_result") or {}
    candidates = []
    for cand in retrieval.get("candidate_versions") or []:
        verification = cand.get("import_verification") or {}
        candidates.append({
            "version": cand.get("version"),
            "requires_python": cand.get("requires_python"),
            "python_compatibility": cand.get("python_compatibility"),
            "yanked": cand.get("yanked"),
            "first_upload_time": cand.get("first_upload_time"),
            "import_status": verification.get("status"),
            "wheel_filename": verification.get("wheel_filename"),
            "top_level_imports": list(verification.get("top_level_imports") or []),
        })
    evidence = retrieval.get("compatibility_evidence") or {}
    return {
        "status": retrieval.get("status"),
        "import_name": retrieval.get("import_name"),
        "module_path": retrieval.get("module_path"),
        "symbol": retrieval.get("symbol"),
        "distribution_name": retrieval.get("distribution_name"),
        "package_found": retrieval.get("package_found"),
        "latest_version": retrieval.get("latest_version"),
        "python_version": retrieval.get("python_version"),
        "source_endpoint": retrieval.get("source_endpoint"),
        "retrieved_at": retrieval.get("retrieved_at"),
        "error": retrieval.get("error"),
        "compatibility_status": evidence.get("status"),
        "compatibility_meaning": evidence.get("meaning"),
        "repository_date": evidence.get("repository_date"),
        "candidates": candidates,
        "warnings": trim_warnings(retrieval.get("warnings")),
    }


def build_requirements(i4: dict) -> dict | None:
    """Repository dependency-declaration context (never authoritative)."""
    declared = i4.get("declared_constraint")
    if not declared:
        return None
    declarations = []
    for decl in declared.get("matching_declarations") or []:
        declarations.append({
            "path": decl.get("path"),
            "line_number": decl.get("line_number"),
            "raw": decl.get("raw"),
            "requirement": decl.get("requirement"),
            "specifier": decl.get("specifier"),
            "marker": decl.get("marker"),
            "active_for_runtime": decl.get("active_for_runtime"),
            "parse_status": decl.get("parse_status"),
        })
    files = []
    for entry in declared.get("files_considered") or []:
        files.append({
            "path": entry.get("path"),
            "fetched": entry.get("fetched"),
            "ref": entry.get("ref"),
        })
    return {
        "status": declared.get("status"),
        "distribution_name": declared.get("distribution_name"),
        "normalized_distribution_name": declared.get("normalized_distribution_name"),
        "comparison_basis": declared.get("comparison_basis"),
        "declarations": declarations,
        "alias_declarations": list(declared.get("alias_declarations") or []),
        "files_considered": files,
        "limitations": list(declared.get("limitations") or []),
        "non_authoritative": declared.get("non_authoritative"),
        "compatible_candidate_versions": list(declared.get("compatible_candidate_versions") or []),
    }


def build_decision(i4: dict) -> dict:
    """The repair decision, and the model's role in it where there was one."""
    llm = i4.get("llm") or {}
    source = i4.get("decision_source")
    # A model appears here only for verified-version selection; the name
    # proposal is recorded on the mapping step instead.
    model = None
    if source == "llm_select_from_verified_versions" and llm.get("role") != "distribution_proposal":
        model = {
            "model": llm.get("model"),
            "role": llm.get("role"),
            "prompt_template": llm.get("prompt_template"),
            "prompt_version": llm.get("prompt_version"),
        }
    return {
        "status": i4.get("status"),
        "source": source,
        "action": i4.get("final_action"),
        "install_name": i4.get("final_install_name"),
        "version": i4.get("final_version"),
        "command": i4.get("command"),
        "rationale": i4.get("final_rationale"),
        "attempts": i4.get("attempts"),
        "schema_valid": (i4.get("schema_validation") or {}).get("valid"),
        "grounding_valid": (i4.get("grounding_validation") or {}).get("valid"),
        "grounding_errors": list((i4.get("grounding_validation") or {}).get("errors") or []),
        "errors": list(i4.get("errors") or []),
        "model": model,
    }


def build_applied(i5: dict) -> dict:
    """FixApplicator: what was applied and what Docker reported."""
    return {
        "status": i5.get("status"),
        "action": i5.get("action"),
        "install_name": i5.get("install_name"),
        "version": i5.get("version"),
        "command": i5.get("command"),
        "return_code": i5.get("apply_return_code"),
        "execution_status": i5.get("execution_status"),
        "outcome": i5.get("outcome"),
        "same_as_original_error": i5.get("same_as_original_error"),
        "new_error_type": i5.get("new_error_type"),
        "new_error_message": i5.get("new_error_message"),
        "elapsed_seconds": i5.get("elapsed_seconds"),
        "commit_checkout_status": i5.get("commit_checkout_status"),
        "commit_resolution_note": i5.get("commit_resolution_note"),
        "repository_commit": i5.get("repository_commit"),
        "failure_stage": i5.get("failure_stage"),
        "skip_reason": i5.get("skip_reason"),
        "diagnostic_message": i5.get("diagnostic_message"),
        "errors": list(i5.get("errors") or []),
    }


def build_round(round_rec: dict, trigger_in: dict | None) -> dict:
    """One recorded repair round."""
    i4 = round_rec.get("i4_result") or {}
    i5 = round_rec.get("i5_result") or {}
    inp = i4.get("input") or {}
    trigger_out = round_rec.get("round2_trigger") or {}

    entered = None
    if trigger_in:
        # Why this round ran at all: the previous round's recorded decision.
        reclassified = trigger_in.get("round2_record") or {}
        entered = {
            "reason": trigger_in.get("reason"),
            "error_type": reclassified.get("error_type"),
            "error_message": reclassified.get("error_message"),
            "failing_module": reclassified.get("failing_module"),
            "scope_status": reclassified.get("scope_status"),
            "refined_subtype": reclassified.get("refined_subtype"),
            "context_status": reclassified.get("context_status"),
        }

    return {
        "round": round_rec.get("round"),
        "status": round_rec.get("status"),
        "repair_attempts_row_id": round_rec.get("repair_attempts_row_id"),
        "entered_because": entered,
        "error": {
            "type": inp.get("error_type"),
            "message": inp.get("error_message"),
            "module": inp.get("failing_module"),
        },
        "classification": {
            "original_subtype": inp.get("original_subtype"),
            "refined_subtype": inp.get("refined_subtype"),
            "root_cause_hint": inp.get("root_cause_hint"),
            "scope_status": inp.get("scope_status"),
            "exclusion_reason": inp.get("exclusion_reason"),
            "context_status": inp.get("context_status"),
            "eligibility": (i4.get("eligibility") or {}).get("decision"),
            "signature": i4.get("extracted_signature") or {},
        },
        "explanation": explanation_payload(round_rec.get("explanation")),
        "mapping": build_mapping(i4),
        "pypi": build_pypi(i4),
        "requirements": build_requirements(i4),
        "decision": build_decision(i4),
        "applied": build_applied(i5),
        "next_round": {
            "triggered": trigger_out.get("triggered"),
            "reason": trigger_out.get("reason"),
            "exclusion_reason": trigger_out.get("exclusion_reason"),
        } if trigger_out else None,
    }


def build_explain_only(trigger: dict) -> dict | None:
    """A newly exposed error that was explained but is out of repair scope.

    Recorded on the Round-1 trigger when the reclassified error is excluded:
    the explanation exists in the trace, no repair round follows.
    """
    if not trigger or trigger.get("triggered"):
        return None
    reason = str(trigger.get("reason") or "")
    if not reason.startswith("new_error_not_repair_eligible"):
        return None
    record = trigger.get("round2_record") or {}
    return {
        "reason": reason,
        "error_type": record.get("error_type"),
        "error_message": record.get("error_message"),
        "failing_module": record.get("failing_module"),
        "refined_subtype": record.get("refined_subtype"),
        "scope_status": record.get("scope_status"),
        "exclusion_reason": record.get("exclusion_reason") or trigger.get("exclusion_reason"),
        "root_cause_hint": record.get("root_cause_hint"),
        "confidence": record.get("confidence"),
        "context_status": record.get("context_status"),
        "explanation": explanation_payload(trigger.get("explanation")),
    }


def build_record(rec: dict, ctx: dict) -> dict:
    rounds_in = rec.get("rounds") or []
    rounds = []
    carried_trigger = None
    for round_rec in rounds_in:
        rounds.append(build_round(round_rec, carried_trigger))
        carried_trigger = round_rec.get("round2_trigger") or None

    first = rounds_in[0] if rounds_in else {}
    last = rounds[-1] if rounds else {}
    explain_only = build_explain_only(first.get("round2_trigger") or {})

    return {
        "id": rec.get("notebook_execution_id"),
        "index": rec.get("index"),
        "notebook": {
            "notebook_id": ctx.get("notebook_id"),
            "name": ctx.get("notebook_name"),
            "repository_url": ctx.get("repository_url"),
            "repository_commit": ctx.get("repository_commit"),
            "repository_commit_date": ctx.get("repository_commit_date"),
            "error_cell_index": ctx.get("error_cell_index"),
        },
        "classifier": {
            "confidence": ctx.get("confidence"),
            "scope_status": ctx.get("scope_status"),
            "exclusion_reason": ctx.get("exclusion_reason"),
            "root_cause_hint": ctx.get("root_cause_hint"),
            "context_status": ctx.get("context_status"),
            "provenance_status": ctx.get("provenance_status"),
        },
        "eligibility": rec.get("repair_eligibility") or {},
        "explanation_status": rec.get("explanation_status"),
        "explanation": explanation_payload(rec.get("explanation")),
        "rounds": rounds,
        "explain_only": explain_only,
        "final": {
            "rounds_run": len(rounds),
            "outcome": (last.get("applied") or {}).get("outcome"),
            "decision_status": (last.get("decision") or {}).get("status"),
            "last_round": last.get("round"),
        },
    }


def build_provenance(manifest: dict, validation: dict, record_count: int) -> dict:
    checks = validation.get("checks") or []
    return {
        "run_id": manifest.get("run_id"),
        "split": manifest.get("split"),
        "model": manifest.get("model"),
        "max_rounds": manifest.get("max_rounds"),
        "prompt_strategy": manifest.get("prompt_strategy"),
        "expected_record_count": manifest.get("expected_record_count"),
        "actual_record_count": record_count,
        "created_at": manifest.get("created_at"),
        "git_commit_sha": manifest.get("git_commit_sha"),
        "python_version": manifest.get("python_version"),
        "explanation_prompt_version": manifest.get("explanation_prompt_version"),
        "repair_prompt_version": manifest.get("repair_prompt_version"),
        "config_paths": manifest.get("config_paths") or {},
        "checks_total": len(checks),
        "checks_passed": sum(1 for c in checks if c.get("passed")),
        "trace_file": str(TRACE.relative_to(REPO)).replace("\\", "/"),
        "context_file": str(CONTEXTS.relative_to(REPO)).replace("\\", "/"),
    }


def build_payload() -> dict:
    trace = read_jsonl(TRACE)
    contexts = {c.get("notebook_execution_id"): c for c in read_jsonl(CONTEXTS)}
    manifest = read_json(MANIFEST)
    validation = read_json(VALIDATION)

    records = [build_record(rec, contexts.get(rec.get("notebook_execution_id"), {}))
               for rec in trace]
    records.sort(key=lambda r: r["index"] if r["index"] is not None else 0)

    by_id = {r["id"] for r in records}
    highlights = [{"id": rid, "note": note} for rid, note in HIGHLIGHTS if rid in by_id]
    missing = [rid for rid, _ in HIGHLIGHTS if rid not in by_id]
    if missing:
        print(f"warning: highlighted records absent from trace: {missing}", file=sys.stderr)

    return {
        "provenance": build_provenance(manifest, validation, len(records)),
        "mapping_labels": MAPPING_LABELS,
        "highlights": highlights,
        "records": records,
    }


def render(payload: dict) -> str:
    body = json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=False)
    header = (
        "/* GENERATED FILE - do not edit by hand.\n"
        "   Rebuild with: python demo-mockup/build_pipeline_demo_data.py\n"
        f"   Extracted from the recorded run {RUN_ID}.\n"
        "   Every value is copied from a stored artefact; nothing is recomputed. */\n"
    )
    return f"{header}const PIPELINE_DEMO = {body};\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report whether the output file is up to date; write nothing")
    args = parser.parse_args()

    for path in (TRACE, MANIFEST, VALIDATION, CONTEXTS):
        if not path.exists():
            print(f"error: missing required artefact: {path}", file=sys.stderr)
            return 2

    text = render(build_payload())

    if args.check:
        if not OUT.exists():
            print(f"{OUT.name}: missing")
            return 1
        current = OUT.read_text(encoding="utf-8")
        if current == text:
            print(f"{OUT.name}: up to date ({len(text):,} bytes)")
            return 0
        print(f"{OUT.name}: differs from the artefacts "
              f"(stored {len(current):,} bytes, rebuilt {len(text):,} bytes)")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    payload = json.loads(text.split("const PIPELINE_DEMO = ", 1)[1].rstrip().rstrip(";"))
    print(f"wrote {OUT.relative_to(REPO)} ({len(text):,} bytes)")
    print(f"  records: {len(payload['records'])}, highlighted: {len(payload['highlights'])}")
    print(f"  run: {payload['provenance']['run_id']} "
          f"({payload['provenance']['checks_passed']}/{payload['provenance']['checks_total']} checks passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
