"""Per-perspective explorer Perspective cache (DevLoop Sprint D — todo D2).

Each explorer agent (``data`` / ``api`` / ``ui`` / ``test`` / ``history``) runs
on the same repo, so when multiple cases are evaluated against the same
checkout the explorers repeat almost identical work. We cache the
``Perspective`` produced by each agent keyed by:

    (cwd_path, head_commit, perspective_type, intent_summary)

where ``intent_summary`` is ``intent.primary[:200]`` so cosmetically different
intent strings still share the cache when the user is asking the "same thing".

The actual cache key stored in SQLite is the hex SHA-256 of those four fields
joined by ``|`` — this keeps the row primary key short, opaque, and collision-
resistant.

Storage delegates to :class:`devloop.cache.CacheBackend.get_perspective` /
``set_perspective``; TTL eviction (``settings.cache.ttl_days``) is handled
there.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from devloop.spec_phase.schemas import Perspective

if TYPE_CHECKING:  # pragma: no cover - typing only
    from devloop.cache import CacheBackend
    from devloop.spec_phase.schemas import ConfirmedIntent

logger = logging.getLogger(__name__)

INTENT_SUMMARY_MAX_CHARS = 200


def intent_summary_from(intent: ConfirmedIntent | None) -> str:
    """Return the cache-relevant slice of ``intent.primary`` (or ``""`` if missing).

    Trimmed to ``INTENT_SUMMARY_MAX_CHARS`` so trivially long primary strings do
    not balloon the key derivation and so two intents that only diverge after
    the slice boundary still hit the same cache row.
    """
    if intent is None:
        return ""
    return (intent.primary or "")[:INTENT_SUMMARY_MAX_CHARS]


def compute_perspective_cache_key(
    cwd_path: str,
    head_commit: str,
    perspective_type: str,
    intent_summary: str,
) -> str:
    """Deterministic SHA-256 key for a single explorer Perspective.

    Inputs are joined by ``|`` and UTF-8 encoded. Returns the full 64-char hex
    digest. Any change to any of the four inputs produces a different key.
    """
    raw = f"{cwd_path}|{head_commit}|{perspective_type}|{intent_summary}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cached_perspective(cache: CacheBackend, cache_key: str) -> Perspective | None:
    """Return the cached :class:`Perspective` for ``cache_key`` or ``None``.

    Returns ``None`` on cache miss, on TTL expiry, or when the stored payload
    fails to deserialize (treated as a miss rather than crashing the run).
    """
    raw = cache.get_perspective(cache_key)
    if raw is None:
        return None
    try:
        return Perspective.model_validate_json(raw)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "explorer cache entry failed to deserialize (treating as miss): %s",
            exc,
        )
        return None


def set_cached_perspective(
    cache: CacheBackend, cache_key: str, perspective: Perspective
) -> None:
    """JSON-serialize ``perspective`` and store it under ``cache_key``."""
    cache.set_perspective(cache_key, perspective.model_dump_json())
