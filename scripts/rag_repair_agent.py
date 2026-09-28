#!/usr/bin/env python3

import argparse
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import llm_providers
from pypi_retriever import configure_pypi_client, load_package_mapping, load_rag_repair_config, retrieve
from render_repair_prompt import render_repair_prompt
from repair_proposal_validator import is_safe_token, parse_and_validate_schema, validate_grounding


SUPPORTED_SUBTYPES = {"missing_package", "wrong_version"}

# Deterministic extraction only - the LLM is never used to pull module_path
# and symbol out of an error message. Matches the dataset's exact wording,
# including the trailing file-path parenthetical every real row carries,
# e.g. "cannot import name 'cumtrapz' from 'scipy.integrate'
# (/tmp/.local/lib/python3.10/site-packages/scipy/integrate/__init__.py)".
CANNOT_IMPORT_NAME_RE = re.compile(
    r"cannot import name ['\"]([^'\"]+)['\"] from ['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)

# Any of these retrieve() statuses (or an empty candidate_versions list, even
# under a "resolved"-looking status) means there is nothing grounded to
# propose from - abstain without ever calling the LLM.
RETRIEVAL_STATUSES_REQUIRING_ABSTENTION = {
    "mapping_unknown",
    "configuration_error",
    "package_not_found",
    "network_error",
    "frozen_cache_miss",
    "invalid_response",
    "no_compatible_release",
    "standard_library",
    "local_import_path",
    "classification_uncertain",
    "import_not_provided",
    "import_evidence_unavailable",
    "date_evidence_unavailable",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- 1. repair-eligibility gate ----------------------------------------------

def check_eligibility(record: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """Return (decision, exclusion_reason).

    decision is "usable", "excluded", or "invalid" - "invalid" covers a
    missing or unrecognized scope_status and fails safe (never assumes
    eligibility just because scope_status isn't literally "excluded").
    `split` (dev/evaluation) never affects this decision - it is evaluation
    metadata only, per docs/architecture-note.md §7.1.
    """
    scope_status = record.get("scope_status")

    if scope_status == "usable":
        return "usable", None

    if scope_status == "excluded":
        return "excluded", record.get("exclusion_reason")

    return "invalid", f"missing or unrecognized scope_status: {scope_status!r}"


# --- 2. deterministic signature extraction (wrong_version only) -------------

def extract_wrong_version_signature(error_message: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Deterministically parse "cannot import name 'X' from 'Y'" into
    (module_path, symbol). Returns (None, None) if the message doesn't
    match this shape - callers must treat that as extraction failure, never
    fall back to guessing or asking the LLM."""
    if not error_message:
        return None, None

    match = CANNOT_IMPORT_NAME_RE.search(error_message)
    if not match:
        return None, None

    symbol, module_path = match.group(1), match.group(2)
    return module_path, symbol


# --- 3. Ollama call -----------------------------------------------------------
# Deliberately not imported from scripts/run_llm_explainer.py: same shape,
# independent function, so the completed i3 explanation pipeline is never
# touched by this component.

def call_ollama(
    model: str,
    prompt: str,
    generation_config: Dict[str, Any],
    ollama_url: str,
) -> Tuple[str, Dict[str, Any]]:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": generation_config.get("temperature", 0.1),
            "top_p": generation_config.get("top_p", 0.9),
            "num_predict": generation_config.get("max_tokens", 700),
        },
    }

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        ollama_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    timeout = generation_config.get("timeout_seconds", 120)

    with urllib.request.urlopen(request, timeout=timeout) as response:
        response_data = json.loads(response.read().decode("utf-8"))

    return response_data.get("response", ""), response_data


# provider dispatch: routes to call_ollama() (default, unchanged) or the
# shared Kiste transport (scripts/llm_providers.py) for the model-
# sensitivity supplementary experiment. repair_agent_config["provider"] is
# absent from config/rag_repair.yaml, so `.get("provider", "ollama")`
# always resolves to "ollama" there - the branch below is then
# byte-identical to the direct call_ollama() call it replaces, and still
# resolves the module-level name `call_ollama` at call time, so tests that
# monkeypatch rag_repair_agent.call_ollama continue to intercept it
# unchanged.
def call_llm(
    model: str,
    prompt: str,
    generation_config: Dict[str, Any],
    repair_agent_config: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    provider = repair_agent_config.get("provider", "ollama")
    if provider == "ollama":
        return call_ollama(
            model=model,
            prompt=prompt,
            generation_config=generation_config,
            ollama_url=repair_agent_config.get("ollama", {}).get("url"),
        )
    if provider == "kiste":
        return llm_providers.call_kiste(
            model=model,
            prompt=prompt,
            generation_config=generation_config,
            kiste_config=repair_agent_config.get("kiste", {}),
        )
    raise ValueError(f"unknown provider: {provider!r}")


# Bounds how much of the model's own previous (invalid) response is echoed
# back into the retry prompt. A malformed response can itself be very long
# (e.g. the model hallucinating a list of hundreds of filenames instead of
# a proposal - see docs/rag-design.md and the i7 real-pilot report); echoing
# it back verbatim only re-exposes the retry attempt to the same noise that
# produced the invalid response in the first place, rather than clearly
# steering it toward the required shape.
MAX_RETRY_ECHO_CHARS = 500


def build_retry_prompt(original_prompt: str, invalid_response: str, errors: List[str]) -> str:
    truncated_response = invalid_response
    if len(truncated_response) > MAX_RETRY_ECHO_CHARS:
        truncated_response = truncated_response[:MAX_RETRY_ECHO_CHARS] + " ...[truncated]"

    return """The previous response was invalid.

Validation errors:
{errors}

Previous response (truncated for brevity):
{invalid_response}

Return ONLY the corrected repair JSON object, with exactly this structure
and no other fields, no markdown, and no extra text:
{{"action": "install | pin_version | none", "install_name": "... or null", "version": "... or null", "rationale": "..."}}

Do not invent a distribution name or version that is not shown in the
original input record below - if nothing in that record supports a safe
repair, return action "none" instead.

Original prompt:
{original_prompt}
""".format(
        errors="\n".join("- " + error for error in errors),
        invalid_response=truncated_response,
        original_prompt=original_prompt,
    )


def classify_validation_error(errors: List[str]) -> str:
    if errors and errors[0].startswith("invalid_json"):
        return "invalid_json"
    return "schema_validation_error"


def should_retry(category: str, attempt: int, max_retries: int, retry_on: List[str]) -> bool:
    return attempt < max_retries and category in retry_on


# --- 4. deterministic argv construction --------------------------------------

def build_argv(action: str, install_name: Optional[str], version: Optional[str]) -> Optional[List[str]]:
    """Construct pip's argument list only from fields that already passed
    grounding validation. Returns a list, never a shell string; this
    function does not invoke a shell and never executes anything itself.
    `action: "none"` always yields `None`."""
    if action == "install":
        return ["python", "-m", "pip", "install", install_name]
    if action == "pin_version":
        return ["python", "-m", "pip", "install", f"{install_name}=={version}"]
    return None


def build_command_display(argv: Optional[List[str]]) -> Optional[str]:
    """A human-readable, non-executable string for logs only, derived
    purely from the already-validated argv - never used to run anything."""
    if argv is None:
        return None
    return " ".join(argv)


# --- result assembly ----------------------------------------------------------

def _base_result(record: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "created_at": utc_now(),
        "notebook_execution_id": record.get("notebook_execution_id"),
        "input": {
            "failing_module": record.get("failing_module"),
            "error_type": record.get("error_type"),
            "error_message": record.get("error_message"),
            "original_subtype": record.get("original_subtype"),
            "refined_subtype": record.get("refined_subtype"),
            "scope_status": record.get("scope_status"),
            "exclusion_reason": record.get("exclusion_reason"),
            "split": record.get("split"),
            "root_cause_hint": record.get("root_cause_hint"),
            "context_status": record.get("context_status"),
        },
        "eligibility": None,
        "extracted_signature": None,
        "retrieval_result": None,
        "declared_constraint": None,
        "llm": None,
        "mapping_proposal": None,
        "mapping_raw_response": None,
        "mapping_schema_validation": None,
        "mapping_verification": None,
        "decision_source": None,
        "raw_response": None,
        "proposal": None,
        "schema_validation": None,
        "grounding_validation": None,
        "final_action": "none",
        "final_install_name": None,
        "final_version": None,
        "final_rationale": None,
        "argv": None,
        "command": None,
        "attempts": 0,
        "errors": [],
        "status": "abstained",
    }


def _provider_settings(config: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    repair_agent_config = config.get("repair_agent", {})
    provider = repair_agent_config.get("provider", "ollama")
    provider_config = (
        repair_agent_config.get("ollama", {})
        if provider == "ollama"
        else repair_agent_config.get("kiste", {})
    )
    return repair_agent_config, provider_config


def _set_deterministic_result(
    result: Dict[str, Any],
    action: str,
    install_name: str,
    version: Optional[str],
    rationale: str,
    decision_source: str,
) -> Dict[str, Any]:
    argv = build_argv(action, install_name, version)
    result["proposal"] = {
        "action": action,
        "install_name": install_name,
        "version": version,
        "rationale": rationale,
    }
    result["schema_validation"] = {"valid": True, "errors": []}
    result["grounding_validation"] = {"valid": True, "errors": []}
    result["final_action"] = action
    result["final_install_name"] = install_name
    result["final_version"] = version
    result["final_rationale"] = rationale
    result["argv"] = argv
    result["command"] = build_command_display(argv)
    result["decision_source"] = decision_source
    result["status"] = "success"
    return result


def _render_distribution_mapping_prompt(
    record: Dict[str, Any],
    retrieval_result: Dict[str, Any],
    declared_constraint: Optional[Dict[str, Any]],
) -> str:
    from render_repair_prompt import format_declared_constraint, format_value, render_prompt

    template = Path("prompts/distribution_mapping_v2.txt").read_text(encoding="utf-8")
    attempts = (retrieval_result.get("resolver") or {}).get("deterministic_attempts", [])
    return render_prompt(template, {
        "error_message": format_value(record.get("error_message")),
        "failing_module": format_value(record.get("failing_module")),
        "deterministic_attempts": json.dumps(attempts, sort_keys=True),
        "declared_constraint": format_declared_constraint(declared_constraint),
    })


def _request_distribution_suggestion(
    record: Dict[str, Any],
    retrieval_result: Dict[str, Any],
    declared_constraint: Optional[Dict[str, Any]],
    repair_agent_config: Dict[str, Any],
    provider_config: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Ask the LLM for one name only; no repair action is accepted here."""
    prompt = _render_distribution_mapping_prompt(record, retrieval_result, declared_constraint)
    schema_path = "schemas/distribution_suggestion.schema.json"
    audit: Dict[str, Any] = {
        "role": "distribution_proposal",
        "model": provider_config.get("model"),
        "prompt_template": "distribution_mapping_v2",
        "raw_response": None,
        "schema_validation": None,
        "errors": [],
    }
    try:
        raw_response, _ = call_llm(
            model=provider_config.get("model"),
            prompt=prompt,
            generation_config=provider_config,
            repair_agent_config=repair_agent_config,
        )
        audit["raw_response"] = raw_response
        valid, proposal, errors = parse_and_validate_schema(raw_response, schema_path)
        audit["schema_validation"] = {"valid": valid, "errors": errors}
        if not valid:
            audit["errors"] = errors
            return None, audit
        suggestion = proposal.get("suggested_distribution")
        if suggestion is None:
            audit["errors"] = ["model abstained from suggesting a distribution"]
            return None, audit
        if not is_safe_token(suggestion):
            audit["errors"] = ["suggested_distribution failed safe-token validation"]
            return None, audit
        return proposal, audit
    except (TimeoutError, socket.timeout) as exc:
        audit["errors"] = [f"timeout: {exc}"]
        return None, audit
    except urllib.error.URLError as exc:
        audit["errors"] = [f"model_unavailable: {exc}"]
        return None, audit
    except Exception as exc:  # noqa: BLE001 - this path must fail closed
        audit["errors"] = [f"runtime_error: {type(exc).__name__}: {exc}"]
        return None, audit


def run_repair_agent(
    record: Dict[str, Any],
    config: Dict[str, Any],
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Process one enriched dependency-error record end to end.

    eligibility gate -> deterministic signature extraction ->
    pypi_retriever.retrieve() -> repair prompt -> local Ollama LLM -> strict
    JSON-schema validation -> deterministic grounding validation ->
    deterministic argv construction. Never runs pip, never executes argv,
    never touches a notebook or a Docker container - FixApplicator (not
    this component) is responsible for that, later. One call always
    produces exactly one result dict, representing one input record and one
    final decision, however many internal LLM attempts it took.
    """
    configure_pypi_client(config)
    run_id = run_id or "i4-{}".format(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    result = _base_result(record, run_id)
    repair_agent_config, provider_config = _provider_settings(config)

    # --- eligibility gate: zero retrieval/LLM calls unless "usable" ---
    decision, exclusion_reason = check_eligibility(record)
    result["eligibility"] = {
        "decision": decision,
        "scope_status": record.get("scope_status"),
        "exclusion_reason": exclusion_reason,
    }

    if decision != "usable":
        result["errors"].append(f"not repair-eligible: {decision} ({exclusion_reason})")
        result["status"] = "abstained"
        return result

    subtype = record.get("refined_subtype")
    if subtype not in SUPPORTED_SUBTYPES:
        result["errors"].append(f"unsupported subtype for repair: {subtype!r}")
        result["status"] = "abstained"
        return result

    # --- deterministic signature extraction ---
    module_path: Optional[str] = None
    symbol: Optional[str] = None

    if subtype == "wrong_version":
        module_path, symbol = extract_wrong_version_signature(record.get("error_message"))
        result["extracted_signature"] = {
            "subtype": subtype,
            "module_path": module_path,
            "symbol": symbol,
            "status": "ok" if (module_path and symbol) else "failed",
        }
        if not module_path or not symbol:
            result["errors"].append(
                "could not deterministically extract module_path/symbol from error_message"
            )
            result["status"] = "abstained"
            return result
        import_name = record.get("failing_module")
    else:
        result["extracted_signature"] = {
            "subtype": subtype, "module_path": None, "symbol": None, "status": "not_applicable",
        }
        import_name = record.get("failing_module")
        if not import_name:
            result["errors"].append("record has no failing_module for missing_package")
            result["status"] = "abstained"
            return result

    # --- retrieval: production calls always pass python_version=None, so
    # retrieve() loads the authoritative constant from config/rag_repair.yaml
    # itself rather than this caller re-deriving or hardcoding it ---
    resolver_config = config.get("resolver", {})
    retrieval_result = retrieve(
        import_name,
        python_version=None,
        subtype=subtype,
        module_path=module_path,
        symbol=symbol,
        resolver_config=resolver_config,
        repository_date=record.get("repository_commit_date"),
        record=record,
    )
    result["retrieval_result"] = retrieval_result

    # Only after special, identity/PEP-503, and the frozen public mapping
    # have all failed may the LLM propose a distribution name.  The LLM's
    # answer is then routed back through the identical PyPI + wheel check;
    # no LLM text is ever itself mapping evidence.
    decision_policy = repair_agent_config.get("decision_policy", {})
    unresolved_import_policy = decision_policy.get(
        "unresolved_import", "ollama_propose_then_verify"
    )

    if (
        resolver_config.get("mode") == "v2"
        and retrieval_result.get("status") == "mapping_unknown"
        and unresolved_import_policy == "ollama_propose_then_verify"
    ):
        mapping_proposal, mapping_audit = _request_distribution_suggestion(
            record,
            retrieval_result,
            declared_constraint=None,
            repair_agent_config=repair_agent_config,
            provider_config=provider_config,
        )
        result["mapping_proposal"] = mapping_proposal
        result["mapping_raw_response"] = mapping_audit.get("raw_response")
        result["mapping_schema_validation"] = mapping_audit.get("schema_validation")
        result["llm"] = {
            "model": provider_config.get("model"),
            "role": "distribution_proposal",
            "prompt_template": mapping_audit.get("prompt_template"),
            "errors": mapping_audit.get("errors"),
        }
        if mapping_proposal is not None:
            candidate_config = dict(resolver_config)
            candidate_config["_v2_resolution_candidate"] = {
                "distribution_name": mapping_proposal["suggested_distribution"],
                "mapping_method": "llm_proposed_then_verified",
            }
            verification = retrieve(
                import_name,
                python_version=None,
                subtype=subtype,
                module_path=module_path,
                symbol=symbol,
                resolver_config=candidate_config,
                repository_date=record.get("repository_commit_date"),
                record=record,
            )
            result["mapping_verification"] = verification
            if verification.get("status") == "resolved":
                retrieval_result = verification
                result["retrieval_result"] = retrieval_result
            else:
                result["errors"].append(
                    "LLM distribution suggestion did not pass PyPI/wheel verification "
                    f"(status: {verification.get('status')})"
                )

    if (
        resolver_config.get("mode") == "v2"
        and retrieval_result.get("status") == "mapping_unknown"
        and unresolved_import_policy == "deterministic_abstain"
    ):
        result["decision_source"] = "deterministic_unresolved_import_abstention"
        result["errors"].append(
            "no deterministic import-to-distribution mapping passed verification; "
            "the deterministic policy abstains"
        )

    if (
        retrieval_result["status"] in RETRIEVAL_STATUSES_REQUIRING_ABSTENTION
        or not retrieval_result.get("candidate_versions")
    ):
        result["errors"].append(
            f"retrieval produced no grounded candidates (status: {retrieval_result['status']})"
        )
        result["status"] = "abstained"
        return result

    if subtype == "wrong_version" and resolver_config.get("mode") != "v2":
        compatibility_evidence = retrieval_result.get("compatibility_evidence") or {}
        if compatibility_evidence.get("status") != "resolved":
            result["errors"].append(
                "compatibility evidence is missing or invalid; abstaining without an LLM call "
                f"(status: {compatibility_evidence.get('status')!r})"
            )
            result["status"] = "abstained"
            return result

    # V2 records repository declarations after (not before) the resolver has
    # verified the distribution. A requirements file is context only: it
    # cannot create a mapping or replace PyPI/wheel evidence.
    declared_constraint = None
    if resolver_config.get("mode") == "v2":
        from requirements_evidence import assess_declared_constraint

        dependency_files = record.get("dependency_file_metadata")
        if not isinstance(dependency_files, list):
            prompt_context = record.get("prompt_context", {})
            dependency_files = (
                prompt_context.get("dependency_files", []) if isinstance(prompt_context, dict) else []
            )
        mapping_path = resolver_config.get("package_mapping_path")
        declared_constraint = assess_declared_constraint(
            dependency_files,
            retrieval_result,
            import_distribution_mapping=load_package_mapping(mapping_path),
        )
        result["declared_constraint"] = declared_constraint

    # A verified missing distribution has exactly one safe pip action.
    # There is no value in making a language model repeat that fact.
    if resolver_config.get("mode") == "v2" and subtype == "missing_package":
        return _set_deterministic_result(
            result,
            "install",
            retrieval_result["distribution_name"],
            None,
            "The distribution and requested import were verified from PyPI wheel metadata.",
            "deterministic_verified_install",
        )

    # One date-anchored version candidate likewise leaves no choice for the
    # model.  Multiple candidates are intentionally left to the bounded LLM
    # selection experiment below.
    if (
        resolver_config.get("mode") == "v2"
        and subtype == "wrong_version"
        and len(retrieval_result.get("candidate_versions") or []) == 1
    ):
        only_version = retrieval_result["candidate_versions"][0]["version"]
        return _set_deterministic_result(
            result,
            "pin_version",
            retrieval_result["distribution_name"],
            only_version,
            "The only verified version available by the recorded repository date was selected.",
            "deterministic_single_verified_version",
        )

    # The deterministic-policy ablation removes the LLM's bounded version
    # selection while preserving the same date-anchored, wheel-verified
    # candidate list.  retrieve() orders candidates newest first.
    if (
        resolver_config.get("mode") == "v2"
        and subtype == "wrong_version"
        and len(retrieval_result.get("candidate_versions") or []) > 1
        and decision_policy.get("wrong_version_multiple_candidates")
        == "deterministic_newest_verified_candidate"
    ):
        selected_version = retrieval_result["candidate_versions"][0]["version"]
        return _set_deterministic_result(
            result,
            "pin_version",
            retrieval_result["distribution_name"],
            selected_version,
            "The newest version in the date-anchored, wheel-verified candidate list was selected deterministically.",
            "deterministic_newest_verified_version",
        )

    # --- from here on, grounded evidence exists: an LLM call is justified ---
    # In V2 this branch is only the bounded choice among multiple verified
    # wrong-version candidates.  V1 retains its prior LLM behaviour.
    prompt_config = repair_agent_config.get("prompt", {})
    retry_config = repair_agent_config.get("retry", {})
    schema_path = repair_agent_config.get("output", {}).get(
        "schema", "schemas/repair_proposal.schema.json"
    )

    template_path = Path("prompts") / "{}.txt".format(prompt_config.get("template", "dependency_repair_v1"))
    template = template_path.read_text(encoding="utf-8")
    prompt = render_repair_prompt(
        record, retrieval_result, subtype, template, declared_constraint=declared_constraint
    )

    result["llm"] = {
        "model": provider_config.get("model"),
        "role": "verified_version_selection" if resolver_config.get("mode") == "v2" else "repair_proposal",
        "prompt_template": prompt_config.get("template"),
        "prompt_version": prompt_config.get("version"),
    }

    max_retries = int(retry_config.get("max_retries", 0))
    retry_on = retry_config.get("retry_on", [])

    current_prompt = prompt
    raw_response = ""
    errors: List[str] = []
    final_category = None
    actual_attempts = 0
    proposal: Optional[Dict[str, Any]] = None
    schema_valid = False
    grounding_errors: List[str] = []

    for attempt in range(max_retries + 1):
        actual_attempts = attempt + 1
        try:
            raw_response, _ = call_llm(
                model=provider_config.get("model"),
                prompt=current_prompt,
                generation_config=provider_config,
                repair_agent_config=repair_agent_config,
            )

            schema_valid, proposal, errors = parse_and_validate_schema(raw_response, schema_path)

            if not schema_valid:
                final_category = classify_validation_error(errors)
                if should_retry(final_category, attempt, max_retries, retry_on):
                    current_prompt = build_retry_prompt(prompt, raw_response, errors)
                    continue
                break

            grounding_errors = validate_grounding(proposal, retrieval_result, subtype)

            if grounding_errors:
                final_category = "grounding_validation_error"
                if should_retry(final_category, attempt, max_retries, retry_on):
                    current_prompt = build_retry_prompt(prompt, raw_response, grounding_errors)
                    continue
                break

            final_category = None
            break

        except (TimeoutError, socket.timeout) as e:
            final_category = "timeout"
            errors = [f"timeout: {e}"]
            if should_retry(final_category, attempt, max_retries, retry_on):
                time.sleep(1)
                continue
            break

        except urllib.error.URLError as e:
            final_category = "model_unavailable"
            errors = [f"model_unavailable: {e}"]
            if should_retry(final_category, attempt, max_retries, retry_on):
                time.sleep(1)
                continue
            break

        except Exception as e:
            final_category = "runtime_error"
            errors = [f"runtime_error: {type(e).__name__}: {e}"]
            break

    result["raw_response"] = raw_response
    result["proposal"] = proposal
    result["attempts"] = actual_attempts
    result["schema_validation"] = {
        "valid": schema_valid,
        "errors": [] if schema_valid else errors,
    }

    if not schema_valid:
        result["grounding_validation"] = {"valid": False, "errors": []}
        result["errors"] = errors
        result["status"] = "failed" if final_category in {"timeout", "model_unavailable", "runtime_error"} else "abstained"
        return result

    result["grounding_validation"] = {"valid": not grounding_errors, "errors": grounding_errors}

    if grounding_errors:
        result["errors"] = grounding_errors
        result["status"] = "abstained"
        return result

    action = proposal["action"]
    install_name = proposal["install_name"]
    version = proposal["version"]

    argv = build_argv(action, install_name, version)

    result["final_action"] = action
    result["final_install_name"] = install_name
    result["final_version"] = version
    result["final_rationale"] = proposal["rationale"]
    result["argv"] = argv
    result["command"] = build_command_display(argv)
    result["decision_source"] = (
        "llm_select_from_verified_versions"
        if resolver_config.get("mode") == "v2"
        else "llm_repair_proposal"
    )
    result["status"] = "success" if action != "none" else "abstained"

    return result


# --- CLI / batch runner -------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run RAGRepairAgent over i2-classified, repair-eligible dependency-error records."
    )
    parser.add_argument("--config", default="config/rag_repair.yaml")
    parser.add_argument("--input", default="data/context-classification/dependency_error_contexts.jsonl")
    parser.add_argument("--output")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    config = load_rag_repair_config(args.config)
    output_path = Path(
        args.output
        or config.get("repair_agent", {}).get("output", {}).get("path", "data/repair-proposals/repair_proposals.jsonl")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    run_id = "i4-{}".format(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    mode = "w" if args.overwrite else "a"
    processed = 0

    with output_path.open(mode, encoding="utf-8") as out, open(args.input, "r", encoding="utf-8") as f:
        for index, line in enumerate(f):
            if index < args.start_index:
                continue
            if args.limit is not None and processed >= args.limit:
                break
            if not line.strip():
                continue

            record = json.loads(line)
            result = run_repair_agent(record, config, run_id=run_id)
            result["index"] = index

            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            out.flush()

            print("[{}] index={} status={} action={}".format(
                utc_now(), index, result["status"], result["final_action"]
            ))

            processed += 1


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        print("ERROR: {}".format(e))
        raise SystemExit(1)
