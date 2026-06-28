"""Schemas for Stage 4-5: Spec writing + self-reflection."""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, Field, field_validator

from devloop.spec_phase._homoglyph_table import HOMOGLYPH_TO_ASCII
from devloop.spec_phase.schemas.common import (
    SCHEMA_VERSION,
    CodeRef,
    Priority,
    RequirementType,
)

# ---------------------------------------------------------------------------
# Soft-language defense (DevLoop Sprint A — A4)
#
# The writer prompt forbids vague hedging phrases ("or equivalent", "TBD",
# "if needed", ...) because they leak unresolved decisions into the spec.
# Prompt-only defense is unreliable (proven across 5 cases), so we enforce
# this at the schema layer via pydantic validators on the affected fields.
#
# Escape hatch: phrases enclosed in backticks (`code` or ```fenced```) are
# stripped before matching, so legitimate references to the literal word
# (e.g. an HTML `placeholder` attribute) can still appear.
#
# Unicode-confusable defense (DevLoop Sprint F1 — A4 follow-up): before
# matching, every guarded string is normalized via NFKC + a vendored
# homoglyph table (`_homoglyph_table.HOMOGLYPH_TO_ASCII`) so that
# adversarial Cyrillic / Greek / Math-Alphanumeric / Fullwidth lookalikes
# (e.g. "or еquivalent" with Cyrillic U+0435) cannot bypass the regex.
# Zero-width and other Cf format chars are normalized to a regular space
# (Sprint F2) so they act as valid separators and the regex catches
# ``or<ZWSP>equivalent`` as ``or equivalent``.
# Whitelisted scripts (CJK, Arabic, Hebrew, Devanagari, ...) pass through
# unchanged so legitimate multi-language spec text is unaffected.
#
# Boundary-mutation defense (DevLoop Sprint F2 — A4 follow-up): the
# regex is built around a permissive separator class (``_SEP``) that
# accepts whitespace, hyphen, underscore, period, middle-dot, and named
# zero-width Unicode chars between tokens of every multi-word phrase, plus
# optional plural suffix (``s``/``es``) and optional parenthesized wrap
# (``if (needed)``). False-positive guards:
#   * "TBD-1234" / "TBA-1234" ticket references are NOT flagged
#     (negative lookahead ``(?![-_]\w)`` after the abbreviation).
#   * "if-statement" / "or-pattern" do not match because the second word
#     ("statement" / "pattern") isn't in the phrase list.
#   * "ifneeded" / "asneeded" require at least one separator OR opening
#     paren between the two tokens.
# ---------------------------------------------------------------------------

# Boundary-tolerant separator class (DevLoop Sprint F2 — A4 follow-up).
# Includes ASCII whitespace (incl. NBSP/tab/newline via ``\s``), hyphen,
# underscore, period, middle dot (U+00B7), and the named zero-width
# Unicode format chars (ZWSP / ZWNJ / ZWJ / LRM / RLM). All other Cf
# chars are normalized to space upstream by ``_normalize_for_match``.
_SEP = r"[\s\-_.\u00b7\u200b\u200c\u200d\u200e\u200f]"

# Trailing boundary that accepts non-letter follow-up (digit / punct / EOS)
# but rejects mid-word continuation, e.g. "equivalentXYZ" must not match
# while "equivalent." / "equivalent)" / "equivalents " all do. Used in
# place of the closing ``\b`` for phrases with optional plural / paren
# trailers, which can confuse ``\b`` when the next char is ``)``.
_NW = r"(?![A-Za-z])"

_FORBIDDEN_PHRASES_RE = re.compile(
    # or equivalent[s|es] — separator-tolerant, plural-tolerant, paren-tolerant
    rf"\bor{_SEP}+\(?{_SEP}*equivalent(?:s|es)?{_NW}(?:{_SEP}*\))?"
    # or similar[s|es]
    rf"|\bor{_SEP}+\(?{_SEP}*similar(?:s|es)?{_NW}(?:{_SEP}*\))?"
    # TBD — bare token only; ticket refs like ``TBD-1234`` are excluded
    rf"|\bTBD\b(?![-_]\w)"
    # TBA — bare token only; ticket refs like ``TBA-1234`` are excluded
    rf"|\bTBA\b(?![-_]\w)"
    # to be decided / to be determined — separator-tolerant on both joins
    rf"|\bto{_SEP}+be{_SEP}+(?:decided|determined)\b"
    # if needed / if (needed) / if-needed / if_needed / if·needed
    # Requires a separator OR an opening paren between "if" and "needed"
    # so "ifneeded" (no gap) does not false-positive.
    rf"|\bif(?:{_SEP}+|{_SEP}*\({_SEP}*)needed{_NW}(?:{_SEP}*\))?"
    # as needed / as (needed) / as-needed — same shape as if-needed
    rf"|\bas(?:{_SEP}+|{_SEP}*\({_SEP}*)needed{_NW}(?:{_SEP}*\))?"
    # placeholder[s]
    rf"|\bplaceholders?\b",
    re.IGNORECASE,
)

