#!/usr/bin/env python3

import json
import io
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from zipfile import BadZipFile, ZipFile

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version


DEFAULT_PACKAGE_MAPPING_PATH = Path(__file__).resolve().parent.parent / "config" / "package_mapping.yaml"
DEFAULT_PUBLIC_MAPPING_PATH = Path(__file__).resolve().parent.parent / "data" / "public-import-mapping" / "pipreqs-mapping.txt"
DEFAULT_RAG_REPAIR_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "rag_repair.yaml"

PYPI_SIMPLE_BASE = "https://pypi.org/simple"
PYPI_SIMPLE_ACCEPT_HEADER = "application/vnd.pypi.simple.v1+json"
USER_AGENT = "ma-thesis-rag-repair-agent/i4 (Python dependency-repair research prototype)"
DEFAULT_FETCH_TIMEOUT_SECONDS = 10.0
MAX_CANDIDATE_VERSIONS = 5

# PEP 503-normalized project names: lowercase alphanumerics joined by single
# hyphens. normalize_distribution_name() always produces this shape; this
# regex is a defensive check before any name is inserted into a URL.
_NORMALIZED_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def load_package_mapping(path: Optional[str] = None) -> Dict[str, str]:
    mapping_path = Path(path) if path else DEFAULT_PACKAGE_MAPPING_PATH
    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = yaml.safe_load(f)
    return mapping or {}


def load_public_import_mapping(path: Optional[str] = None) -> Dict[str, str]:
    """Load a frozen, attributable public import-to-distribution mapping.

    The pipreqs mapping is deliberately an *additional candidate source*,
    rather than a truth source.  Every value it supplies still has to pass
    the PyPI and wheel-import checks below.  Its source snapshot and hash are
    recorded in the evaluation manifest.
    """
    mapping_path = Path(path) if path else DEFAULT_PUBLIC_MAPPING_PATH
    mapping: Dict[str, str] = {}
    with open(mapping_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            import_name, distribution_name = line.split(":", 1)
            import_name, distribution_name = import_name.strip(), distribution_name.strip()
            if import_name and distribution_name:
                mapping[import_name] = distribution_name
    return mapping


_PACKAGE_MAPPING = load_package_mapping()


def load_rag_repair_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load config/rag_repair.yaml. python_version is a fixed, repo-wide
    constant (the Docker execution environment always runs Python 3.10 -
    see the file's own header comment and docs/rag-design.md §4) - it is
    never looked up per notebook. `path` lets tests point at a temporary
    file to exercise missing/malformed-configuration behavior."""
    config_path = Path(path) if path else DEFAULT_RAG_REPAIR_CONFIG_PATH
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config or {}


def validate_python_version_config(value: Any) -> Tuple[Optional[str], Optional[str]]:
    """Validate one runtime.python_version value from config/rag_repair.yaml.

    Returns (version_string, None) if valid, or (None, error_message) if the
    value is missing, not a string, or not a valid PEP 440 version. Never
    raises - callers use the error message to build a structured
    "configuration_error" retrieval result instead of crashing or silently
    falling back to some other version source (e.g. notebook metadata).
    """
    if not value or not isinstance(value, str):
        return None, "config/rag_repair.yaml: runtime.python_version is missing or not a string"

    try:
        Version(value)
    except InvalidVersion:
        return None, f"config/rag_repair.yaml: runtime.python_version {value!r} is not a valid PEP 440 version"

    return value, None


_RAG_REPAIR_CONFIG = load_rag_repair_config()
DEFAULT_PYTHON_VERSION, DEFAULT_PYTHON_VERSION_ERROR = validate_python_version_config(
    _RAG_REPAIR_CONFIG.get("runtime", {}).get("python_version")
)

_PYPI_RATE_LIMIT_CONFIG = _RAG_REPAIR_CONFIG.get("pypi_client", {}).get("rate_limit", {}) or {}
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = float(
    _PYPI_RATE_LIMIT_CONFIG.get("min_request_interval_seconds", 0.5)
)
DEFAULT_MAX_RETRIES_ON_429 = int(_PYPI_RATE_LIMIT_CONFIG.get("max_retries_on_429", 1))
DEFAULT_MAX_RETRY_AFTER_SECONDS = float(
    _PYPI_RATE_LIMIT_CONFIG.get("max_retry_after_seconds", 5.0)
)


def resolve_distribution_name(import_name: str) -> Optional[str]:
    return _PACKAGE_MAPPING.get(import_name)


def normalize_distribution_name(distribution_name: str) -> str:
    return re.sub(r"[-_.]+", "-", distribution_name).lower()


def resolve_v2_distribution_name(
    import_name: str,
    resolver_config: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve an import for V2 without guessing a package name.

    A small explicit table is used only for real import/distribution
    mismatches.  Every other top-level import is tried as its own PEP 503
    project name.  That is a candidate, not proof: the wheel check below
    must still show that the project actually provides the requested import.
    """
    resolver_config = resolver_config or {}
    mapping_path = resolver_config.get("package_mapping_path")
    mapping = load_package_mapping(mapping_path) if mapping_path else _PACKAGE_MAPPING
    root = (import_name or "").strip().split(".", 1)[0]
    if not root:
        return None, None
    if root in mapping:
        return mapping[root], "explicit_mismatch_mapping"
    return root, "identity_pep503"


def resolve_v2_distribution_candidates(
    import_name: str,
    resolver_config: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, str]]:
    """Return deterministic candidates in the documented V2 order.

    A duplicate is removed by PEP-503-normalised project name.  This avoids
    asking PyPI twice when, for example, the public mapping repeats an
    identity candidate under a different separator spelling.
    """
    resolver_config = resolver_config or {}
    mapping_path = resolver_config.get("package_mapping_path")
    special_mapping = load_package_mapping(mapping_path) if mapping_path else _PACKAGE_MAPPING
    root = (import_name or "").strip().split(".", 1)[0]
    if not root:
        return []

    candidates: List[Tuple[str, str]] = []
    if root in special_mapping:
        candidates.append((special_mapping[root], "explicit_mismatch_mapping"))
    candidates.append((root, "identity_pep503"))

    public_mapping_path = resolver_config.get("public_mapping_path")
    if public_mapping_path:
        try:
            public_mapping = load_public_import_mapping(public_mapping_path)
        except OSError:
            # The caller records a configuration error only when the public
            # source was explicitly configured but cannot be read.
            raise
        public_distribution = public_mapping.get(root)
        if public_distribution:
            candidates.append((public_distribution, "public_pipreqs_mapping"))

    unique: List[Tuple[str, str]] = []
    seen = set()
    for distribution_name, method in candidates:
        normalized = normalize_distribution_name(distribution_name)
        if normalized not in seen:
            seen.add(normalized)
            unique.append((distribution_name, method))
    return unique


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- PyPI Simple API client -------------------------------------------------

_pypi_response_cache: Dict[str, Tuple[str, Optional[Dict[str, Any]]]] = {}

# A final paired evaluation must use one frozen PyPI snapshot for both
# systems. The PLLM-style adapter stores official ``/pypi/<name>/json``
# payloads, whereas this component normally consumes the PEP 691 Simple API.
# These settings derive the latter's ``files`` view from the former without a
# network request. They remain disabled for ordinary development runs.
_frozen_pypi_cache: Optional[Dict[str, Any]] = None
_frozen_pypi_cache_path: Optional[Path] = None
_frozen_pypi_allow_network = True
_frozen_wheel_import_index: Optional[Dict[str, List[str]]] = None
_frozen_wheel_import_index_path: Optional[Path] = None


def configure_pypi_client(config: Dict[str, Any]) -> None:
    """Configure optional frozen-PyPI evidence for the current process."""
    global _frozen_pypi_cache, _frozen_pypi_cache_path, _frozen_pypi_allow_network
    global _frozen_wheel_import_index, _frozen_wheel_import_index_path

    client_config = config.get("pypi_client", {}) if isinstance(config, dict) else {}
    raw_path = client_config.get("frozen_cache_path")
    allow_network = bool(client_config.get("allow_network", True))
    if raw_path:
        requested_path = Path(raw_path)
        if (
            _frozen_pypi_cache is not None
            and _frozen_pypi_cache_path == requested_path
            and _frozen_pypi_allow_network == allow_network
        ):
            return
    elif _frozen_pypi_cache is None:
        _frozen_pypi_allow_network = allow_network
        return

    _frozen_pypi_allow_network = allow_network
    _frozen_pypi_cache = None
    _frozen_pypi_cache_path = None
    _frozen_wheel_import_index = None
    _frozen_wheel_import_index_path = None
    clear_pypi_cache()
    if not raw_path:
        return

    cache_path = Path(raw_path)
    if not cache_path.is_file():
        raise ValueError(f"frozen PyPI cache does not exist: {cache_path}")
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"frozen PyPI cache is unreadable: {cache_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"frozen PyPI cache must contain a JSON object: {cache_path}")
    _frozen_pypi_cache = payload
    _frozen_pypi_cache_path = cache_path

    resolver_config = config.get("resolver", {}) if isinstance(config, dict) else {}
    index_path_value = resolver_config.get("wheel_import_index_path")
    _frozen_wheel_import_index = None
    _frozen_wheel_import_index_path = None
    if index_path_value:
        index_path = Path(index_path_value)
        try:
            index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"frozen wheel-import index is unreadable: {index_path}: {exc}") from exc
        entries = index_payload.get("entries") if isinstance(index_payload, dict) else None
        if not isinstance(entries, dict):
            raise ValueError(f"frozen wheel-import index has no entries object: {index_path}")
        parsed_entries: Dict[str, List[str]] = {}
        for filename, top_levels in entries.items():
            if isinstance(filename, str) and isinstance(top_levels, list) and all(isinstance(v, str) for v in top_levels):
                parsed_entries[filename] = top_levels
        _frozen_wheel_import_index = parsed_entries
        _frozen_wheel_import_index_path = index_path


