#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jsonschema import Draft202012Validator


def load_schema(schema_path: str) -> Dict[str, Any]:
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_fenced_json(text: str) -> Optional[str]:
    """
    Extract JSON from a markdown code fence if present, even when the model
    adds text before or after the fence.
    """
    fence_start = text.find("```")
    if fence_start == -1:
        return None

    content_start = text.find("\n", fence_start)
    if content_start == -1:
        return None

    fence_end = text.find("```", content_start + 1)
    if fence_end == -1:
        return None

    return text[content_start + 1:fence_end].strip()


def extract_first_json_object(text: str) -> Optional[str]:
    """
    Extract the first balanced JSON object from text.

    This is defensive handling for model responses like:
    'Here is the JSON: { ... } Let me know...'

    It respects quoted strings so braces inside strings do not break parsing.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(text)):
        char = text[index]

        if escape:
            escape = False
            continue

        if char == "\\":
            escape = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]

    return None


def parse_model_response(raw_response: str) -> Dict[str, Any]:
    """
    Parse a model response that should contain one JSON object.

    Accepted defensively:
    - pure JSON object
    - markdown-fenced JSON
    - text containing one balanced JSON object

    Rejected:
    - non-JSON text
    - JSON arrays/strings/numbers
    """
    text = raw_response.strip()

    candidates = [
        text,
        extract_fenced_json(text),
        extract_first_json_object(text),
    ]

    last_error = None

    for candidate in candidates:
        if not candidate:
            continue

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as e:
            last_error = e
            continue

        if not isinstance(parsed, dict):
            raise ValueError("non_object_json: model response must be a JSON object")

        return parsed

    if last_error is not None:
        raise ValueError(f"invalid_json: {last_error}")

    raise ValueError("invalid_json: no JSON object found in model response")


def validate_explanation(
    explanation: Dict[str, Any],
    schema: Dict[str, Any]
) -> List[str]:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(explanation), key=lambda e: e.path)

    return [
        f"{'/'.join(map(str, error.path)) or '<root>'}: {error.message}"
        for error in errors
    ]


def parse_and_validate(
    raw_response: str,
    schema_path: str
) -> Tuple[bool, Optional[Dict[str, Any]], List[str]]:
    schema = load_schema(schema_path)

    try:
        explanation = parse_model_response(raw_response)
    except ValueError as e:
        return False, None, [str(e)]

    validation_errors = validate_explanation(explanation, schema)

    if validation_errors:
        return False, explanation, validation_errors

    return True, explanation, []


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate one LLM explanation response.")
    parser.add_argument("--schema", default="schemas/explanation.schema.json")
    parser.add_argument("--response-file", required=True)
    args = parser.parse_args()

    raw_response = Path(args.response_file).read_text(encoding="utf-8")
    valid, explanation, errors = parse_and_validate(raw_response, args.schema)

    if valid:
        print("VALID")
        print(json.dumps(explanation, indent=2, ensure_ascii=False))
    else:
        print("INVALID")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