_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")


def _strip_code_blocks(text: str) -> str:
    """Remove fenced and inline backtick code so they don't trigger the soft-language regex."""
    text = _FENCED_CODE_RE.sub("", text)
    text = _INLINE_CODE_RE.sub("", text)
    return text


def _normalize_for_match(text: str) -> str:
    """Fold Unicode confusables to ASCII before regex matching.

    Steps:
    1. NFKC normalize -- collapses compatibility forms (Fullwidth Latin,
       Mathematical Alphanumeric Symbols, half-width katakana, ligatures,
       ...) into their canonical equivalents. Many homoglyph attack
       vectors (Fullwidth ``ｏ``, Math Bold ``𝐨``, ...) reduce to ASCII
       here for free.
    2. Per-character homoglyph fold via the vendored ``HOMOGLYPH_TO_ASCII``
       table -- catches Cyrillic / Greek / Coptic / Armenian / IPA /
       Cherokee / etc. lookalikes that NFKC does NOT normalize. The
       table whitelists CJK / Arabic / Hebrew / Devanagari / Thai / ...
       scripts (they have no entry, so they pass through unchanged).
    3. Strip Unicode Cf (Format) characters -- removes zero-width
       separators (U+200B, U+200C, U+200D, U+FEFF, ...) and bidirectional
       overrides. This catches the "rejoin" attack: e.g. ``place\u200bholder``
       collapses to the forbidden ``placeholder``. The separate
       ``_normalize_for_match_spaced`` variant catches the dual "split"
       attack (``or\u200bequivalent`` -> ``or equivalent``).
    """
    if not text:
        return text
    normalized = unicodedata.normalize("NFKC", text)
    result_chars: list[str] = []
    for ch in normalized:
        if unicodedata.category(ch) == "Cf":
            continue
        result_chars.append(HOMOGLYPH_TO_ASCII.get(ch, ch))
    return "".join(result_chars)


def _normalize_for_match_spaced(text: str) -> str:
    """Sibling of ``_normalize_for_match`` that replaces Cf chars with a space.

    This catches the "split" attack vector where invisible Cf characters
    (e.g. U+200B ZWSP) are wedged between tokens of a forbidden phrase to
    defeat the ``\\b`` / ``\\s+`` matchers: ``or\u200bequivalent`` becomes
    ``or equivalent`` and matches the regex.

    Used in conjunction with ``_normalize_for_match`` (Cf-strip) so BOTH
    attack vectors (rejoin AND split) are detected.
    """
    if not text:
        return text
    normalized = unicodedata.normalize("NFKC", text)
    result_chars: list[str] = []
    for ch in normalized:
        if unicodedata.category(ch) == "Cf":
            result_chars.append(" ")
            continue
        result_chars.append(HOMOGLYPH_TO_ASCII.get(ch, ch))
    return "".join(result_chars)


def find_forbidden_phrase(value: str) -> str | None:
    """Return the first forbidden soft-language phrase in ``value``, or None if clean.

    Backtick-fenced code is stripped before matching so that legitimate uses of the
    literal word (e.g. an HTML ``placeholder`` attribute) escape the check.

    The input is Unicode-normalized (NFKC + homoglyph fold + Cf handling) before
    matching so confusable-character bypasses (Cyrillic ``е``, Greek ``ο``,
    Math Bold ``𝐨``, Fullwidth ``ｏ``, zero-width separators, ...) are caught.
    Two complementary normalizations are tried -- Cf-strip (catches the
    ``place\u200bholder`` rejoin attack) and Cf->space (catches the
    ``or\u200bequivalent`` split attack) -- so both invisible-separator
    bypass directions are blocked.

    The returned phrase is the matched substring of the NORMALIZED text, so it
    reads as the ASCII canonical form (e.g. ``"or equivalent"`` even when the
    input contained ``"or еquivalent"``) -- the original raw text is still
    available to callers via ``value`` for echo in error messages.
    """
    if not value:
        return None
    stripped = _strip_code_blocks(value)
    for candidate in (
        _normalize_for_match(stripped),
        _normalize_for_match_spaced(stripped),
    ):
        match = _FORBIDDEN_PHRASES_RE.search(candidate)
        if match:
            return match.group(0)
    return None