def _simple_files_from_raw_json_payload(payload: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Convert a cached PyPI JSON ``releases`` object to PEP-691-style files."""
    releases = payload.get("releases")
    if not isinstance(releases, dict):
        return None
    files: List[Dict[str, Any]] = []
    for release_files in releases.values():
        if not isinstance(release_files, list):
            return None
        for release_file in release_files:
            if not isinstance(release_file, dict):
                continue
            filename = release_file.get("filename")
            if not isinstance(filename, str):
                continue
            simple_file = {
                "filename": filename,
                "yanked": release_file.get("yanked", False),
                "requires-python": release_file.get("requires_python"),
            }
            # These two fields are absent from some early frozen snapshots.
            # Preserve them when present, but never fabricate them: V2's
            # artifact and date checks must abstain rather than infer proof.
            if isinstance(release_file.get("url"), str):
                simple_file["url"] = release_file["url"]
            if isinstance(release_file.get("upload_time_iso_8601"), str):
                simple_file["upload-time"] = release_file["upload_time_iso_8601"]
            files.append(simple_file)
    return files


def _frozen_pypi_result(distribution_name: str) -> Optional[Tuple[str, Optional[Dict[str, Any]]]]:
    """Return a frozen response when configured, otherwise ``None``."""
    if _frozen_pypi_cache is None:
        return None
    cached = _frozen_pypi_cache.get(distribution_name)
    if isinstance(cached, dict) and isinstance(cached.get("result"), dict):
        if cached["result"].get("status") == "not_found":
            return "package_not_found", None
        return "invalid_response", None
    if isinstance(cached, dict) and isinstance(cached.get("payload"), dict):
        files = _simple_files_from_raw_json_payload(cached["payload"])
        if files is not None:
            return "ok", {"files": files}
        return "invalid_response", None
    if not _frozen_pypi_allow_network:
        return "frozen_cache_miss", None
    return None


def clear_pypi_cache() -> None:
    """Reset the in-memory fetch cache. Exposed so tests don't leak cached
    responses between cases, and so a long batch run can be reset between
    independent phases if ever needed."""
    _pypi_response_cache.clear()
    # Artifact evidence is also run-local.  Clearing it makes independent
    # evaluations and tests unable to inherit a prior wheel inspection.
    _wheel_import_cache.clear()


# --- Rate limiting -----------------------------------------------------------
# Single-process, in-memory throttle only - no persistence across runs, no
# distributed coordination. Applies to real (uncached) requests only:
# fetch_pypi_project() checks the cache before any of this is reached, so a
# cache hit never waits and is never counted as a request.

_last_pypi_request_monotonic: Optional[float] = None


def reset_pypi_rate_limiter() -> None:
    """Reset the in-memory rate-limit clock, for the same reason
    clear_pypi_cache() exists: so one test's throttling state never leaks
    into the next."""
    global _last_pypi_request_monotonic
    _last_pypi_request_monotonic = None


def _throttle_before_request(min_interval_seconds: float) -> None:
    """Block, if needed, so at least `min_interval_seconds` has elapsed
    since the previous real PyPI request this process made. Called once per
    fetch_pypi_project() call, before the first HTTP attempt - not before
    each internal HTTP-429 retry, which already waits on its own
    Retry-After-derived delay. `min_interval_seconds <= 0` disables this
    entirely. Reads time.monotonic()/time.sleep() through the `time` module
    attribute (not imported names) so tests can monkeypatch
    pypi_retriever.time.sleep without ever waiting for real."""
    global _last_pypi_request_monotonic

    now = time.monotonic()

    if min_interval_seconds > 0 and _last_pypi_request_monotonic is not None:
        remaining = min_interval_seconds - (now - _last_pypi_request_monotonic)
        if remaining > 0:
            time.sleep(remaining)
            now = time.monotonic()

    _last_pypi_request_monotonic = now


def _parse_retry_after_seconds(raw_value: Optional[str]) -> Optional[float]:
    """Parse an HTTP `Retry-After` header as a plain, non-negative number of
    seconds only - the HTTP-date form is not supported. Never raises: a
    missing, non-numeric, or negative value returns None, so a malformed
    header always fails safe into "no usable wait time" instead of crashing
    or sleeping for a guessed duration."""
    if not raw_value:
        return None
    try:
        seconds = float(str(raw_value).strip())
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return seconds


def fetch_pypi_project(
    distribution_name: str,
    timeout: float = DEFAULT_FETCH_TIMEOUT_SECONDS,
    urlopen: Optional[Any] = None,
    use_cache: bool = True,
    min_request_interval: Optional[float] = None,
    max_retries_on_429: Optional[int] = None,
    max_retry_after_seconds: Optional[float] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Fetch one distribution's file listing from the official PyPI JSON
    Simple API (PEP 691), https://pypi.org/simple/{name}/ - never any other
    host, and never a URL supplied by a caller, an LLM, or an input record.

    `distribution_name` must already be PEP 503-normalized; it is validated
    again here before being inserted into the URL. `urlopen` is injectable
    for tests (default is the real urllib.request.urlopen, resolved at call
    time so monkeypatching urllib.request.urlopen also still works).

    Returns (status, data): status is "ok" (data is the parsed JSON dict),
    "package_not_found", "network_error", or "invalid_response". `data` is
    None for "package_not_found" and "invalid_response", and normally None
    for "network_error" too - except when the underlying cause was an HTTP
    429, in which case `data` is a small dict `{"reason": "rate_limited",
    "retry_after_seconds": float | None, "retries_attempted": int,
    "max_retries": int}` so a caller (retrieve()) can report a specific,
    honest reason without this function inventing a new top-level status.
    Distinguishes HTTP, connection, timeout, and parsing failures rather
    than collapsing them into one generic error, per
    day-1-rag-repair-agent-plan.md Step 4.

    Within-process results are cached by normalized distribution name
    (`use_cache=True`, the default) so a batch run never issues two
    requests for the same project - see docs/rag-design.md §2.4. A cache
    hit returns immediately, before any throttling or 429 handling below.

    **Caching policy - only "ok" and "package_not_found" are cached.**
    "network_error" and "invalid_response" are never cached, however they
    arose (connection failure, timeout, non-404/429 HTTP error, an
    exhausted 429 retry budget, unparseable JSON, a malformed distribution
    name, or a response missing the expected `files` list) - all of these
    are treated as possibly transient, so the *next* call for the same
    distribution always tries again for real rather than replaying a
    stale failure for the rest of the process's lifetime. "package_not_found"
    is the one deliberate exception: within one process, a 404 for a given
    distribution name is treated as stable negative information worth
    caching (this process never invents a mapping, so the only way a 404
    would stop being a 404 mid-run is PyPI itself changing, which a single
    batch run does not need to react to) - see
    `test_fetch_pypi_project_package_not_found_is_cached` in
    `tests/test_pypi_retriever.py`.

    Rate limiting (docs/rag-design.md §2.4, config/rag_repair.yaml
    `pypi_client.rate_limit`): before the first real HTTP attempt, waits
    (if needed) so at least `min_request_interval` seconds have passed
    since this process's last real PyPI request. On HTTP 429, retries at
    most `max_retries_on_429` times, only when the response's Retry-After
    header parses as a plain number of seconds no larger than
    `max_retry_after_seconds` - never an unbounded wait, never a guessed
    duration. All three rate-limit parameters default to the values loaded
    from config/rag_repair.yaml at import time when left as None; tests
    override them explicitly for determinism.
    """
    if use_cache and distribution_name in _pypi_response_cache:
        return _pypi_response_cache[distribution_name]

    if not _NORMALIZED_NAME_RE.match(distribution_name):
        # invalid_response - never cached, see "Caching policy" above.
        return "invalid_response", None

    frozen_result = _frozen_pypi_result(distribution_name)
    if frozen_result is not None:
        if use_cache and frozen_result[0] in {"ok", "package_not_found"}:
            _pypi_response_cache[distribution_name] = frozen_result
        return frozen_result

    interval = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS if min_request_interval is None else min_request_interval
    retries_allowed = DEFAULT_MAX_RETRIES_ON_429 if max_retries_on_429 is None else max_retries_on_429
    retry_after_cap = (
        DEFAULT_MAX_RETRY_AFTER_SECONDS if max_retry_after_seconds is None else max_retry_after_seconds
    )

    url = f"{PYPI_SIMPLE_BASE}/{distribution_name}/"
    headers = {
        "Accept": PYPI_SIMPLE_ACCEPT_HEADER,
        "User-Agent": USER_AGENT,
    }
    opener = urlopen if urlopen is not None else urllib.request.urlopen

    _throttle_before_request(interval)

    attempt = 0
    while True:
        request = urllib.request.Request(url, headers=headers)

        try:
            with opener(request, timeout=timeout) as response:
                raw_body = response.read()
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                result = ("package_not_found", None)
                if use_cache:
                    _pypi_response_cache[distribution_name] = result
                return result

            if exc.code == 429:
                exc_headers = getattr(exc, "headers", None)
                retry_after = _parse_retry_after_seconds(
                    exc_headers.get("Retry-After") if exc_headers is not None else None
                )
                can_retry = (
                    attempt < retries_allowed
                    and retry_after is not None
                    and retry_after <= retry_after_cap
                )
                if can_retry:
                    time.sleep(retry_after)
                    attempt += 1
                    continue

                # network_error (429, retry budget exhausted) - never cached.
                return (
                    "network_error",
                    {
                        "reason": "rate_limited",
                        "retry_after_seconds": retry_after,
                        "retries_attempted": attempt,
                        "max_retries": retries_allowed,
                    },
                )

            # network_error (any other HTTP status) - never cached.
            return "network_error", None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError):
            # network_error (connection failure/timeout) - never cached.
            return "network_error", None

    try:
        data = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # invalid_response - never cached.
        return "invalid_response", None

    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        # invalid_response - never cached.
        return "invalid_response", None

    result = ("ok", data)
    if use_cache:
        _pypi_response_cache[distribution_name] = result
    return result


