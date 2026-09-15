#!/usr/bin/env python3

"""RunEvaluation (i8): an evaluation-specific wrapper around the existing
I7 orchestrator (scripts/run_pipeline.py).

This script never reimplements classification, explanation, RAG proposal
generation, fix application, Round-2 triggering, or repair_attempts
logging - it only:

  1. builds and freezes an EvaluationManifest (scripts/evaluation_manifest.py)
  2. enforces that the requested split's actual record count matches the
     manifest's data-derived `expected_record_count` before running anything
  3. invokes scripts/run_pipeline.py as a subprocess with the frozen
     configuration (never imports and re-drives its internals directly -
     a subprocess boundary is the strongest guarantee against silently
     reimplementing any of its logic)
  4. detects an incomplete run (fewer trace lines than expected) after the
     subprocess exits
  5. refuses to resume under an existing run_id whose manifest disagrees
     with the current configuration on any frozen field

`--split evaluation` is accepted by argparse (so the wiring exists) but
requires an explicit `--i-understand-this-touches-the-reserved-split` flag
to actually run - this task only ever exercises `--split dev`.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import evaluation_manifest as em  # noqa: E402


# Single source of truth for both run_evaluation()'s keyword defaults and
# the CLI's argparse defaults, so the two can never silently drift apart.
# DEFAULT_REPOSITORY_METADATA_DB_PATH is the machine-independent default
# (correct under a native Linux/WSL interpreter); it is never a
# machine-specific absolute path - see docs/i8-evaluation-methodology.md
# "Exact-commit requirement" for why the final run instead passes
# --repository-metadata-db-path pointing at a local, non-UNC copy.
DEFAULT_FIX_CONFIG = "config/fix_applicator.yaml"
DEFAULT_REPOSITORY_METADATA_DB_PATH = "~/era/computational-reproducibility-pmc-docker/data/db/db.sqlite"

PipelineInvoker = Callable[[List[str], Path], subprocess.CompletedProcess]


class EvaluationRunError(Exception):
    """Raised for any condition that must stop an evaluation run before or
    after invoking the I7 pipeline: a record-count mismatch, a manifest
    drift on resume, or an incomplete pipeline run."""


def default_pipeline_invoker(argv: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=str(cwd), check=False)


def evaluation_run_dir(root: Path, run_id: str) -> Path:
    return root / "data" / "evaluation" / run_id


def build_pipeline_argv(
    *,
    python_executable: str,
    split: str,
    limit: int,
    max_rounds: int,
    run_id: str,
    database_path: str,
    output_dir: str,
    explainer_config: str,
    repair_config: str,
    fix_config: str,
    model: Optional[str] = None,
    prompt_strategy: Optional[str] = None,
    overwrite: bool = False,
) -> List[str]:
    """Pure argv construction for scripts/run_pipeline.py - fully testable
    without ever invoking a subprocess."""
    argv = [
        python_executable,
        "scripts/run_pipeline.py",
        "--split",
        split,
        "--start-index",
        "0",
        "--limit",
        str(limit),
        "--max-rounds",
        str(max_rounds),
        "--run-id",
        run_id,
        "--database",
        database_path,
        "--output-dir",
        output_dir,
        "--explainer-config",
        explainer_config,
        "--repair-config",
        repair_config,
        "--fix-config",
        fix_config,
    ]
    if model:
        argv += ["--model", model]
    if prompt_strategy:
        argv += ["--prompt-strategy", prompt_strategy]
    if overwrite:
        argv.append("--overwrite")
    return argv


def count_actual_records(i2_path: Path, split: str) -> int:
    return em.count_records_in_split(i2_path, split)


def load_existing_manifest(run_dir: Path) -> Optional[Dict[str, Any]]:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    return em.load_manifest(manifest_path)


def count_trace_lines(trace_path: Path) -> int:
    if not trace_path.is_file():
        return 0
    count = 0
    with trace_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def run_evaluation(
    *,
    split: str,
    run_id: str,
    max_rounds: int = 2,
    model: str = "gemma2:9b",
    prompt_strategy: str = "few_shot",
    explanation_prompt_version: str = "i3_prompt_v1",
    repair_prompt_version: str = "i4_prompt_v1",
    explainer_config: str = "config/llm_explainer.yaml",
    repair_config: str = "config/rag_repair.yaml",
    fix_config: str = DEFAULT_FIX_CONFIG,
    repository_metadata_db_path: Optional[str] = DEFAULT_REPOSITORY_METADATA_DB_PATH,
    i2_path: str = em.DEFAULT_I2_PATH,
    root: Optional[Path] = None,
    python_executable: Optional[str] = None,
    pipeline_invoker: PipelineInvoker = default_pipeline_invoker,
    overwrite: bool = False,
    allow_evaluation_split: bool = False,
) -> Dict[str, Any]:
    """Run one evaluation invocation end to end: build/verify the
    manifest, enforce the expected record count, invoke scripts/
    run_pipeline.py, then report completeness. Raises EvaluationRunError
    for any precondition failure or incomplete run - never partially
    proceeds past a failed check."""
    root = root or ROOT
    python_executable = python_executable or sys.executable

    if split == "evaluation" and not allow_evaluation_split:
        raise EvaluationRunError(
            "refusing to run --split evaluation: the reserved 187-record evaluation split "
            "requires the explicit allow_evaluation_split=True guard, which this task does not set."
        )

    run_dir = evaluation_run_dir(root, run_id)
    raw_dir = run_dir / "raw"
    database_path = str(raw_dir / "repair_attempts.sqlite")
    trace_output_dir = str(raw_dir / "pipeline-runs")

    manifest = em.build_manifest(
        run_id=run_id,
        split=split,
        max_rounds=max_rounds,
        model=model,
        prompt_strategy=prompt_strategy,
        explanation_prompt_version=explanation_prompt_version,
        repair_prompt_version=repair_prompt_version,
        database_path=database_path,
        output_dir=trace_output_dir,
        explainer_config_path=explainer_config,
        repair_config_path=repair_config,
        fix_config_path=fix_config,
        repository_metadata_db_path=repository_metadata_db_path,
        i2_path=i2_path,
        root=root,
    )

    existing_manifest = load_existing_manifest(run_dir)
    if existing_manifest is not None:
        em.verify_manifest_consistency(existing_manifest, manifest)

    expected_count = manifest["expected_record_count"]
    if expected_count <= 0:
        raise EvaluationRunError(f"expected_record_count for split={split!r} is {expected_count} - refusing to run.")

    em.write_manifest(manifest, run_dir / "manifest.json")

    argv = build_pipeline_argv(
        python_executable=python_executable,
        split=split,
        limit=expected_count,
        max_rounds=max_rounds,
        run_id=run_id,
        database_path=database_path,
        output_dir=trace_output_dir,
        explainer_config=explainer_config,
        repair_config=repair_config,
        fix_config=fix_config,
        model=model,
        prompt_strategy=prompt_strategy,
        overwrite=overwrite,
    )

    result = pipeline_invoker(argv, root)
    if result.returncode != 0:
        raise EvaluationRunError(f"scripts/run_pipeline.py exited with code {result.returncode} (argv={argv!r})")

    trace_path = raw_dir / "pipeline-runs" / f"{run_id}.jsonl"
    actual_count = count_trace_lines(trace_path)
    complete = actual_count == expected_count
    if not complete:
        raise EvaluationRunError(
            f"incomplete run: expected {expected_count} trace lines for split={split!r}, "
            f"found {actual_count} at {trace_path}. Re-run (without --overwrite) to resume."
        )

    return {
        "run_id": run_id,
        "split": split,
        "manifest_path": str(run_dir / "manifest.json"),
        "trace_path": str(trace_path),
        "database_path": database_path,
        "expected_record_count": expected_count,
        "actual_record_count": actual_count,
        "complete": complete,
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="I8 evaluation-specific wrapper around scripts/run_pipeline.py.")
    parser.add_argument("--split", choices=["dev", "evaluation"], default="dev")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-rounds", type=int, choices=[1, 2], default=2)
    parser.add_argument("--model", default="gemma2:9b")
    parser.add_argument("--prompt-strategy", default="few_shot")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--explainer-config",
        default="config/llm_explainer.yaml",
        help=(
            "Path to the LLMExplainer config to use (default: %(default)s). Pass a sibling "
            "config (e.g. config/llm_explainer.kiste.yaml) for a different provider/model "
            "without touching the frozen default - never edit config/llm_explainer.yaml itself, "
            "see docs/i8-pre-final-evaluation-freeze.md."
        ),
    )
    parser.add_argument(
        "--repair-config",
        default="config/rag_repair.yaml",
        help=(
            "Path to the RAGRepairAgent config to use (default: %(default)s). Pass a sibling "
            "config (e.g. config/rag_repair.kiste.yaml) for a different provider/model without "
            "touching the frozen default - never edit config/rag_repair.yaml itself, see "
            "docs/i8-pre-final-evaluation-freeze.md."
        ),
    )
    parser.add_argument(
        "--fix-config",
        default=DEFAULT_FIX_CONFIG,
        help=(
            "Path to the FixApplicator config to use (default: %(default)s). Pass "
            "config/fix_applicator.evaluation.local.yaml for the final evaluation run, "
            "once that machine-local file points at a validated local metadata DB copy."
        ),
    )
    parser.add_argument(
        "--repository-metadata-db-path",
        default=DEFAULT_REPOSITORY_METADATA_DB_PATH,
        help=(
            "Path to the upstream Docker pipeline's repository-metadata sqlite DB, recorded "
            "(with its SHA-256, when accessible) in the manifest (default: %(default)s). Pass "
            "a genuine local filesystem path (never a machine-specific path committed to source) "
            "for the final evaluation run - see docs/i8-evaluation-methodology.md."
        ),
    )
    parser.add_argument(
        "--i-understand-this-touches-the-reserved-split",
        dest="allow_evaluation_split",
        action="store_true",
        help="Required in addition to --split evaluation to actually run the reserved 187-record split.",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    try:
        result = run_evaluation(
            split=args.split,
            run_id=args.run_id,
            max_rounds=args.max_rounds,
            model=args.model,
            prompt_strategy=args.prompt_strategy,
            explainer_config=args.explainer_config,
            repair_config=args.repair_config,
            fix_config=args.fix_config,
            repository_metadata_db_path=args.repository_metadata_db_path,
            overwrite=args.overwrite,
            allow_evaluation_split=args.allow_evaluation_split,
        )
    except EvaluationRunError as e:
        print(f"ERROR: {e}")
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