def validate_no_soft_language(field_name: str, value: str) -> str:
    """Reject ``value`` if it contains forbidden soft-language phrases.

    Returns the original ``value`` unchanged on success (so the helper is safe to
    use directly as a pydantic ``@field_validator`` body). Raises ``ValueError``
    with the matched phrase included if a forbidden phrase is detected outside of
    backtick-fenced code.
    """
    matched = find_forbidden_phrase(value)
    if matched:
        raise ValueError(
            f"{field_name} contains forbidden soft language: '{matched}'. "
            "Be specific or use needs_clarification (BlockingDecision)."
        )
    return value


# ---------------------------------------------------------------------------
# Under-escalation defense (DevLoop F3 — A3)
#
# The spec writer occasionally dumps "I see 3 implementation options, not sure
# which" into ``Concern.evidence_gap`` instead of escalating the decision to a
# top-of-spec ``BlockingDecision`` in ``needs_clarification``. Self-concerns are
# meant for residual implementation uncertainty the writer has *already*
# resolved with a default; a multi-option decision is a real blocker that must
# be surfaced to a reviewer/user before coding starts.
#
# The patterns below detect explicit enumerations of ≥3 implementation choices
# (English + Chinese) so the pydantic validator can reject the concern and
# force the writer to escalate. Two-option choices fall through (binary
# decisions are typically picked by the writer with a clear default).
# ---------------------------------------------------------------------------

_UNDERESCALATED_PATTERNS = [
    # English: "3 options" / "three alternatives" / "several approaches" with enumeration intent
    re.compile(
        r"\b(?P<n>\d+|three|four|five|six|seven|eight|nine|ten|several|multiple|N)\s+"
        r"(option|alternative|approach|candidate|choice|implementation|design)s?\b",
        re.IGNORECASE,
    ),
    # Chinese: "3 种选项" / "多个备选" / "几种方案"
    re.compile(
        r"(?P<n>\d+|三|四|五|六|七|八|九|十|几|多|若干)\s*"
        r"(种|个|项|条)?\s*"
        r"(选项|备选|方案|候选|实现|做法|路径|途径)"
    ),
    # English alt form: "option A, option B, option C" or "Options 1, 2, and 3"
    re.compile(
        r"\boption(?:s)?\s+\d+[\s,]+(?:and\s+)?\d+[\s,]+(?:and\s+)?\d+\b",
        re.IGNORECASE,
    ),
]


def detect_underescalated_concern(text: str) -> str | None:
    """Return the matched phrase if the concern text describes ≥3 options
    that should be escalated to BlockingDecision; None otherwise.

    False-positive guards:
    - "Option to" (preposition) — does NOT match because pattern requires
      'options' (plural with a count) or an explicit enumeration.
    - "for several reasons" — does NOT match (reasons not in keyword set).
    - "two options" — does NOT match (digit must be ≥3 / 'three').
    """
    if not text:
        return None
    for pattern in _UNDERESCALATED_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        # Try to verify n >= 3 if numeric
        n_str = m.groupdict().get("n", "") if m.groupdict() else ""
        if n_str:
            num_map = {
                "three": 3,
                "four": 4,
                "five": 5,
                "six": 6,
                "seven": 7,
                "eight": 8,
                "nine": 9,
                "ten": 10,
                "三": 3,
                "四": 4,
                "五": 5,
                "六": 6,
                "七": 7,
                "八": 8,
                "九": 9,
                "十": 10,
                "several": 3,
                "multiple": 3,
                "几": 3,
                "多": 3,
                "若干": 3,
                "n": 3,
            }
            try:
                n = int(n_str) if n_str.isdigit() else num_map.get(n_str.lower(), 0)
            except (ValueError, AttributeError):
                n = 0
            if n < 3:
                continue
        return m.group(0)
    return None


class AcceptanceScenario(BaseModel):
    """Given-When-Then acceptance scenario."""

    given: str
    when: str
    then: str


