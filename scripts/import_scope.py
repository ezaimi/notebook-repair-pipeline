"""Evidence-based scope checks used by the V2 dependency resolver.

The original dataset excluded a few short names merely because they *could*
have been local modules.  That is not enough evidence to call an import
local, and it also incorrectly catches standard-library modules such as
``statistics``.  V2 therefore performs this small, deterministic check before
consulting PyPI.  It never guesses that an ordinary import is local.
"""

import re
import sys
from typing import Any, Dict, Iterable, Optional


# These names sometimes identify a repository helper, but a bare error
# message cannot prove that.  They must be kept separate from a confirmed
# local import and from a normal third-party lookup.
AMBIGUOUS_LOCAL_ROOTS = {"config", "helpers", "src", "utils"}


def import_root(import_name: Optional[str]) -> str:
    """Return the top-level import component without interpreting it."""
    return (import_name or "").strip().lstrip(".").split(".", 1)[0]


def _context_texts(record: Optional[Dict[str, Any]]) -> Iterable[str]:
    """Yield only source-like strings supplied with an enriched record."""
    if not isinstance(record, dict):
        return []
    context = record.get("prompt_context", {})
    if not isinstance(context, dict):
        return []

    texts = []
    for key in ("failing_cell_source", "cell_source", "surrounding_cells", "import_cells"):
        value = context.get(key)
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, list):
            texts.extend(item for item in value if isinstance(item, str))
        elif isinstance(value, dict):
            texts.extend(item for item in value.values() if isinstance(item, str))
    return texts


def classify_import_scope(import_name: Optional[str], record: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Classify an import before package-index lookup.

    Returns a small audit-friendly result with one of four statuses:
    ``standard_library``, ``local_import_path``, ``classification_uncertain``,
    or ``third_party_dependency``.  Only an explicit relative import in the
    captured notebook source is accepted as evidence of a local import.
    """
    root = import_root(import_name)
    if not root:
        return {"status": "classification_uncertain", "reason": "missing_import_name"}

    stdlib_names = getattr(sys, "stdlib_module_names", frozenset())
    if root in stdlib_names:
        return {"status": "standard_library", "reason": "python_standard_library"}

    # ``from .helpers import x`` and ``from ..pkg import x`` are the concrete
    # evidence available in a notebook cell that an import is repository-local.
    relative_pattern = re.compile(
        rf"^\s*from\s+\.+{re.escape(root)}(?:\.|\s|$)", re.MULTILINE
    )
    if any(relative_pattern.search(text) for text in _context_texts(record)):
        return {"status": "local_import_path", "reason": "relative_import_in_notebook_source"}

    if root.lower() in AMBIGUOUS_LOCAL_ROOTS:
        return {"status": "classification_uncertain", "reason": "ambiguous_short_import_without_path_evidence"}

    return {"status": "third_party_dependency", "reason": "no_standard_library_or_local_path_evidence"}
