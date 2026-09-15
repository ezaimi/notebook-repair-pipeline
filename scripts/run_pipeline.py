#!/usr/bin/env python3

"""PipelineOrchestrator (i7): sequences the already-implemented i2-i6
components into one pipeline invocation per dependency-error record.

    i2-classified record
            |
      LLMExplainer (i3)                         -- always, all 214 rows
            |
      repair eligibility check (scope_status)    -- reused from i4
            |  (usable only)
      RAGRepairAgent (i4)
            |
      FixApplicator (i5)  -- clone/build/run/re-execute
            |
      ResultLogger (i6)   -- one repair_attempts row per round

This module reuses i2-i6's own functions directly (classification,
PyPI retrieval, proposal validation, Docker execution, row building) - it
does not reimplement any of them. See docs/pipeline-orchestrator.md for
the full design, the bounded-second-round trigger rules, and the
cumulative Round 1 + Round 2 environment strategy.
"""

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import docker_runner
import fix_applicator
import rag_repair_agent
import result_logger
import run_llm_explainer
from extract_error_contexts import classify_refined
from prepare_dependency_dataset import classify as classify_scope
from prepare_dependency_dataset import extract_failing_module
from pypi_retriever import load_rag_repair_config
from render_explanation_prompt import render_record_prompt


DEFAULT_I2_PATH = "data/context-classification/dependency_error_contexts.jsonl"
DEFAULT_DB_PATH = "data/repair-attempts/repair_attempts.sqlite"
DEFAULT_TRACE_DIR = "data/pipeline-runs"

# How long a connection waits for repair_attempts.sqlite's lock to clear
# before giving up. Generous relative to any single write (create_table()/
# insert_row() each commit immediately - see open_repair_attempts_db()'s
# docstring) but still short enough that a genuinely stuck/dead writer
# fails with a clear message rather than hanging the whole run.
DB_LOCK_TIMEOUT_SECONDS = 30.0