class UserStory(BaseModel):
    id: str = Field(..., description="US-1, US-2, ...")
    priority: Priority
    title: str
    description: str
    why_this_priority: str = ""
    independent_test: str = ""
    acceptance: list[AcceptanceScenario] = Field(default_factory=list)


class FunctionalRequirement(BaseModel):
    id: str = Field(..., description="FR-001, FR-002, ...")
    text: str
    requirement_type: RequirementType
    related_user_stories: list[str] = Field(default_factory=list)
    related_success_criteria: list[str] = Field(
        default_factory=list,
        description=(
            "SC ids that verify this FR. Used by the trace-matrix validator "
            "to detect orphan functional FRs without measurable acceptance."
        ),
    )
    code_references: list[CodeRef] = Field(
        default_factory=list,
        description="Required for functional FRs; optional for non-functional",
    )
    testable: bool = True

    @field_validator("text")
    @classmethod
    def _no_soft_language_text(cls, v: str) -> str:
        return validate_no_soft_language("FunctionalRequirement.text", v)


class SuccessCriterion(BaseModel):
    id: str = Field(..., description="SC-001, SC-002, ...")
    text: str
    metric: str = Field(..., description="What is being measured")
    threshold: str = Field(..., description="Expected value/range")
    technology_agnostic: bool = True
    related_requirements: list[str] = Field(
        default_factory=list,
        description=(
            "FR ids this SC verifies. Used by the trace-matrix validator to "
            "detect SCs that don't exercise any functional requirement."
        ),
    )

    @field_validator("metric")
    @classmethod
    def _no_soft_language_metric(cls, v: str) -> str:
        return validate_no_soft_language("SuccessCriterion.metric", v)

    @field_validator("threshold")
    @classmethod
    def _no_soft_language_threshold(cls, v: str) -> str:
        return validate_no_soft_language("SuccessCriterion.threshold", v)


class Entity(BaseModel):
    name: str
    description: str
    fields: list[str] = Field(default_factory=list)
    references: list[str] = Field(
        default_factory=list,
        description="Names of related existing entities",
    )

    @field_validator("description")
    @classmethod
    def _no_soft_language_description(cls, v: str) -> str:
        return validate_no_soft_language("Entity.description", v)


class EdgeCase(BaseModel):
    description: str
    handling: str = ""

    @field_validator("handling")
    @classmethod
    def _no_soft_language_handling(cls, v: str) -> str:
        return validate_no_soft_language("EdgeCase.handling", v)