# --- Parsing and grouping ----------------------------------------------------

def _parse_file_version(filename: str) -> Optional[Version]:
    """Extract a release Version from one PyPI Simple API file's filename,
    using PEP 440-aware parsing (never manual string splitting)."""
    if filename.endswith(".whl"):
        try:
            _, version, _, _ = parse_wheel_filename(filename)
            return version
        except (InvalidWheelFilename, InvalidVersion):
            return None

    try:
        _, version = parse_sdist_filename(filename)
        return version
    except (InvalidSdistFilename, InvalidVersion):
        return None


def _group_files_by_version(
    files: List[Dict[str, Any]],
    warnings: Optional[List[str]] = None,
) -> Dict[Version, List[Dict[str, Any]]]:
    """Turn the Simple API's flat file list into one entry per release
    version. Filenames that cannot be parsed safely, or non-dict file
    entries, are skipped and recorded - never guessed. Only the metadata
    needed for later filtering/evidence logging (filename, yanked,
    requires-python) survives; nothing here infers API-level compatibility
    from a filename or any PyPI metadata."""
    grouped: Dict[Version, List[Dict[str, Any]]] = {}

    for file_info in files:
        if not isinstance(file_info, dict):
            message = f"Skipping non-object PyPI file entry: {file_info!r}"
            print(f"[WARN] {message}", file=sys.stderr)
            if warnings is not None:
                warnings.append(message)
            continue

        filename = file_info.get("filename")
        if not filename:
            continue

        version = _parse_file_version(filename)
        if version is None:
            message = f"Skipping unparseable PyPI filename: {filename!r}"
            print(f"[WARN] {message}", file=sys.stderr)
            if warnings is not None:
                warnings.append(message)
            continue

        grouped.setdefault(version, []).append(file_info)

    return grouped