# Hard ceiling, independent of whatever --max-rounds is passed: this
# orchestrator can never run a third round, no matter what a caller
# requests or what a (hypothetical, buggy) config override says.
MAX_ROUNDS_HARD_CAP = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_run_id(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return "i7-{}".format(now.strftime("%Y%m%dT%H%M%SZ"))


# --- dataset loading / selection ---------------------------------------------

def load_all_records(i2_path: str) -> List[Dict[str, Any]]:
    records = []
    with open(i2_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def select_records(
    records: List[Dict[str, Any]],
    split: Optional[str],
    start_index: int,
    limit: Optional[int],
) -> List[Tuple[int, Dict[str, Any]]]:
    """Filter by `split` (None/"all" = every record, regardless of split),
    keeping each record's original 0-based position in the full i2 file for
    traceability, then apply start_index/limit as a slice over the
    *filtered* sequence - so `--split dev --start-index 0 --limit 1` means
    "the first dev-split record", not "the first line of the whole file".
    Never mutates or reorders `records`."""
    if split and split != "all":
        filtered = [(i, r) for i, r in enumerate(records) if r.get("split") == split]
    else:
        filtered = list(enumerate(records))

    end = None if limit is None else start_index + limit
    return filtered[start_index:end]


# --- explanation stage (i3, reused) ------------------------------------------

def explain_record(
    record: Dict[str, Any],
    explainer_config: Dict[str, Any],
    explainer_template: str,
    explainer_schema_path: str,
    run_id: str,
    index: int,
) -> Dict[str, Any]:
    """Same per-record body as run_llm_explainer.py's own CLI loop, reused
    function-for-function (render_record_prompt, explain_one,
    build_input_metadata, build_llm_metadata) rather than reimplemented.
    Runs for every record regardless of repair eligibility - explanation
    scope is all 214 rows, never gated by scope_status."""
    try:
        prompt = render_record_prompt(record, explainer_template)
    except Exception as e:
        return {
            "run_id": run_id,
            "created_at": utc_now(),
            "index": index,
            "input": run_llm_explainer.build_input_metadata(record),
            "llm": run_llm_explainer.build_llm_metadata(explainer_config),
            "explanation_result": {
                "status": "render_failed",
                "failure_category": "render_failed",
                "error": "{}: {}".format(type(e).__name__, e),
            },
        }

    explanation_result = run_llm_explainer.explain_one(prompt, explainer_config, explainer_schema_path)
    return {
        "run_id": run_id,
        "created_at": utc_now(),
        "index": index,
        "input": run_llm_explainer.build_input_metadata(record),
        "llm": run_llm_explainer.build_llm_metadata(explainer_config),
        "explanation_result": explanation_result,
    }


# --- excluded-record stub (never calls RAGRepairAgent) -----------------------

def build_excluded_repair_stub(record: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    """Produce the exact same abstained result shape
    rag_repair_agent.run_repair_agent() would produce for a repair-ineligible
    record - by reusing its own check_eligibility()/_base_result() helpers -
    without ever calling run_repair_agent() itself. This is the orchestrator
    enforcing "an excluded record must still be explainable but must never
    call RAGRepairAgent or FixApplicator" (see docs/pipeline-orchestrator.md)
    while keeping the historical repair_attempts contract (docs/architecture-
    note.md §7.3): an excluded row still gets one abstained row, action
    "none", so the benchmark table keeps one row per considered record."""
    result = rag_repair_agent._base_result(record, run_id)
    decision, exclusion_reason = rag_repair_agent.check_eligibility(record)
    result["eligibility"] = {
        "decision": decision,
        "scope_status": record.get("scope_status"),
        "exclusion_reason": exclusion_reason,
    }
    result["errors"].append("not repair-eligible: {} ({})".format(decision, exclusion_reason))
    result["status"] = "abstained"
    return result


# --- Round N->N+1 reclassification (reuses i1/i2 classification only) -------

def build_round2_record(original_record: Dict[str, Any], new_error_type: str, new_error_message: str) -> Dict[str, Any]:
    """Build a fresh classified/context record for the failure FixApplicator
    observed after Round 1, reusing i1's scope classifier
    (prepare_dependency_dataset.classify) for scope_status/exclusion_reason
    and i2's refinement (extract_error_contexts.classify_refined) for
    root_cause_hint/confidence - the exact same two-stage classification
    every original dataset row already went through, applied to the new
    failure instead of reimplementing a parallel rule set.

    Notebook/repository identity (notebook_execution_id, repository_id,
    notebook_id, notebook_name, repository_url, split) is carried over from
    `original_record` unchanged - it is the same notebook. No prompt_context
    is invented: this failure was never re-fetched from GitHub/legacy
    executions, so prompt_context is left absent and render_repair_prompt()/
    render_record_prompt() fall back to "Not available" for cell source,
    exactly as they already do for any record lacking it."""
    new_failing_module = extract_failing_module(new_error_message)
    original_subtype, scope_status, exclusion_reason = classify_scope(
        new_error_type, new_error_message, new_failing_module
    )
    refined_subtype, confidence, root_cause_hint = classify_refined(
        new_error_type, new_error_message, new_failing_module, original_subtype
    )

    return {
        "notebook_execution_id": original_record.get("notebook_execution_id"),
        "repository_id": original_record.get("repository_id"),
        "notebook_id": original_record.get("notebook_id"),
        "notebook_name": original_record.get("notebook_name"),
        "repository_url": original_record.get("repository_url"),
        "error_type": new_error_type,
        "error_message": new_error_message,
        "error_cell_index": None,
        "failing_module": new_failing_module,
        "original_subtype": original_subtype,
        "refined_subtype": refined_subtype,
        "scope_status": scope_status,
        "exclusion_reason": exclusion_reason,
        "split": original_record.get("split"),
        "confidence": confidence,
        "root_cause_hint": root_cause_hint,
        "context_status": "round2_reclassified_from_execution_outcome",
    }


def evaluate_round2_trigger(i5_result: Optional[Dict[str, Any]], original_record: Dict[str, Any]) -> Dict[str, Any]:
    """Decide whether a Round 2 attempt is warranted, per the exact rules in
    docs/pipeline-orchestrator.md: Round 1 must have actually applied a fix
    and produced outcome "still_failing" with a genuinely different,
    newly-exposed error that is itself an eligible pip-only dependency
    failure under i1's own scope rules. `same_as_original_error == True`
    alone stops Round 2 even before reclassification is attempted; a
    "different" new error still only triggers Round 2 once it is
    independently classified as `scope_status == "usable"` with a
    supported subtype - never merely because it differs from the original.

    Returns a dict; when triggered is True, "round2_record" carries the
    fully reclassified record to feed into Round 2. Pure function, no I/O,
    no LLM call - fully unit-testable."""
    if i5_result is None or i5_result.get("outcome") != "still_failing":
        return {"triggered": False, "reason": "round1_outcome_not_still_failing"}

    new_error_type = i5_result.get("new_error_type")
    new_error_message = i5_result.get("new_error_message")
    if not new_error_type:
        return {"triggered": False, "reason": "no_new_error_recorded"}

    if i5_result.get("same_as_original_error"):
        return {"triggered": False, "reason": "same_as_original_error"}

    round2_record = build_round2_record(original_record, new_error_type, new_error_message)
    decision, exclusion_reason = rag_repair_agent.check_eligibility(round2_record)

    if decision != "usable":
        return {
            "triggered": False,
            "reason": "new_error_not_repair_eligible:{}".format(decision),
            "round2_record": round2_record,
            "exclusion_reason": exclusion_reason,
        }

    if round2_record["refined_subtype"] not in rag_repair_agent.SUPPORTED_SUBTYPES:
        return {
            "triggered": False,
            "reason": "unsupported_subtype:{}".format(round2_record["refined_subtype"]),
            "round2_record": round2_record,
        }

    return {"triggered": True, "reason": "new_dependency_error_eligible", "round2_record": round2_record}


# --- one repair round (RAGRepairAgent -> FixApplicator, both reused) -------

def run_repair_round(
    record: Dict[str, Any],
    run_id: str,
    repair_config: Dict[str, Any],
    fix_config: Dict[str, Any],
    i2_index: Dict[int, Dict[str, Any]],
    repository_metadata_lookup: Optional[Callable[[int], Optional[Dict[str, Any]]]],
    runner: docker_runner.Runner,
    work_dir_base: Optional[Path],
    prior_fix_argvs: Optional[List[List[str]]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """RAGRepairAgent (i4) then FixApplicator (i5), both called unmodified
    with the shared orchestration run_id, and both always called for a
    usable record regardless of round: FixApplicator's own resolve_attempt()
    already gates whether a real Docker attempt happens (abstained/failed/
    action=="none" -> "skipped", zero subprocess calls), so the orchestrator
    reuses that gate instead of duplicating it."""
    i4_result = rag_repair_agent.run_repair_agent(record, repair_config, run_id=run_id)
    i5_result = fix_applicator.apply_and_validate(
        i4_result,
        i2_index,
        fix_config,
        repository_metadata_lookup=repository_metadata_lookup,
        runner=runner,
        run_id=run_id,
        work_dir_base=work_dir_base,
        prior_fix_argvs=prior_fix_argvs,
    )
    return i4_result, i5_result


# --- one dataset record, end to end -------------------------------------------

def process_record(
    record: Dict[str, Any],
    original_index: int,
    run_id: str,
    max_rounds: int,
    explainer_config: Dict[str, Any],
    explainer_template: str,
    explainer_schema_path: str,
    repair_config: Dict[str, Any],
    fix_config: Dict[str, Any],
    i2_index: Dict[int, Dict[str, Any]],
    repository_metadata_lookup: Optional[Callable[[int], Optional[Dict[str, Any]]]],
    runner: docker_runner.Runner,
    work_dir_base: Optional[Path],
    already_logged: Callable[[Any, str, int], bool],
) -> Tuple[Dict[str, Any], List[Tuple[int, Dict[str, Any]]]]:
    """Explanation (always) -> repair eligibility check -> up to
    min(max_rounds, 2) repair rounds for one i2 record.

    Never raises for a per-record component failure: explanation failures
    are already captured by explain_record()/explain_one()'s own bounded
    retry+status contract, and a repair-round exception (PyPI unreachable,
    clone failure, unexpected error) is caught here and recorded as
    "component_error", stopping further rounds for *this* record only -
    the caller's own per-record try/except is the last-resort net for
    anything this function itself doesn't anticipate.

    Returns (diagnostics, pending_rows): pending_rows is a list of
    (round_number, repair_attempts_row) tuples the caller inserts via
    result_logger.insert_row() - kept out of this function so it stays
    testable without a real database connection."""
    notebook_execution_id = record.get("notebook_execution_id")
    diagnostics: Dict[str, Any] = {
        "index": original_index,
        "notebook_execution_id": notebook_execution_id,
    }
    pending_rows: List[Tuple[int, Dict[str, Any]]] = []

    explanation = explain_record(
        record, explainer_config, explainer_template, explainer_schema_path, run_id, original_index
    )
    diagnostics["explanation_status"] = explanation["explanation_result"]["status"]
    diagnostics["explanation"] = explanation

    decision, exclusion_reason = rag_repair_agent.check_eligibility(record)
    diagnostics["repair_eligibility"] = {"decision": decision, "exclusion_reason": exclusion_reason}

    if decision != "usable":
        # Never call RAGRepairAgent/FixApplicator for an excluded/invalid
        # record (build_excluded_repair_stub reuses check_eligibility() and
        # _base_result(), it does not call run_repair_agent()). One
        # abstained row (action "none", outcome null) is still logged, per
        # the pre-i7 architecture's own contract (docs/architecture-note.md
        # §7.3): LLMExplainer's output reaches ResultLogger for every row,
        # independent of repair eligibility.
        if not already_logged(notebook_execution_id, run_id, 1):
            i4_stub = build_excluded_repair_stub(record, run_id)
            row = result_logger.build_repair_attempt_row(i4_stub, record, explanation, None, 1)
            pending_rows.append((1, row))
            diagnostics["rounds"] = [{"round": 1, "status": "excluded", "i4_result": i4_stub}]
        else:
            diagnostics["rounds"] = [{"round": 1, "status": "skipped_already_logged"}]
        return diagnostics, pending_rows

    rounds: List[Dict[str, Any]] = []
    active_record = record
    prior_fix_argvs: List[List[str]] = []
    round_number = 1
    effective_max_rounds = min(max_rounds, MAX_ROUNDS_HARD_CAP)

    while round_number <= effective_max_rounds:
        if already_logged(notebook_execution_id, run_id, round_number):
            rounds.append({"round": round_number, "status": "skipped_already_logged"})
            break

        try:
            i4_result, i5_result = run_repair_round(
                active_record,
                run_id,
                repair_config,
                fix_config,
                i2_index,
                repository_metadata_lookup,
                runner,
                work_dir_base,
                prior_fix_argvs=(prior_fix_argvs or None),
            )
        except Exception as e:
            rounds.append(
                {
                    "round": round_number,
                    "status": "component_error",
                    "error": "{}: {}".format(type(e).__name__, e),
                }
            )
            break

        i3_for_row = explanation if round_number == 1 else None
        # Only pass the i5 record when FixApplicator actually executed
        # (status "completed": fixed/still_failing/apply_error). A "skipped"
        # decision (abstained/failed i4, or action "none") is not a real
        # attempt - build_repair_attempt_row falls back to i4's own
        # final_action/run_id in that case, exactly as it already does when
        # no i5 record exists at all (docs/architecture-note.md §7.3).
        i5_for_row = i5_result if i5_result.get("status") == "completed" else None
        row = result_logger.build_repair_attempt_row(i4_result, active_record, i3_for_row, i5_for_row, round_number)
        pending_rows.append((round_number, row))

        round_entry: Dict[str, Any] = {
            "round": round_number,
            "status": "completed",
            "i4_result": i4_result,
            "i5_result": i5_result,
        }
        rounds.append(round_entry)

        if round_number >= effective_max_rounds:
            break

        trigger = evaluate_round2_trigger(i5_result, record)
        round_entry["round2_trigger"] = trigger
        if not trigger["triggered"]:
            break

        if i5_result.get("argv"):
            prior_fix_argvs = prior_fix_argvs + [i5_result["argv"]]
        active_record = trigger["round2_record"]
        round_number += 1

    diagnostics["rounds"] = rounds
    return diagnostics, pending_rows


# --- shared repair_attempts SQLite connection --------------------------------

def open_repair_attempts_db(
    db_path: Path, timeout: float = DB_LOCK_TIMEOUT_SECONDS
) -> sqlite3.Connection:
    """Open (and, via result_logger.create_table(), ensure the schema of)
    the shared I6 repair_attempts SQLite database - reused as-is, no new
    schema. `create_table()`/`insert_row()` (scripts/result_logger.py) each
    commit immediately after their one statement, so no write transaction
    is ever held open across a round's real Ollama/PyPI/Docker work; the
    only genuine contention window is the brief moment another process is
    itself mid-write.

    `timeout` is passed straight to sqlite3.connect() (which sets the
    connection's busy handler) and is also set again explicitly via
    `PRAGMA busy_timeout` for the same effect, spelled out rather than left
    implicit. A connection contending with another writer waits up to
    `timeout` seconds rather than failing immediately; if the lock is still
    held after that, this raises a clear, actionable RuntimeError (chained
    from the original sqlite3.OperationalError) naming the database path -
    it never silently switches to a different database file, and never
    swallows a persistent lock as if nothing were wrong."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(str(db_path), timeout=timeout)
        conn.execute("PRAGMA busy_timeout = {}".format(int(timeout * 1000)))
        result_logger.create_table(conn)
    except sqlite3.OperationalError as e:
        raise RuntimeError(
            "repair_attempts database is busy/locked after waiting {:.0f}s ({}): "
            "another pipeline process may be writing to {} - wait for it to finish, "
            "or use a separate --database path for this run.".format(timeout, e, db_path)
        ) from e
    return conn


def _reset_repair_attempts_table(conn: sqlite3.Connection, db_path: Path) -> None:
    """--overwrite: drop and recreate repair_attempts. Wrapped the same way
    as open_repair_attempts_db() so a lock encountered here is just as
    clearly reported, never silently ignored."""
    try:
        conn.execute("DROP TABLE IF EXISTS repair_attempts")
        conn.commit()
        result_logger.create_table(conn)
    except sqlite3.OperationalError as e:
        raise RuntimeError(
            "repair_attempts database is busy/locked while applying --overwrite ({}): "
            "another pipeline process may be writing to {}.".format(e, db_path)
        ) from e


# --- CLI ----------------------------------------------------------------------

def load_configs(args: argparse.Namespace) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    explainer_config = run_llm_explainer.load_config(args.explainer_config)
    repair_config = load_rag_repair_config(args.repair_config)
    fix_config = fix_applicator.load_fix_applicator_config(args.fix_config)

    if args.model:
        explainer_config.setdefault("models", {})["primary"] = args.model
        # Provider-aware: writes into whichever provider sub-section the
        # loaded repair config actually declares (repair_agent.ollama by
        # default, repair_agent.kiste when repair_agent.provider: kiste),
        # so --model overrides the model an evaluation run actually uses
        # instead of silently landing in an unused "ollama" sub-key.
        repair_agent_config = repair_config.setdefault("repair_agent", {})
        repair_provider = repair_agent_config.get("provider", "ollama")
        repair_agent_config.setdefault(repair_provider, {})["model"] = args.model
    if args.prompt_strategy:
        explainer_config.setdefault("prompt", {})["strategy"] = args.prompt_strategy

    return explainer_config, repair_config, fix_config


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "PipelineOrchestrator (i7): run classification -> LLMExplainer -> "
            "repair eligibility -> RAGRepairAgent -> FixApplicator -> ResultLogger "
            "for a slice of the i2-classified dependency-error dataset."
        )
    )
    parser.add_argument("--i2", default=DEFAULT_I2_PATH, help="i2-classified dependency-error JSONL.")
    parser.add_argument(
        "--split",
        choices=["dev", "evaluation", "excluded", "all"],
        default="dev",
        help=(
            "Which i1 split to run over. Defaults to 'dev' so iterative/pilot use "
            "never touches the reserved 187-row evaluation split by accident; pass "
            "--split evaluation or --split all explicitly for the final evaluation run."
        ),
    )
    parser.add_argument("--start-index", type=int, default=0, help="0-based offset into the selected split.")
    parser.add_argument("--limit", type=int, default=1, help="Maximum number of records to process.")
    parser.add_argument(
        "--max-rounds",
        type=int,
        choices=[1, 2],
        default=2,
        help="Maximum repair rounds per record. Round 3 is never possible regardless of this value.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Override the model for LLMExplainer and RAGRepairAgent. Provider-aware: lands in "
            "repair_agent.ollama.model or repair_agent.kiste.model depending on the loaded "
            "--repair-config's own repair_agent.provider (default: ollama)."
        ),
    )
    parser.add_argument("--prompt-strategy", default=None, help="Override LLMExplainer's config prompt.strategy.")
    parser.add_argument(
        "--run-id",
        default=None,
        help="Shared orchestration-level run id used by every repair_attempts row this invocation writes. Default: i7-<UTC timestamp>.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_TRACE_DIR,
        help="Directory for this orchestrator's own per-record JSONL trace (one line per record).",
    )
    parser.add_argument("--database", default=DEFAULT_DB_PATH, help="repair_attempts SQLite path (I6 schema, reused as-is).")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Drop and recreate repair_attempts before this run, and never treat any prior row as already-logged.",
    )
    parser.add_argument("--explainer-config", default="config/llm_explainer.yaml")
    parser.add_argument("--repair-config", default="config/rag_repair.yaml")
    parser.add_argument("--fix-config", default=str(fix_applicator.DEFAULT_CONFIG_PATH))
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Base directory for FixApplicator's per-attempt work dirs (default: system temp dir).",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()

    if args.start_index < 0:
        raise SystemExit("--start-index must be >= 0")
    if args.limit is not None and args.limit < 0:
        raise SystemExit("--limit must be >= 0")

    run_id = args.run_id or make_run_id()

    explainer_config, repair_config, fix_config = load_configs(args)
    explainer_template_path = Path("prompts") / "{}.txt".format(explainer_config["prompt"]["template"])
    explainer_template = explainer_template_path.read_text(encoding="utf-8")
    explainer_schema_path = explainer_config["output"]["schema"]

    records = load_all_records(args.i2)
    selected = select_records(records, args.split, args.start_index, args.limit)

    i2_index = fix_applicator.load_i2_index(args.i2)
    repository_metadata_lookup = fix_applicator.default_repository_metadata_lookup(
        fix_config.get("upstream_docker_pipeline", {}).get("db_path")
    )
    runner = docker_runner.default_runner
    work_dir_base = Path(args.work_dir) if args.work_dir else None

    db_path = Path(args.database)
    conn = open_repair_attempts_db(db_path)

    try:
        if args.overwrite:
            _reset_repair_attempts_table(conn, db_path)

        def already_logged(notebook_execution_id: Any, check_run_id: str, round_number: int) -> bool:
            if args.overwrite:
                return False
            cursor = conn.execute(
                "SELECT 1 FROM repair_attempts WHERE notebook_execution_id = ? AND run_id = ? AND round = ? LIMIT 1",
                (notebook_execution_id, check_run_id, round_number),
            )
            return cursor.fetchone() is not None

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        trace_path = output_dir / "{}.jsonl".format(run_id)
        trace_mode = "w" if args.overwrite else "a"

        print(
            "[i7] run_id={} split={} start_index={} limit={} max_rounds={}".format(
                run_id, args.split, args.start_index, args.limit, args.max_rounds
            )
        )

        with trace_path.open(trace_mode, encoding="utf-8") as trace_out:
            for original_index, record in selected:
                notebook_execution_id = record.get("notebook_execution_id")
                try:
                    diagnostics, pending_rows = process_record(
                        record,
                        original_index,
                        run_id,
                        args.max_rounds,
                        explainer_config,
                        explainer_template,
                        explainer_schema_path,
                        repair_config,
                        fix_config,
                        i2_index,
                        repository_metadata_lookup,
                        runner,
                        work_dir_base,
                        already_logged,
                    )
                    for round_number, row in pending_rows:
                        row_id = result_logger.insert_row(conn, row)
                        for round_entry in diagnostics["rounds"]:
                            if round_entry.get("round") == round_number and "i4_result" in round_entry:
                                round_entry["repair_attempts_row_id"] = row_id
                except Exception as e:
                    diagnostics = {
                        "index": original_index,
                        "notebook_execution_id": notebook_execution_id,
                        "status": "orchestrator_error",
                        "error": "{}: {}".format(type(e).__name__, e),
                    }

                trace_out.write(json.dumps(diagnostics, ensure_ascii=False, default=str) + "\n")
                trace_out.flush()

                n_rounds = len(diagnostics.get("rounds", []))
                print(
                    "[i7] index={} notebook_execution_id={} repair_eligibility={} rounds_run={}".format(
                        original_index,
                        notebook_execution_id,
                        diagnostics.get("repair_eligibility", {}).get("decision"),
                        n_rounds,
                    )
                )
    finally:
        conn.close()

    print("[i7] done. trace: {} db: {}".format(trace_path, db_path))


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        print("ERROR: {}".format(e))
        raise SystemExit(1)