class Concern(BaseModel):
    """A self-identified concern from the writer (Stage 5)."""

    location: str = Field(..., description="e.g. 'FR-007' or 'Key Entity Comment'")
    concern: str
    evidence_gap: str = Field(
        ..., description="What evidence is missing that prevents full confidence"
    )
    suggested_resolution: str | None = None

    @field_validator("evidence_gap")
    @classmethod
    def _no_underescalation(cls, v: str) -> str:
        m = detect_underescalated_concern(v)
        if m:
            raise ValueError(
                f"Concern.evidence_gap describes ≥3 implementation options "
                f"({m!r}). This should be escalated to needs_clarification "
                f"(BlockingDecision) so a reviewer/user can decide before coding. "
                f"Move it to Spec.needs_clarification with recommended_default + if_rejected."
            )
        return v

    @field_validator("suggested_resolution")
    @classmethod
    def _no_soft_language_suggested_resolution(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_no_soft_language("Concern.suggested_resolution", v)


class BlockingDecision(BaseModel):
    """A NEEDS_CLARIFICATION top-of-spec blocker.

    Use this for material conflicts between user input and existing code
    (e.g. user requests "new X table" but code already has X). Distinct from
    Concern (which is for residual implementation uncertainty) — a
    BlockingDecision must be resolved before coding starts.
    """

    id: str = Field(..., description="NC-001, NC-002, ...")
    title: str = Field(..., description="Short description of the decision needed")
    conflict: str = Field(..., description="Why this is a blocker — what conflicts")
    recommended_default: str = Field(
        ..., description="The writer's recommended resolution and rationale"
    )
    if_rejected: str = Field(..., description="What to do if the default is rejected")
    related_requirements: list[str] = Field(
        default_factory=list, description="FRs / SCs affected by this decision"
    )

    @field_validator("recommended_default")
    @classmethod
    def _no_soft_language_recommended_default(cls, v: str) -> str:
        return validate_no_soft_language("BlockingDecision.recommended_default", v)

    @field_validator("if_rejected")
    @classmethod
    def _no_soft_language_if_rejected(cls, v: str) -> str:
        return validate_no_soft_language("BlockingDecision.if_rejected", v)


class SpecMetadata(BaseModel):
    feature_id: str
    title: str
    writer_model: str = ""
    reviewer_model: str = ""
    iterations: int = 0
    needs_review: bool = False
    total_llm_calls: int = 0
    total_tool_calls: int = 0


class Spec(BaseModel):
    """The final structured specification."""

    schema_version: str = SCHEMA_VERSION
    metadata: SpecMetadata
    summary: str = Field(..., description="One-paragraph high-level summary")
    needs_clarification: list[BlockingDecision] = Field(
        default_factory=list,
        description=(
            "Top-of-spec blocking decisions that must be resolved before coding. "
            "Use for material conflicts between user input and existing code."
        ),
    )
    user_stories: list[UserStory] = Field(default_factory=list)
    functional_requirements: list[FunctionalRequirement] = Field(default_factory=list)
    success_criteria: list[SuccessCriterion] = Field(default_factory=list)
    key_entities: list[Entity] = Field(default_factory=list)
    edge_cases: list[EdgeCase] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    self_concerns: list[Concern] = Field(
        default_factory=list,
        description="Stage 5 mandatory self-reflection",
    )

    @field_validator("summary")
    @classmethod
    def _no_soft_language_summary(cls, v: str) -> str:
        return validate_no_soft_language("Spec.summary", v)


# ---------------------------------------------------------------------------
# Segmented rewriter partial schemas (DevLoop Sprint D — D3)
#
# The single-shot rewriter produces an entire ~30KB JSON Spec in one LLM call,
# which is slow and brittle — a mid-call failure loses all progress. The
# segmented rewriter splits the work into 5 dependent LLM calls, each
# validated independently with the per-segment partial schemas below.
#
# Each schema covers ONLY the fields produced by that segment so pydantic
# rejects a bad segment without rejecting unrelated good ones. Field
# validators (e.g. soft-language guards) are inherited from the underlying
# typed elements (FunctionalRequirement, SuccessCriterion, ...) so the same
# A4 protections fire per segment.
# ---------------------------------------------------------------------------


class SpecSegmentHead(BaseModel):
    """Segment 1: metadata + summary + blocking decisions.

    Sets the stage for the rest of the rewrite. Small, fast, and surfaces
    blocking decisions (``needs_clarification``) before the writer commits
    to user stories / FRs that may depend on them.
    """

    metadata: SpecMetadata
    summary: str = Field(..., description="One-paragraph high-level summary")
    needs_clarification: list[BlockingDecision] = Field(default_factory=list)

    @field_validator("summary")
    @classmethod
    def _no_soft_language_summary(cls, v: str) -> str:
        return validate_no_soft_language("SpecSegmentHead.summary", v)


class SpecSegmentStories(BaseModel):
    """Segment 2: user stories.

    Depends on segment 1's ``summary`` — the rewriter is given the head
    segment as context so stories align with the high-level goal.
    """

    user_stories: list[UserStory] = Field(default_factory=list)


class SpecSegmentFRs(BaseModel):
    """Segment 3: functional requirements.

    Depends on segment 2's ``user_stories`` — the rewriter is given the
    stories so it can populate ``FunctionalRequirement.related_user_stories``
    with real US ids (not hallucinated ones).
    """

    functional_requirements: list[FunctionalRequirement] = Field(default_factory=list)


class SpecSegmentSCs(BaseModel):
    """Segment 4: success criteria.

    Depends on segment 3's ``functional_requirements`` — the rewriter is
    given the FR ids so ``SuccessCriterion.related_requirements`` can
    reference them without dangling pointers.
    """

    success_criteria: list[SuccessCriterion] = Field(default_factory=list)


class SpecSegmentTail(BaseModel):
    """Segment 5: entities, edge cases, assumptions, out_of_scope, self-concerns.

    Final wrap-up segment. Bundled together because each piece is small and
    they share the full prior-segment context (head + stories + FRs + SCs).
    """

    key_entities: list[Entity] = Field(default_factory=list)
    edge_cases: list[EdgeCase] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    self_concerns: list[Concern] = Field(default_factory=list)
