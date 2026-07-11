#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterator, Optional


NOT_AVAILABLE = "Not available"
PLACEHOLDER_RE = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


def iter_jsonl_records(path: str, limit: Optional[int] = None) -> Iterator[Dict[str, Any]]:
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if limit is not None and count >= limit:
                break
            if line.strip():
                yield json.loads(line)
                count += 1


def load_jsonl_record(path: str, index: int) -> Dict[str, Any]:
    for current_index, record in enumerate(iter_jsonl_records(path)):
        if current_index == index:
            return record
    raise IndexError("No record at index {}".format(index))


def format_value(value: Any) -> str:
    if value is None:
        return NOT_AVAILABLE

    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else NOT_AVAILABLE

    if isinstance(value, list):
        if not value:
            return NOT_AVAILABLE
        return json.dumps(value, ensure_ascii=False, indent=2)

    if isinstance(value, dict):
        if not value:
            return NOT_AVAILABLE
        return json.dumps(value, ensure_ascii=False, indent=2)

    return str(value)


def get_prompt_context(record: Dict[str, Any]) -> Dict[str, Any]:
    context = record.get("prompt_context")
    return context if isinstance(context, dict) else {}


def extract_legacy_traceback_hint(record: Dict[str, Any]) -> Any:
    hint = record.get("legacy_traceback_hint")

    if isinstance(hint, dict):
        return hint.get("raw_traceback")

    return hint


def build_template_values(record: Dict[str, Any]) -> Dict[str, str]:
    prompt_context = get_prompt_context(record)

    return {
        "notebook_execution_id": format_value(record.get("notebook_execution_id")),
        "error_type": format_value(record.get("error_type")),
        "error_message": format_value(record.get("error_message")),
        "original_subtype": format_value(record.get("original_subtype")),
        "refined_subtype": format_value(record.get("refined_subtype")),
        "classifier_confidence": format_value(record.get("confidence")),
        "root_cause_hint": format_value(record.get("root_cause_hint")),
        "failing_module": format_value(record.get("failing_module")),
        "context_status": format_value(record.get("context_status")),
        "error_cell_index": format_value(record.get("error_cell_index")),
        "failing_cell_source": format_value(prompt_context.get("failing_cell_source")),
        "import_cells": format_value(prompt_context.get("import_cells")),
        "surrounding_cells": format_value(prompt_context.get("surrounding_cells")),
        "dependency_files": format_value(prompt_context.get("dependency_files")),
        "legacy_traceback_hint": format_value(extract_legacy_traceback_hint(record)),
    }


def render_prompt(template: str, values: Dict[str, str]) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError("Unknown template placeholder: {}".format(key))
        return values[key]

    return PLACEHOLDER_RE.sub(replace, template)


def render_record_prompt(record: Dict[str, Any], template: str) -> str:
    values = build_template_values(record)
    return render_prompt(template, values)


def iter_rendered_prompts(
    input_path: str,
    template_path: str,
    limit: Optional[int] = None
) -> Iterator[Dict[str, Any]]:
    template = Path(template_path).read_text(encoding="utf-8")
    count = 0

    with open(input_path, "r", encoding="utf-8") as f:
        for line_index, line in enumerate(f):
            if limit is not None and count >= limit:
                break

            if not line.strip():
                continue

            record = None

            try:
                record = json.loads(line)
            except Exception as e:
                yield {
                    "index": line_index,
                    "record": None,
                    "prompt": None,
                    "error": "{}: {}".format(type(e).__name__, e),
                }
                count += 1
                continue

            try:
                prompt = render_record_prompt(record, template)
                yield {
                    "index": line_index,
                    "record": record,
                    "prompt": prompt,
                    "error": None,
                }
            except Exception as e:
                yield {
                    "index": line_index,
                    "record": record,
                    "prompt": None,
                    "error": "{}: {}".format(type(e).__name__, e),
                }

            count += 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render an LLM explanation prompt from one i2 JSONL record."
    )
    parser.add_argument(
        "--input",
        default="data/context-classification/dependency_error_contexts.jsonl"
    )
    parser.add_argument(
        "--template",
        default="prompts/dependency_explanation_v1.txt"
    )
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--output")
    args = parser.parse_args()

    try:
        record = load_jsonl_record(args.input, args.index)
        template = Path(args.template).read_text(encoding="utf-8")
        prompt = render_record_prompt(record, template)

        if args.output:
            Path(args.output).write_text(prompt, encoding="utf-8")
        else:
            print(prompt)

    except (FileNotFoundError, IndexError, KeyError, json.JSONDecodeError) as e:
        print("ERROR: {}".format(e))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
