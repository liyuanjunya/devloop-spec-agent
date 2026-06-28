"""Intent-driven selection of which explorer perspectives to run.

The explorer stage iterates over a list of :data:`PerspectiveType` values.
Running every perspective on every feature is wasteful (e.g. a backend bug
fix doesn't need the UI explorer) and incomplete (e.g. a feature touching
auth + file uploads should also run a `security` perspective).

:func:`select_perspectives` resolves the active list from the
:class:`ConfirmedIntent` produced by Stage 2 using simple, deterministic
rules — substring matching on ``intent.primary`` (lowercased) and exact
membership tests on ``intent.scope``. The result is the order-preserving
deduplicated list of perspectives to run.

Defaults always included: ``data``, ``api``, ``test``, ``history``. The
``ui`` perspective is conditional on intent scope. ``security`` and
``performance`` are conditional on either scope tags, the
``intent_type``, or trigger keywords appearing in the primary intent
sentence.

Callers may pass ``explicit_override`` (e.g. forwarded from
``settings.explorer.perspectives`` when the user has explicitly
configured them); when provided, that list is returned verbatim with no
auto-selection applied.
"""

from __future__ import annotations

from devloop.spec_phase.schemas import ConfirmedIntent, PerspectiveType

ALWAYS_INCLUDED: tuple[PerspectiveType, ...] = ("data", "api", "test", "history")
"""Perspectives that always run regardless of intent."""

_UI_SCOPE_TRIGGERS: frozenset[str] = frozenset({"ui", "frontend"})

_SECURITY_SCOPE_TRIGGERS: frozenset[str] = frozenset(
    {"security", "auth", "external_integration"}
)
_SECURITY_PRIMARY_KEYWORDS: tuple[str, ...] = (
    "upload",
    "image",
    "file",
    "prompt",
    "llm",
    "openai",
    "password",
    "token",
    "secret",
    "rate-limit",
)

_PERFORMANCE_SCOPE_TRIGGERS: frozenset[str] = frozenset({"performance"})
_PERFORMANCE_PRIMARY_KEYWORDS: tuple[str, ...] = (
    "n+1",
    "performance",
    "latency",
    "optimize",
    "slow",
    "query count",
)


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(n in haystack for n in needles)


def select_perspectives(
    intent: ConfirmedIntent,
    *,
    explicit_override: list[PerspectiveType] | None = None,
) -> list[PerspectiveType]:
    """Pick which perspectives to run based on intent.

    Always include: ``data``, ``api``, ``test``, ``history``.

    Conditional:

    - ``ui`` if ``intent.scope`` contains ``ui`` or ``frontend``
    - ``security`` if ``intent.scope`` contains ``security``, ``auth``, or
      ``external_integration`` OR ``intent.primary`` mentions any of
      ``{upload, image, file, prompt, llm, openai, password, token,
      secret, rate-limit}`` (case-insensitive substring match)
    - ``performance`` if ``intent.intent_type == "perf_opt"`` OR
      ``intent.scope`` contains ``performance`` OR ``intent.primary``
      mentions any of ``{n+1, performance, latency, optimize, slow,
      query count}`` (case-insensitive substring match)

    ``explicit_override`` (from settings or CLI) wins over auto-selection:
    when provided, the list is returned verbatim with order and duplicates
    preserved as-given.

    The returned list preserves a stable order:
    ``data, api, ui, test, history, security, performance``.
    """
    if explicit_override is not None:
        return list(explicit_override)

    primary_lower = intent.primary.lower()
    scope_set: set[str] = set(intent.scope)

    selected: list[PerspectiveType] = ["data", "api"]

    if scope_set & _UI_SCOPE_TRIGGERS:
        selected.append("ui")

    selected.extend(["test", "history"])

    if (scope_set & _SECURITY_SCOPE_TRIGGERS) or _contains_any(
        primary_lower, _SECURITY_PRIMARY_KEYWORDS
    ):
        selected.append("security")

    if (
        intent.intent_type == "perf_opt"
        or (scope_set & _PERFORMANCE_SCOPE_TRIGGERS)
        or _contains_any(primary_lower, _PERFORMANCE_PRIMARY_KEYWORDS)
    ):
        selected.append("performance")

    return selected


__all__ = ["ALWAYS_INCLUDED", "select_perspectives"]