def _requires_python_specifiers(
    files: List[Dict[str, Any]],
    warnings: Optional[List[str]] = None,
) -> Tuple[List[SpecifierSet], Optional[str]]:
    """Collect the valid requires-python specifiers declared across a
    version's files, and the first raw declared value (for display)."""
    specifiers: List[SpecifierSet] = []
    first_declared: Optional[str] = None

    for file_info in files:
        raw = file_info.get("requires-python")
        if not raw:
            continue

        if first_declared is None:
            first_declared = raw

        try:
            specifiers.append(SpecifierSet(raw))
        except InvalidSpecifier:
            message = f"Invalid requires-python specifier {raw!r}; ignoring for compatibility checks"
            print(f"[WARN] {message}", file=sys.stderr)
            if warnings is not None:
                warnings.append(message)

    return specifiers, first_declared


def _evaluate_python_compatibility(
    usable_files: List[Dict[str, Any]],
    parsed_python_version: Optional[Version],
    warnings: Optional[List[str]] = None,
) -> Tuple[str, Optional[str]]:
    """Return (python_compatibility, requires_python) for one release,
    given only its non-yanked files.

    - "compatible": at least one usable file's requires-python is satisfied
      by the runtime Python version. This is PyPI-metadata compatibility
      only - it says the release *can be installed*, not that any specific
      imported symbol works, which is a distinct, stronger claim only
      wrong_version's compatibility-evidence intersection can make.
    - "incompatible": usable files declare requires-python, but none of them
      are satisfied by the runtime Python version.
    - "unknown": either the runtime Python version is not known, or no
      usable file declares requires-python at all. Never presented as
      proven compatible (docs/rag-design.md §7.3).
    """
    specifiers, requires_python = _requires_python_specifiers(usable_files, warnings)

    if parsed_python_version is None or not specifiers:
        return "unknown", requires_python

    if any(parsed_python_version in specifier for specifier in specifiers):
        return "compatible", requires_python

    return "incompatible", requires_python


