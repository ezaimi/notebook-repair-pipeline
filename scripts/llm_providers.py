#!/usr/bin/env python3

"""Shared OpenAI-compatible ("kiste") LLM transport for the model-
sensitivity supplementary experiment (Qwen3.6-35B-A3B-MLX-8bit via TU
Chemnitz Kiste).

This is the ONLY place in the repository that reads KISTE_API_TOKEN. It is
deliberately one shared module rather than duplicated per call site (unlike
call_ollama, which is intentionally duplicated between
scripts/run_llm_explainer.py and scripts/rag_repair_agent.py) so there is a
single, auditable function to verify never logs, prints, returns, or
persists the token. call_kiste() never reads .env itself - it only reads
the already-exported process environment variable, exactly like every
other secret in this project (see scripts/evaluation_manifest.py's own
"never reads .env" contract).

call_kiste() returns the same (raw_response: str, metadata: dict) shape
scripts/run_llm_explainer.py's and scripts/rag_repair_agent.py's own
call_ollama() already return, with metadata using the same
prompt_eval_count/eval_count keys Ollama's response already uses - so
neither caller's existing tokens_input/tokens_output extraction needs to
change. It never touches prompts, schemas, or validation: the already-
rendered prompt string is sent unmodified as a single user message.
"""

import os
from typing import Any, Dict, Optional, Tuple


class KisteConfigurationError(Exception):
    """Raised for any precondition failure before or during a Kiste call
    (missing token, missing openai package, missing base_url). Never
    includes the token value - callers must not attempt to recover it from
    this exception's message."""


# One cached client per base_url per process. The client is not a fixture
# to a network resource in a way that needs pooled/reused connections
# across a whole 187-record run; caching it just avoids rebuilding the
# client object once per record.
_CLIENT_CACHE: Dict[str, Any] = {}


def _get_api_token() -> str:
    token = os.environ.get("KISTE_API_TOKEN")
    if not token:
        raise KisteConfigurationError(
            "KISTE_API_TOKEN is not set in the environment. Export it before "
            "running a provider: kiste evaluation; this module never reads "
            ".env itself, so sourcing a .env file (if you use one) is the "
            "caller's responsibility, not this module's."
        )
    return token


def _get_client(base_url: str):
    if base_url in _CLIENT_CACHE:
        return _CLIENT_CACHE[base_url]

    # Token is resolved before the (optional) openai import so a missing
    # KISTE_API_TOKEN is always reported as exactly that, never masked by
    # an unrelated "openai package missing" error if both happen to be
    # true at once.
    api_key = _get_api_token()

    try:
        from openai import OpenAI
    except ImportError as e:
        raise KisteConfigurationError(
            "the 'openai' package is required for provider: kiste (pip install openai)"
        ) from e

    client = OpenAI(api_key=api_key, base_url=base_url)
    _CLIENT_CACHE[base_url] = client
    return client


def call_kiste(
    model: str,
    prompt: str,
    generation_config: Dict[str, Any],
    kiste_config: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """Send one already-rendered prompt string as a single user message to
    an OpenAI-compatible chat.completions endpoint. `generation_config` is
    the same provider-agnostic shape (temperature/top_p/max_tokens/
    timeout_seconds) both call_ollama() implementations already read from;
    `kiste_config` supplies only transport-specific settings (base_url).

    Returns (content, metadata). `content` is choices[0].message.content
    only - a model's separate reasoning/thinking output (surfaced by some
    OpenAI-compatible servers as choices[0].message.reasoning_content) is
    never included in the returned text, matching call_ollama()'s own
    "one response string" contract; its presence/length is still reported
    in `metadata` for diagnostic purposes; callers already ignore unknown
    metadata keys (call_ollama()'s real Ollama metadata dict carries many
    keys explain_one()/run_repair_agent() never read either)."""
    base_url = kiste_config.get("base_url")
    if not base_url:
        raise KisteConfigurationError("kiste_config['base_url'] is required for provider: kiste")

    client = _get_client(base_url)

    messages = [{"role": "user", "content": prompt}]
    timeout = generation_config.get("timeout_seconds", 120)

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=generation_config.get("temperature", 0.1),
        top_p=generation_config.get("top_p", 0.9),
        max_tokens=generation_config.get("max_tokens", 700),
        timeout=timeout,
    )

    choice = response.choices[0]
    content = getattr(choice.message, "content", None) or ""
    reasoning_content: Optional[str] = getattr(choice.message, "reasoning_content", None)
    finish_reason = getattr(choice, "finish_reason", None)

    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None) if usage is not None else None
    completion_tokens = getattr(usage, "completion_tokens", None) if usage is not None else None

    metadata: Dict[str, Any] = {
        "prompt_eval_count": prompt_tokens,
        "eval_count": completion_tokens,
        "finish_reason": finish_reason,
        "reasoning_content_present": bool(reasoning_content),
        "reasoning_content_chars": len(reasoning_content) if reasoning_content else 0,
        "provider": "kiste",
        "model": model,
    }

    return content, metadata