def _parse_python_version_arg(
    python_version: Optional[str],
    warnings: Optional[List[str]] = None,
) -> Optional[Version]:
    if python_version is None:
        return None
    try:
        return Version(python_version)
    except InvalidVersion:
        message = f"Invalid python_version {python_version!r}; treating Python compatibility as unknown"
        print(f"[WARN] {message}", file=sys.stderr)
        if warnings is not None:
            warnings.append(message)
        return None


def _filter_grouped_candidates(
    grouped: Dict[Version, List[Dict[str, Any]]],
    parsed_python_version: Optional[Version],
    limit: Optional[int],
    warnings: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Reduce already-grouped releases to PyPI-metadata-safe candidates, per
    docs/rag-design.md §7: drop a release only if *every* one of its files
    is yanked; drop pre-release/dev releases; drop releases whose declared
    requires-python explicitly rejects the given Python version. Releases
    with *no* declared requires-python are kept and marked "unknown", not
    dropped and not claimed compatible - matching
    data/prompt-tests/l5_pypi_poc_filter_fixture.json, the L5 proof of
    concept's own verified fixture (day-1-rag-repair-agent-plan.md's
    stricter prose is superseded here; see docs/rag-design.md §2.2/§7).

    Sorted newest-first using real version comparison. `limit=None` returns
    every safe candidate, uncapped - required for the wrong_version path,
    which must intersect against the *full* safe set before any five-item
    cap is applied (capping first could silently discard an older,
    API-compatible release in favour of newer ones that turn out
    API-incompatible). `limit=<int>` caps immediately, for direct/standalone
    callers that have no further intersection step.
    """
    candidates: List[Tuple[Version, Dict[str, Any]]] = []

    for version, version_files in grouped.items():
        if version.is_prerelease or version.is_devrelease:
            continue

        non_yanked_files = [f for f in version_files if not f.get("yanked")]
        if not non_yanked_files:
            # every usable file for this release is yanked
            continue

        compatibility, requires_python = _evaluate_python_compatibility(
            non_yanked_files, parsed_python_version, warnings
        )

        if compatibility == "incompatible":
            continue

        candidates.append((
            version,
            {
                "version": str(version),
                "requires_python": requires_python,
                "python_compatibility": compatibility,
                "yanked": False,
                "yanked_reason": None,
            },
        ))

    candidates.sort(key=lambda item: item[0], reverse=True)
    ordered = [candidate for _, candidate in candidates]

    if limit is None:
        return ordered
    return ordered[:limit]


def filter_candidate_versions(
    files: List[Dict[str, Any]],
    python_version: Optional[str],
    limit: Optional[int] = MAX_CANDIDATE_VERSIONS,
) -> List[Dict[str, Any]]:
    """Public, standalone entry point: group raw PyPI files and reduce them
    to PyPI-metadata-safe candidates in one call. See
    _filter_grouped_candidates() for the filtering rules. retrieve() itself
    groups once internally (see below) to avoid grouping/warning twice for
    the same fetch."""
    parsed_python_version = _parse_python_version_arg(python_version)
    grouped = _group_files_by_version(files)
    return _filter_grouped_candidates(grouped, parsed_python_version, limit)


def _latest_stable_version_from_grouped(grouped: Dict[Version, List[Dict[str, Any]]]) -> Optional[str]:
    """The newest non-prerelease, non-fully-yanked version PyPI reports for
    this distribution - independent of Python-version filtering, matching
    what an unpinned install would resolve to by default."""
    stable_versions = [
        version
        for version, version_files in grouped.items()
        if not version.is_prerelease
        and not version.is_devrelease
        and any(not f.get("yanked") for f in version_files)
    ]

    if not stable_versions:
        return None

    return str(max(stable_versions))


# --- V2 evidence checks ------------------------------------------------------

_wheel_import_cache: Dict[str, Tuple[str, List[str]]] = {}


def _parse_utc_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp as an aware UTC value, or return None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _filter_candidates_by_date(
    candidates: List[Dict[str, Any]],
    grouped: Dict[Version, List[Dict[str, Any]]],
    repository_date: str,
) -> List[Dict[str, Any]]:
    """Keep releases that had a non-yanked file on PyPI by the repository date.

    A candidate with no trustworthy upload timestamp is deliberately omitted.
    Date anchoring is evidence about availability, not a claim that a package
    API is compatible; Docker execution remains the final validator.
    """
    anchor = _parse_utc_timestamp(repository_date)
    if anchor is None:
        return []
    filtered: List[Dict[str, Any]] = []
    for candidate in candidates:
        try:
            version = Version(candidate["version"])
        except (KeyError, InvalidVersion):
            continue
        upload_times = [
            parsed
            for file_info in grouped.get(version, [])
            if not file_info.get("yanked")
            for parsed in [_parse_utc_timestamp(file_info.get("upload-time"))]
            if parsed is not None
        ]
        if not upload_times:
            continue
        first_upload = min(upload_times)
        if first_upload <= anchor:
            dated = dict(candidate)
            dated["first_upload_time"] = first_upload.isoformat()
            filtered.append(dated)
    return filtered


def _wheel_top_level_imports(raw_wheel: bytes) -> Optional[List[str]]:
    """Read top-level imports from a wheel without installing or importing it."""
    try:
        with ZipFile(io.BytesIO(raw_wheel)) as wheel:
            names = wheel.namelist()
            top_level_files = [name for name in names if name.endswith(".dist-info/top_level.txt")]
            if top_level_files:
                content = wheel.read(top_level_files[0]).decode("utf-8", errors="replace")
                return sorted({line.strip() for line in content.splitlines() if line.strip()})

            record_files = [name for name in names if name.endswith(".dist-info/RECORD")]
            if not record_files:
                return None
            content = wheel.read(record_files[0]).decode("utf-8", errors="replace")
    except (BadZipFile, KeyError, OSError):
        return None

    top_levels = set()
    for line in content.splitlines():
        path = line.split(",", 1)[0]
        first = path.split("/", 1)[0]
        if not first or first.endswith(".dist-info") or first.endswith(".data"):
            continue
        if first.endswith(".py"):
            first = first[:-3]
        if first:
            top_levels.add(first)
    return sorted(top_levels) or None


def verify_wheel_provides_import(
    file_info: Dict[str, Any],
    import_name: str,
    timeout: float = DEFAULT_FETCH_TIMEOUT_SECONDS,
    urlopen: Optional[Any] = None,
) -> Tuple[str, List[str]]:
    """Verify a wheel supplies an import using its archived metadata.

    Only HTTPS wheel URLs hosted by PyPI's file host are accepted.  The wheel
    is inspected as an archive; it is never installed or executed.  Returns
    ``verified``, ``not_provided``, or ``evidence_unavailable``.
    """
    url = file_info.get("url")
    filename = file_info.get("filename")
    root = (import_name or "").strip().split(".", 1)[0]
    if not root:
        return "evidence_unavailable", []
    if _frozen_wheel_import_index is not None:
        indexed = _frozen_wheel_import_index.get(filename) if isinstance(filename, str) else None
        if indexed is not None:
            return ("verified" if root in indexed else "not_provided"), indexed
        if not _frozen_pypi_allow_network:
            return "evidence_unavailable", []
    if not isinstance(url, str):
        return "evidence_unavailable", []
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"files.pythonhosted.org", "pypi.org"}:
        return "evidence_unavailable", []
    if url in _wheel_import_cache:
        status, top_levels = _wheel_import_cache[url]
        return status if root in top_levels else "not_provided", top_levels

    opener = urlopen if urlopen is not None else urllib.request.urlopen
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with opener(request, timeout=timeout) as response:
            raw_wheel = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout, TimeoutError, ConnectionError):
        return "evidence_unavailable", []

    top_levels = _wheel_top_level_imports(raw_wheel)
    if top_levels is None:
        return "evidence_unavailable", []
    _wheel_import_cache[url] = ("verified", top_levels)
    return ("verified" if root in top_levels else "not_provided"), top_levels


def _verify_candidates_provide_import(
    candidates: List[Dict[str, Any]],
    grouped: Dict[Version, List[Dict[str, Any]]],
    import_name: str,
) -> Tuple[List[Dict[str, Any]], str]:
    """Retain only candidate releases with a wheel that proves the import."""
    verified_candidates: List[Dict[str, Any]] = []
    evidence_unavailable = False
    for candidate in candidates:
        try:
            version = Version(candidate["version"])
        except (KeyError, InvalidVersion):
            continue
        wheel_files = [
            file_info for file_info in grouped.get(version, [])
            if not file_info.get("yanked") and str(file_info.get("filename", "")).endswith(".whl")
        ]
        if not wheel_files:
            evidence_unavailable = True
            continue
        candidate_verified = False
        unavailable_for_candidate = False
        for file_info in wheel_files:
            status, top_levels = verify_wheel_provides_import(file_info, import_name)
            if status == "verified":
                verified = dict(candidate)
                verified["import_verification"] = {
                    "status": "verified",
                    "wheel_filename": file_info.get("filename"),
                    "top_level_imports": top_levels,
                }
                verified_candidates.append(verified)
                candidate_verified = True
                break
            if status == "evidence_unavailable":
                unavailable_for_candidate = True
        if not candidate_verified and unavailable_for_candidate:
            evidence_unavailable = True

    if verified_candidates:
        return verified_candidates, "resolved"
    return [], "import_evidence_unavailable" if evidence_unavailable else "import_not_provided"


# --- Public entry point ------------------------------------------------------

def _empty_result(
    import_name: str,
    subtype: str,
    python_version: Optional[str],
    module_path: Optional[str],
    symbol: Optional[str],
) -> Dict[str, Any]:
    return {
        "status": None,
        "import_name": import_name,
        "subtype": subtype,
        "module_path": module_path,
        "symbol": symbol,
        "distribution_name": None,
        "package_found": None,
        "python_version": python_version,
        "latest_version": None,
        "candidate_versions": [],
        "compatibility_evidence": None,
        "source_endpoint": None,
        "retrieved_at": None,
        "warnings": [],
        "error": None,
    }


def retrieve(
    import_name: str,
    python_version: Optional[str] = None,
    subtype: str = "missing_package",
    module_path: Optional[str] = None,
    symbol: Optional[str] = None,
    resolver_config: Optional[Dict[str, Any]] = None,
    repository_date: Optional[str] = None,
    record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve `import_name` to a verified PyPI distribution, retrieve its
    release metadata, and return a bounded, safe set of candidate versions.

    Deviation from day-1-rag-repair-agent-plan.md's original two-parameter
    sketch (`retrieve(import_name, python_version=None)`): `subtype`,
    `module_path`, and `symbol` are added so this single entry point can
    also perform the wrong_version compatibility-evidence intersection
    docs/rag-design.md §2.2 requires - a second, parallel function was not
    introduced. Calls that omit them behave exactly as the original
    two-parameter signature (subtype defaults to "missing_package").

    `python_version` defaults to the fixed execution-runtime constant in
    config/rag_repair.yaml (currently "3.10") when not explicitly
    overridden. If that configuration is missing or invalid and no explicit
    override is given, returns status "configuration_error" without making
    any PyPI request - never silently falls back to notebook metadata or a
    second hardcoded version.

    The default resolver preserves V1 behaviour.  For
    `subtype="wrong_version"`, it requires `module_path` and `symbol` and
    intersects PyPI-metadata-safe candidates with the existing static API
    compatibility evidence.

    With ``resolver_config={"mode": "v2", ...}``, the function first
    classifies standard-library/local-path cases, then tries a small mismatch
    table or identity/PEP-503 lookup.  It returns candidates only after wheel
    metadata proves that the distribution provides the requested top-level
    import.  V2 wrong-version candidates additionally require a repository
    commit date and retain only releases uploaded by that date.  This is an
    availability filter, not a claim of API compatibility; Docker execution
    remains the final validator.

    Always returns the full schema (see module docstring / docs/rag-design.md
    §6), including on every failure path. It never constructs, returns, or
    runs an installation command.
    """
    result = _empty_result(import_name, subtype, python_version, module_path, symbol)
    resolver_config = resolver_config or {}
    v2_mode = resolver_config.get("mode") == "v2"
    if v2_mode:
        result["resolver"] = {
            "mode": "v2",
            "mapping_method": None,
            "repository_date": repository_date,
            "scope": None,
        }

    if python_version is not None:
        resolved_python_version = python_version
    elif DEFAULT_PYTHON_VERSION is not None:
        resolved_python_version = DEFAULT_PYTHON_VERSION
    else:
        result["status"] = "configuration_error"
        result["error"] = DEFAULT_PYTHON_VERSION_ERROR
        return result

    result["python_version"] = resolved_python_version

    if subtype == "wrong_version" and (not module_path or not symbol):
        # Pure caller-input validation: this can be decided before any
        # network activity, exactly like mapping_unknown below.
        result["status"] = "no_compatible_release"
        result["error"] = "wrong_version requires both module_path and symbol; none were supplied"
        return result

    if v2_mode:
        # This happens before any package-index lookup.  The check is
        # intentionally conservative: only standard-library names and an
        # explicit relative import are classified; ambiguous short names are
        # reported for review instead of being silently called a package.
        from import_scope import classify_import_scope

        scope = classify_import_scope(import_name, record)
        result["resolver"]["scope"] = scope
        if scope["status"] != "third_party_dependency":
            result["status"] = scope["status"]
            result["error"] = scope["reason"]
            return result

        # The outer V2 call tries every non-LLM candidate source in the
        # published policy.  Each inner call executes the normal PyPI and
        # wheel verification path for exactly one candidate.  This prevents
        # an identity project that exists but exposes the wrong import from
        # blocking a later public mapping candidate.
        forced_candidate = resolver_config.get("_v2_resolution_candidate")
        if forced_candidate is None:
            try:
                deterministic_candidates = resolve_v2_distribution_candidates(
                    import_name, resolver_config
                )
            except OSError as exc:
                result["status"] = "configuration_error"
                result["error"] = f"could not read V2 import mapping: {exc}"
                return result
            if not deterministic_candidates:
                result["status"] = "mapping_unknown"
                result["error"] = "The import name was empty; no distribution candidate could be formed."
                return result

            attempts = []
            retryable_negative_statuses = {"package_not_found", "import_not_provided"}
            for candidate_name, method in deterministic_candidates:
                nested_config = dict(resolver_config)
                nested_config["_v2_resolution_candidate"] = {
                    "distribution_name": candidate_name,
                    "mapping_method": method,
                }
                candidate_result = retrieve(
                    import_name,
                    python_version=python_version,
                    subtype=subtype,
                    module_path=module_path,
                    symbol=symbol,
                    resolver_config=nested_config,
                    repository_date=repository_date,
                    record=record,
                )
                attempts.append({
                    "distribution_name": candidate_name,
                    "mapping_method": method,
                    "status": candidate_result.get("status"),
                    "error": candidate_result.get("error"),
                })
                if candidate_result.get("status") == "resolved":
                    candidate_result.setdefault("resolver", {})["deterministic_attempts"] = attempts
                    return candidate_result
                # A network/configuration/date/evidence failure is not proof
                # that the candidate is wrong.  Do not hide it by trying
                # another name or by asking the LLM to guess.
                if candidate_result.get("status") not in retryable_negative_statuses:
                    candidate_result.setdefault("resolver", {})["deterministic_attempts"] = attempts
                    return candidate_result

            result["resolver"]["deterministic_attempts"] = attempts
            result["status"] = "mapping_unknown"
            result["error"] = (
                "No deterministic candidate both existed on PyPI and proved the requested import "
                "through inspected wheel metadata."
            )
            return result
        try:
            distribution_name = forced_candidate["distribution_name"]
            mapping_method = forced_candidate["mapping_method"]
        except (KeyError, TypeError) as exc:
            result["status"] = "configuration_error"
            result["error"] = f"invalid forced V2 distribution candidate: {exc}"
            return result
        result["resolver"]["mapping_method"] = mapping_method
    else:
        distribution_name = resolve_distribution_name(import_name)
    if distribution_name is None:
        result["status"] = "mapping_unknown"
        return result

    result["distribution_name"] = distribution_name

    normalized_name = normalize_distribution_name(distribution_name)
    endpoint = f"{PYPI_SIMPLE_BASE}/{normalized_name}/"

    # A V2 wrong-version proposal must be anchored to repository history.
    # Validate this before querying PyPI, because an unanchored file listing
    # cannot become valid evidence later in the process.
    if v2_mode and subtype == "wrong_version" and _parse_utc_timestamp(repository_date) is None:
        result["status"] = "date_evidence_unavailable"
        result["error"] = (
            "V2 wrong-version retrieval requires the repository commit date; "
            "none was supplied or it was not an ISO-8601 UTC timestamp."
        )
        return result

    fetch_status, data = fetch_pypi_project(normalized_name)

    if fetch_status == "frozen_cache_miss":
        result["status"] = "frozen_cache_miss"
        result["source_endpoint"] = f"frozen-pypi-cache:{_frozen_pypi_cache_path}#{normalized_name}"
        result["error"] = "The frozen comparison PyPI snapshot has no entry for this distribution."
        return result

    if fetch_status == "package_not_found":
        result["status"] = "package_not_found"
        result["package_found"] = False
        result["source_endpoint"] = endpoint
        result["retrieved_at"] = utc_now()
        return result

    if fetch_status == "network_error":
        result["status"] = "network_error"
        result["source_endpoint"] = endpoint
        if isinstance(data, dict) and data.get("reason") == "rate_limited":
            retry_after = data.get("retry_after_seconds")
            retry_after_text = (
                f"retry_after={retry_after}s" if retry_after is not None else "no usable Retry-After value"
            )
            message = (
                "PyPI rate-limited this request (HTTP 429); "
                f"{retry_after_text} (retries_attempted={data.get('retries_attempted')}/"
                f"{data.get('max_retries')})."
            )
            result["error"] = message
            result["warnings"] = [message]
        else:
            result["error"] = "Could not reach PyPI (timeout, DNS, or connection failure)."
        return result

    if fetch_status == "invalid_response":
        result["status"] = "invalid_response"
        result["source_endpoint"] = endpoint
        result["error"] = "PyPI response could not be parsed or was missing the expected 'files' list."
        return result

    files = data.get("files", [])
    warnings: List[str] = []

    result["package_found"] = True
    result["source_endpoint"] = endpoint
    result["retrieved_at"] = utc_now()

    grouped = _group_files_by_version(files, warnings)
    result["latest_version"] = _latest_stable_version_from_grouped(grouped)

    parsed_python_version = _parse_python_version_arg(resolved_python_version, warnings)
    general_candidates = _filter_grouped_candidates(grouped, parsed_python_version, limit=None, warnings=warnings)

    if subtype == "wrong_version" and not v2_mode:
        # Lazy import: compatibility_evidence imports normalize_distribution_name
        # from this module, so a top-level import here would be circular.
        from compatibility_evidence import (
            filter_versions_by_compatibility_evidence,
            lookup_compatibility_evidence,
        )

        evidence = lookup_compatibility_evidence(distribution_name, module_path, symbol)
        result["compatibility_evidence"] = {
            "status": evidence["status"],
            "compatible_specifier": evidence.get("compatible_specifier"),
            "evidence": evidence.get("evidence"),
        }

        if evidence["status"] != "resolved":
            result["error"] = (
                f"No usable API-compatibility evidence for {module_path}.{symbol} "
                f"(compatibility_evidence status: {evidence['status']})"
            )
            result["warnings"] = warnings
            result["status"] = "no_compatible_release"
            return result

        # Intersect against the FULL (uncapped) PyPI-safe set, then cap -
        # capping before this point could discard an older, still-compatible
        # release in favour of newer ones that later prove API-incompatible.
        candidates = filter_versions_by_compatibility_evidence(general_candidates, evidence)[:MAX_CANDIDATE_VERSIONS]
    elif not v2_mode:
        candidates = general_candidates[:MAX_CANDIDATE_VERSIONS]

    if v2_mode:
        if subtype == "wrong_version":
            candidates = _filter_candidates_by_date(general_candidates, grouped, repository_date)
            result["compatibility_evidence"] = {
                "status": "date_anchored",
                "repository_date": repository_date,
                "meaning": "candidate releases were available on PyPI by the repository commit date",
            }
            if not candidates:
                result["status"] = "no_compatible_release"
                result["warnings"] = warnings
                result["error"] = "No PyPI release with a recorded upload time was available by the repository commit date."
                return result
        else:
            candidates = general_candidates

        # Check no more than the proposal budget.  A verified wheel is
        # required for every returned candidate, so a project name alone
        # never becomes evidence that it provides the requested import.
        candidates = candidates[:MAX_CANDIDATE_VERSIONS]
        candidates, verification_status = _verify_candidates_provide_import(
            candidates, grouped, import_name
        )
        if not candidates:
            result["status"] = verification_status
            result["warnings"] = warnings
            if verification_status == "import_not_provided":
                result["error"] = "No inspected PyPI wheel provided the requested top-level import."
            else:
                result["error"] = (
                    "Wheel metadata needed to verify the requested import was unavailable."
                )
            return result

    result["candidate_versions"] = candidates
    result["warnings"] = warnings

    if not candidates:
        result["status"] = "no_compatible_release"
        return result

    result["status"] = "resolved"
    return result
