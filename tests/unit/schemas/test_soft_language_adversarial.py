"""Adversarial tests for the soft-language schema validators (DevLoop Sprint A — A4).

Capability-boundary test T-defense-fires-A4. The happy-path tests in
``test_soft_language_validator.py`` confirm the validators fire on the canonical
phrases. This file probes the *boundary* — case folding, whitespace tricks,
Unicode homoglyphs, hyphen / underscore separators, pluralization, fence-escape
abuses, and field-scope leaks — to surface false negatives and document
design-intent limitations.

Each test ends with a one-line tag:

* ``# EXPECTED: ...``        — the validator behaves correctly here.
* ``# DOCUMENTED LIMITATION: ...`` — a real bypass that future work should
  consider fixing. We intentionally do NOT fix it here; we pin the current
  (broken) behavior so any future tightening of the regex flips a red test
  and forces a deliberate decision.
* ``# BY DESIGN: ...``       — the field is intentionally not validated.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from devloop.spec_phase.schemas import (
    BlockingDecision,
    EdgeCase,
    Entity,
    FunctionalRequirement,
    Spec,
    SpecMetadata,
    SuccessCriterion,
)
from devloop.spec_phase.schemas.spec import find_forbidden_phrase

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fr(text: str) -> FunctionalRequirement:
    """Build a FunctionalRequirement with the given guarded ``text``."""
    return FunctionalRequirement(id="FR-001", text=text, requirement_type="functional")


def _sc(*, metric: str = "p99 latency", threshold: str = "< 200 ms") -> SuccessCriterion:
    """Build a SuccessCriterion with the given guarded fields."""
    return SuccessCriterion(id="SC-001", text="latency", metric=metric, threshold=threshold)


def _clean_spec() -> Spec:
    """Build a minimal, validator-clean Spec for round-trip mutation tests."""
    return Spec(
        metadata=SpecMetadata(feature_id="f1", title="Feature One"),
        summary="Allow logged-in users to favorite recipes via a star button.",
        functional_requirements=[
            FunctionalRequirement(
                id="FR-001",
                text="System must persist a favorite when the star is clicked.",
                requirement_type="functional",
            )
        ],
        success_criteria=[
            SuccessCriterion(
                id="SC-001",
                text="Favorite action latency stays below threshold under load.",
                metric="p99 latency of POST /favorite",
                threshold="< 200 ms at 100 rps",
            )
        ],
    )


# ---------------------------------------------------------------------------
# 1. Bypass via case — "OR EQUIVALENT" (uppercase) must still trigger
# ---------------------------------------------------------------------------


def test_uppercase_or_equivalent_still_triggers() -> None:
    """Uppercase forbidden phrase must match (regex uses re.IGNORECASE)."""
    with pytest.raises(ValidationError) as exc:
        _fr("System must persist data OR EQUIVALENT for resilience.")
    assert "or equivalent" in str(exc.value).lower()
    # EXPECTED: re.IGNORECASE on _FORBIDDEN_PHRASES_RE catches all-caps form.


# ---------------------------------------------------------------------------
# 2. Bypass via whitespace — "or  equivalent" (double space)
# ---------------------------------------------------------------------------


def test_double_space_between_or_and_equivalent_still_triggers() -> None:
    """``\\s+`` in the regex collapses one-or-more whitespace, so double
    spaces (and tabs / newlines) between the two tokens still match."""
    with pytest.raises(ValidationError) as exc:
        _fr("System must persist data or  equivalent table.")
    assert "or  equivalent" in str(exc.value) or "or equivalent" in str(exc.value).lower()
    # EXPECTED: the regex uses \s+ between tokens so any whitespace span matches.

    # Bonus: tab and newline are also \s and must trigger.
    assert find_forbidden_phrase("or\tequivalent") is not None
    assert find_forbidden_phrase("or\nequivalent") is not None
    # And the U+00A0 non-breaking space is \s in Python re too:
    assert find_forbidden_phrase("or\u00a0equivalent") is not None


# ---------------------------------------------------------------------------
# 3. Bypass via punctuation — "or equivalent;" (trailing semicolon)
# ---------------------------------------------------------------------------


def test_trailing_punctuation_does_not_bypass() -> None:
    """``\\b`` is a zero-width word boundary, so trailing punctuation
    (``;``, ``.``, ``,``, ``)``) doesn't shield the phrase."""
    with pytest.raises(ValidationError):
        _fr("Use UserToRecipe or equivalent; migrate later.")
    # Same for other trailing punctuation
    with pytest.raises(ValidationError):
        _fr("Use UserToRecipe or equivalent.")
    with pytest.raises(ValidationError):
        EdgeCase(description="d", handling="(TBD).")
    # EXPECTED: \b handles all non-word boundary characters uniformly.


# ---------------------------------------------------------------------------
# 4. Catch the parenthesized middle word — "if (needed) do X"
#
# Sprint F2 closed this bypass: the regex now accepts an optional opening
# paren after the first token and an optional closing paren after the
# second so ``if (needed)`` matches just like ``if needed``.
# ---------------------------------------------------------------------------


def test_parenthesized_inner_word_caught_for_if_needed() -> None:
    """``if (needed)`` (parenthesized middle word) now matches.

    Sprint F2 broadened the ``if``/``as`` patterns to allow an optional
    ``(`` between the tokens and an optional trailing ``)``. The pattern
    still requires either a separator OR a paren between ``if`` and
    ``needed`` so ``ifneeded`` (no gap at all) does NOT false-positive.
    """
    with pytest.raises(ValidationError) as exc:
        _fr("System will retry if (needed) within 5s.")
    assert "if (needed)" in str(exc.value).lower() or "if needed" in str(exc.value).lower()

    # The helper also returns a non-None match for raw parenthesized text.
    assert find_forbidden_phrase("if (needed) do X") is not None
    assert find_forbidden_phrase("as (needed)") is not None
    assert find_forbidden_phrase("if(needed)") is not None  # no space too

    # Negative guard: standalone ``ifneeded`` (no separator, no paren) does
    # NOT match -- the pattern requires at least one separator OR an open
    # paren between the two tokens.
    assert find_forbidden_phrase("ifneeded") is None
    # And ``if-statement`` (different second word) is not flagged.
    assert find_forbidden_phrase("if-statement compatibility") is None
    # EXPECTED (Sprint F2): parenthesized middle / trailing word caught.


# ---------------------------------------------------------------------------
# 5. Backtick escape — "`or equivalent` is fine" must NOT trigger
# ---------------------------------------------------------------------------


def test_backtick_wrapped_phrase_is_escaped() -> None:
    """Inline backticks strip the wrapped span before regex matching, so
    legitimate literal uses (``\\`placeholder\\``) survive."""
    fr = _fr("`or equivalent` is the literal phrase we forbid.")
    assert "or equivalent" in fr.text  # text was preserved
    assert find_forbidden_phrase("`or equivalent`") is None
    # EXPECTED: backtick escape hatch works for inline code spans.

    # But the escape ONLY protects what's inside backticks — a phrase
    # outside the span still triggers even when other backticks exist:
    with pytest.raises(ValidationError):
        _fr("`foo` requires UserToRecipe or equivalent storage.")
    # EXPECTED: escape is span-local, not document-global.


# ---------------------------------------------------------------------------
# 6. Bypass via leading newline — "\nor equivalent"
# ---------------------------------------------------------------------------


def test_leading_newline_does_not_bypass() -> None:
    """``\\b`` matches at any word boundary including string start after
    a newline, so a leading newline (or any whitespace) doesn't help."""
    with pytest.raises(ValidationError):
        _fr("\nor equivalent storage strategy.")
    with pytest.raises(ValidationError):
        _fr("   \n\n\tor equivalent storage strategy.")
    # EXPECTED: \b is whitespace-anchor-friendly.


# ---------------------------------------------------------------------------
# 7. Cyrillic homoglyph — "or еquivalent" with U+0435 instead of ASCII 'e'
#
# Sprint F1 closed this bypass via NFKC + a vendored homoglyph fold table.
# ---------------------------------------------------------------------------


def test_cyrillic_homoglyph_caught() -> None:
    """The Cyrillic letter at U+0435 is visually identical to Latin ``e``
    but a totally different codepoint. Sprint F1 added NFKC normalization
    and a per-character homoglyph fold (`HOMOGLYPH_TO_ASCII`) so this
    attack vector is now caught."""
    # The phrase below LOOKS like "or equivalent" but the inner letter
    # after the space is U+0435 (Cyrillic), not ASCII 'e'.
    sneaky = "or \u0435quivalent storage"
    matched = find_forbidden_phrase(sneaky)
    assert matched is not None and matched.lower() == "or equivalent"
    # And the model rejects it:
    with pytest.raises(ValidationError):
        _fr(f"System must persist {sneaky} table.")
    # EXPECTED (Sprint F1): NFKC + homoglyph fold catches Cyrillic /
    # Greek / Coptic / Math-Alphanumeric / Fullwidth lookalikes.


# ---------------------------------------------------------------------------
# 8. Catch hyphen / underscore / dot / middle-dot separator — "or-equivalent"
#
# Sprint F2 expanded the separator class to include ``-``, ``_``, ``.``,
# ``·`` and the named zero-width Unicode chars so all these variants match.
# ---------------------------------------------------------------------------


def test_hyphen_separator_caught() -> None:
    """The separator class ``_SEP`` now accepts hyphen / underscore / period /
    middle-dot between tokens, so ``or-equivalent`` / ``or_equivalent`` /
    ``or.equivalent`` / ``or·equivalent`` all match."""
    for sep in ("-", "_", ".", "\u00b7"):
        text = f"or{sep}equivalent"
        matched = find_forbidden_phrase(text)
        assert matched is not None, f"FAILED to catch {text!r}"

    # And the model rejects them:
    with pytest.raises(ValidationError):
        _fr("System uses UserToRecipe or-equivalent table.")
    with pytest.raises(ValidationError):
        _fr("System uses UserToRecipe or_equivalent table.")
    with pytest.raises(ValidationError):
        _fr("System uses UserToRecipe or.equivalent table.")

    # And the negative cases (different second word) still pass — the
    # regex only matches when ``equivalent`` / ``similar`` follows ``or``.
    assert find_forbidden_phrase("or-pattern matching") is None
    assert find_forbidden_phrase("or_else fallback") is None
    # EXPECTED (Sprint F2): hyphen / underscore / period / middle-dot
    # separator bypass closed.


# ---------------------------------------------------------------------------
# 9. Catch plural form — "or equivalents" / "placeholders"
#
# Sprint F2 added optional plural suffix (``s`` / ``es``) for the two
# pluralizable phrases (``equivalent``, ``similar``) and for the standalone
# ``placeholder`` word. ``TBD`` / ``TBA`` / ``to be decided`` / ``if needed``
# are NOT pluralized — they aren't real plurals as a soft phrase.
# ---------------------------------------------------------------------------


def test_plural_form_caught() -> None:
    """``equivalent[s|es]`` / ``similar[s|es]`` / ``placeholder[s]`` all match.

    Other phrases (``TBD``, ``to be decided``, ``if needed``) intentionally
    don't have plural variants because ``TBDs`` / ``to be decideds`` /
    ``if neededs`` are not real soft-language phrases.
    """
    # or equivalents / or equivalentes
    assert find_forbidden_phrase("or equivalents") is not None
    assert find_forbidden_phrase("or equivalentes") is not None
    # placeholders
    assert find_forbidden_phrase("placeholders for fields") is not None
    # or similars
    assert find_forbidden_phrase("or similars") is not None

    # And the model rejects them:
    with pytest.raises(ValidationError):
        _fr("System uses UserToRecipe or equivalents.")
    with pytest.raises(ValidationError):
        Entity(name="HelpText", description="placeholders for field hints.")

    # Negative: the plural is still bounded by a non-letter, so identifier
    # uses like ``placeholders_value`` (underscore continues the word) do
    # NOT false-positive.
    assert find_forbidden_phrase("placeholders_value") is None
    assert find_forbidden_phrase("placeholder_value") is None
    # And a real word that *starts with* the stem ("equivalency") is not
    # flagged either (the negative lookahead ``(?![A-Za-z])`` blocks it).
    assert find_forbidden_phrase("or equivalency check") is None
    # EXPECTED (Sprint F2): plural-form bypass closed for pluralizable phrases.


# ---------------------------------------------------------------------------
# 10. Embedded in JSON — escaped quotes around the phrase
# ---------------------------------------------------------------------------


def test_phrase_inside_escaped_quotes_still_triggers() -> None:
    """JSON-encoded quotation marks (``\\"``) aren't word chars and don't
    affect ``\\b`` matching — the validator sees through them."""
    payload = '... \\"if needed\\" ...'
    assert find_forbidden_phrase(payload) == "if needed"
    with pytest.raises(ValidationError):
        EdgeCase(description="parse JSON", handling=payload)
    # EXPECTED: regex operates on the decoded Python string; escapes don't help.


# ---------------------------------------------------------------------------
# 11. Repeated phrase — "TBD TBD TBD" — error message names ONE occurrence
# ---------------------------------------------------------------------------


def test_repeated_phrase_error_reports_first_only() -> None:
    """When the same forbidden phrase appears multiple times, the error
    message quotes ONLY the first match — by design, we want the surface
    error short, not exhaustive. ``find_forbidden_phrase`` returns one
    string; the writer-side ``detect_soft_language_in_spec_dict`` is the
    exhaustive reporter."""
    with pytest.raises(ValidationError) as exc:
        _sc(metric="TBD TBD TBD")
    err = str(exc.value)
    # The error mentions soft language and the phrase appears in single-quotes.
    assert "'TBD'" in err
    # Sanity: helper only returns one phrase per call
    assert find_forbidden_phrase("TBD TBD TBD") == "TBD"
    # EXPECTED: first-match semantics; multi-error reporting is the writer
    # pre-check helper's job, not the per-field validator's.


# ---------------------------------------------------------------------------
# 12. Multiple distinct phrases — "or equivalent or similar"
# ---------------------------------------------------------------------------


def test_multiple_distinct_phrases_report_first_only() -> None:
    """When two different forbidden phrases co-occur, the error names the
    first one encountered (left-to-right). The second is masked until the
    first is fixed and the validator re-runs."""
    with pytest.raises(ValidationError) as exc:
        _fr("Use UserToRecipe or equivalent or similar storage.")
    err = str(exc.value)
    # The validator's *quoted matched phrase* is the first match only.
    # (Note: pydantic also echoes the original input via ``input_value=...``,
    # which contains both phrases — so we assert on the QUOTED phrase token,
    # not on raw substring presence.)
    assert "'or equivalent'" in err
    assert "'or similar'" not in err
    # Helper-level confirmation: only one phrase returned per call.
    assert find_forbidden_phrase("or equivalent or similar") == "or equivalent"
    # EXPECTED: first-match semantics. May feel like a UX limitation, but
    # the writer-side ``detect_soft_language_in_spec_dict`` enumerates all
    # findings for the LLM in a single pre-check pass.


# ---------------------------------------------------------------------------
# 13. Phrase inside Entity.name (not validated) — must NOT trigger
# ---------------------------------------------------------------------------


def test_soft_language_in_entity_name_is_not_validated() -> None:
    """Only ``Entity.description`` carries a @field_validator. The ``name``
    field is by-design unguarded — entity names rarely contain hedging
    phrases, and validating them risks false positives on legitimate
    code-identifier names."""
    ent = Entity(name="TBD_placeholder_table", description="A real description.")
    assert "TBD" in ent.name
    assert "placeholder" in ent.name
    # BY DESIGN: name fields aren't validated; only natural-language fields are.


# ---------------------------------------------------------------------------
# 14. Soft language inside out_of_scope list item — must NOT trigger
# ---------------------------------------------------------------------------


def test_soft_language_in_out_of_scope_is_not_validated() -> None:
    """``Spec.out_of_scope`` is a plain ``list[str]`` with no item-level
    validator. Hedging like ``if needed`` is allowed when explicitly
    listing things we are NOT building."""
    spec = Spec(
        metadata=SpecMetadata(feature_id="f", title="t"),
        summary="Persist favorites via a star button.",
        out_of_scope=[
            "Backfilling historical favorites if needed.",
            "Cross-account sharing TBD.",
            "Migration to a new table or equivalent storage.",
        ],
    )
    assert any("if needed" in s for s in spec.out_of_scope)
    assert any("TBD" in s for s in spec.out_of_scope)
    # BY DESIGN: out_of_scope items intentionally describe vague,
    # NOT-doing-this items and are exempt from the soft-language guard.


# ---------------------------------------------------------------------------
# 15. Soft language inside BlockingDecision.conflict — NOT validated
# ---------------------------------------------------------------------------


def test_soft_language_in_blocking_decision_conflict_is_not_validated() -> None:
    """``conflict`` describes the unresolved tension — it is *expected*
    to contain hedged language like ``or equivalent``, ``TBD``, ``to be
    decided`` while explaining why a decision is blocked. Only
    ``recommended_default`` and ``if_rejected`` are guarded."""
    bd = BlockingDecision(
        id="NC-001",
        title="Storage strategy",
        conflict=(
            "Input requests a new table or equivalent storage; existing "
            "code has is_favorite TBD — strategy is to be decided."
        ),
        recommended_default="Reuse UserToRecipe.is_favorite.",
        if_rejected="Create new table with backfill from is_favorite.",
    )
    assert "or equivalent" in bd.conflict
    assert "TBD" in bd.conflict
    assert "to be decided" in bd.conflict
    # BY DESIGN: ``conflict`` is the narrative description of WHY this is a
    # blocker; hedging there is the point. The recommendation / fallback
    # must be concrete (and ARE validated — see existing positive tests).


# ---------------------------------------------------------------------------
# 16. All-uppercase TBA in success_criterion threshold — must trigger
# ---------------------------------------------------------------------------


def test_all_uppercase_tba_in_threshold_triggers() -> None:
    """All-caps ``TBA`` is the typical sentinel the LLM emits; it must be
    rejected on every guarded numeric / threshold field."""
    with pytest.raises(ValidationError) as exc:
        _sc(threshold="TBA")
    assert "tba" in str(exc.value).lower()
    assert "SuccessCriterion.threshold" in str(exc.value)
    # Also rejected mid-sentence and with surrounding punctuation:
    with pytest.raises(ValidationError):
        _sc(threshold="< TBA ms")
    with pytest.raises(ValidationError):
        _sc(threshold="(TBA)")
    # EXPECTED: TBA matches case-insensitively with full \b protection.


# ---------------------------------------------------------------------------
# 17. Whole-spec round-trip: build clean Spec, mutate one field, revalidate
# ---------------------------------------------------------------------------


def test_round_trip_mutation_revalidate_fails_on_each_guarded_field() -> None:
    """Round-trip: clean Spec → dump → mutate ONE guarded field at a time
    → revalidate. Every guarded field must reject. This pins the full
    validator surface in a single test even as new guarded fields are
    added (a new field guarded by ``validate_no_soft_language`` should
    be added to ``mutations`` below)."""
    base = _clean_spec()
    dumped = base.model_dump(mode="json")
    # Sanity: the clean dump revalidates without error
    Spec.model_validate(dumped)

    # Each mutation is keyed by (json-path-description, mutator-callable,
    # expected-field-name-in-error).
    mutations: list[tuple[str, str]] = [
        ("summary", "Persist favorites; migration TBD."),
        (
            "functional_requirements[0].text",
            "System must persist favorites in UserToRecipe or equivalent.",
        ),
        ("success_criteria[0].metric", "p99 latency TBD"),
        ("success_criteria[0].threshold", "< 200 ms or similar"),
    ]

    for path, poison in mutations:
        poisoned = base.model_dump(mode="json")
        # walk path to mutate
        if path == "summary":
            poisoned["summary"] = poison
        elif path == "functional_requirements[0].text":
            poisoned["functional_requirements"][0]["text"] = poison
        elif path == "success_criteria[0].metric":
            poisoned["success_criteria"][0]["metric"] = poison
        elif path == "success_criteria[0].threshold":
            poisoned["success_criteria"][0]["threshold"] = poison
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unhandled path {path}")

        with pytest.raises(ValidationError) as exc:
            Spec.model_validate(poisoned)
        # EXPECTED: every guarded field rejects the mutation
        err = str(exc.value).lower()
        assert any(phrase in err for phrase in ("tbd", "or equivalent", "or similar")), (
            f"path {path} mutation did not trigger: {err}"
        )


# ---------------------------------------------------------------------------
# Bonus boundary probes (not in the original 17 but worth pinning).
# ---------------------------------------------------------------------------


def test_zero_width_space_separator_caught() -> None:
    """U+200B (zero-width space) is now caught.

    Sprint F1's ``_normalize_for_match_spaced`` replaces every Cf char
    (ZWSP / ZWNJ / ZWJ / LRM / RLM / BOM / bidi overrides) with an ASCII
    space before matching, so ``or<ZWSP>equivalent`` becomes
    ``or equivalent`` and the regex catches it.

    Sprint F2 additionally lists the named zero-width chars in the
    separator class ``_SEP`` so even direct (un-normalized) matching
    would catch them.
    """
    assert find_forbidden_phrase("or\u200bequivalent") is not None
    # And the family: ZWNJ / ZWJ / LRM / RLM all close the bypass too.
    for cf in ("\u200c", "\u200d", "\u200e", "\u200f", "\ufeff"):
        text = f"or{cf}equivalent"
        assert find_forbidden_phrase(text) is not None, f"FAILED to catch {text!r}"

    # And the model rejects ZWSP-separated phrases:
    with pytest.raises(ValidationError):
        _fr("System uses UserToRecipe or\u200bequivalent table.")
    # EXPECTED (Sprint F1 + F2): zero-width separator bypass closed.


def test_unclosed_code_fence_does_not_grant_escape() -> None:
    """The fence-escape regex requires a CLOSING ``\\`\\`\\`\\``. An
    unclosed fence does not strip downstream text, so a forbidden phrase
    after an unclosed fence still triggers — preventing a trivial
    'open a fence and never close it' escape."""
    assert find_forbidden_phrase("```\nor equivalent") == "or equivalent"
    with pytest.raises(ValidationError):
        EdgeCase(description="d", handling="```\nor equivalent (unclosed fence)")
    # EXPECTED: escape hatch requires matched fences; unclosed fence does
    # NOT silently strip the rest of the document.


def test_word_internal_phrase_does_not_false_positive() -> None:
    """Sanity check on \\b: a forbidden token jammed inside a longer word
    must NOT trigger. e.g. ``PLACEHOLDERvalue`` is a valid identifier,
    not the forbidden ``placeholder`` phrase."""
    assert find_forbidden_phrase("PLACEHOLDERvalue") is None
    assert find_forbidden_phrase("xyzTBD") is None
    assert find_forbidden_phrase("TBDxyz") is None
    # Construction succeeds — no false positive:
    ent = Entity(name="X", description="See PLACEHOLDERvalue constant for default.")
    assert "PLACEHOLDERvalue" in ent.description
    # EXPECTED: \b protects against substring-in-identifier false positives.


# ---------------------------------------------------------------------------
# Sprint F1 — Unicode-confusable / multi-language test suite.
#
# These tests exercise the full breadth of the homoglyph fold table built
# in ``devloop/spec_phase/_homoglyph_table.py``: every major source script
# that contributes Latin look-alikes (Greek, Mathematical Alphanumeric
# Symbols, Fullwidth Forms, multi-character Cyrillic substitution) must be
# caught, AND legitimate multi-language text in WHITELISTED scripts
# (CJK, Arabic, Hebrew, Devanagari, ...) must pass through unmolested.
# ---------------------------------------------------------------------------


def test_greek_omicron_caught() -> None:
    """Greek small letter omicron (U+03BF) substituted for ASCII 'o' is caught.

    The phrase below LOOKS like ``or equivalent`` but the first letter is
    Greek omicron (U+03BF), not ASCII 'o'. The vendored homoglyph table
    folds omicron -> 'o' so the regex catches it.
    """
    sneaky = "\u03bfr equivalent storage"
    matched = find_forbidden_phrase(sneaky)
    assert matched is not None and matched.lower() == "or equivalent"
    with pytest.raises(ValidationError):
        _fr(f"System must persist data {sneaky} table.")
    # And capital Omicron in TBD-style abbreviation:
    # (no Greek substitute is meaningful for "TBD" since the letters are
    # never realistically Greek-confused; we stick to or-prefixed cases.)
    # EXPECTED (Sprint F1): Greek omicron is in HOMOGLYPH_TO_ASCII.


def test_math_alphanumeric_caught() -> None:
    """Mathematical Alphanumeric Symbols (Math Bold / Italic / Fraktur / ...)
    are NFKC-normalized to ASCII Latin, so an adversarial Math Bold 'o' in
    ``or equivalent`` is caught.

    Covers U+1D400-U+1D7FF plane: Math Bold, Italic, Bold Italic, Script,
    Bold Script, Fraktur, Double-Struck, Bold Fraktur, Sans-Serif (regular,
    Bold, Italic, Bold Italic), and Monospace.
    """
    # Math Bold 'o' (U+1D428) in the first letter of "or"
    sneaky = "\U0001d428r equivalent storage"
    matched = find_forbidden_phrase(sneaky)
    assert matched is not None and matched.lower() == "or equivalent"
    with pytest.raises(ValidationError):
        _fr(f"System must persist data {sneaky} table.")

    # Cover several other Math styles for the same letter:
    math_variants = (
        "\U0001d428",  # MATHEMATICAL BOLD SMALL O
        "\U0001d45c",  # MATHEMATICAL ITALIC SMALL O
        "\U0001d490",  # MATHEMATICAL BOLD ITALIC SMALL O
        "\U0001d52c",  # MATHEMATICAL FRAKTUR SMALL O
        "\U0001d560",  # MATHEMATICAL DOUBLE-STRUCK SMALL O
        "\U0001d698",  # MATHEMATICAL MONOSPACE SMALL O
    )
    for o_variant in math_variants:
        text = f"{o_variant}r equivalent"
        assert find_forbidden_phrase(text) is not None, f"FAILED to catch {text!r}"
    # EXPECTED (Sprint F1): NFKC folds Math Alphanumeric Symbols to ASCII.


def test_fullwidth_caught() -> None:
    """Fullwidth Latin (U+FF01-U+FF5E) is NFKC-normalized to ASCII so a
    Fullwidth 'ｏ' substituted in ``or equivalent`` is caught.

    Common east-Asian IME input modes emit Fullwidth Latin by default,
    which makes this a high-probability "accidental" bypass that we now
    cover.
    """
    sneaky = "\uff4fr equivalent storage"  # ｏr equivalent
    matched = find_forbidden_phrase(sneaky)
    assert matched is not None and matched.lower() == "or equivalent"
    with pytest.raises(ValidationError):
        _fr(f"System must persist data {sneaky} table.")

    # Even more aggressive: ENTIRE phrase in Fullwidth Latin.
    full_phrase = "\uff4f\uff52\uff20\uff45\uff51\uff55\uff49\uff56\uff41\uff4c\uff45\uff4e\uff54"
    # U+FF20 is FULLWIDTH COMMERCIAL AT '＠'; let me use proper space:
    full_phrase = (
        "\uff4f\uff52"  # ｏｒ
        "\u3000"  # ideographic space (NFKC -> regular space)
        "\uff45\uff51\uff55\uff49\uff56\uff41\uff4c\uff45\uff4e\uff54"  # ｅｑｕｉｖａｌｅｎｔ
    )
    assert find_forbidden_phrase(full_phrase) is not None
    # EXPECTED (Sprint F1): NFKC folds Fullwidth Forms + ideographic space.


def test_latin_extended_caught() -> None:
    """Multiple Cyrillic substitutes in a single phrase are all folded.

    The text below uses Cyrillic 'о' (U+043E), 'е' (U+0435), 'і' (U+0456,
    Ukrainian I), and 'а' (U+0430) inside "or equivalent" -- a maximally
    adversarial mix.
    """
    sneaky = "\u043er \u0435qu\u0456v\u0430lent storage"  # оr еquіvаlent
    matched = find_forbidden_phrase(sneaky)
    assert matched is not None and matched.lower() == "or equivalent"
    with pytest.raises(ValidationError):
        _fr(f"System must persist data {sneaky} table.")
    # EXPECTED (Sprint F1): per-character homoglyph fold handles any
    # combination of substitutions, not just one.


def test_chinese_text_not_affected() -> None:
    """Han ideographs (CJK Unified Ideographs) are WHITELISTED in the
    homoglyph table generator -- they pass through unfolded, so a clean
    Chinese-language spec line contains no forbidden phrase.
    """
    text = "业务需求 must support concurrent access at 1000 RPS"
    assert find_forbidden_phrase(text) is None
    # And full schema construction works without error:
    fr = _fr(f"{text}.")
    assert "业务需求" in fr.text
    # Sanity: the Chinese chars survive the round-trip:
    assert "\u4e1a\u52a1\u9700\u6c42" in fr.text
    # EXPECTED (Sprint F1): HAN script is in WHITELIST_ALIASES, so no
    # Han character appears in HOMOGLYPH_TO_ASCII.


def test_arabic_text_not_affected() -> None:
    """Arabic script (Hebrew / Devanagari / ... too) is WHITELISTED.

    Legitimate Arabic spec text passes through the validator unmolested
    even though Arabic letters can be visually similar to ASCII (e.g.
    Arabic Letter HEH 'ه' looks like ASCII 'o').
    """
    text = "النظام يجب أن يدعم المستخدمين"
    assert find_forbidden_phrase(text) is None
    fr = _fr(f"System: {text}.")
    assert "\u0627\u0644\u0646\u0638\u0627\u0645" in fr.text  # النظام survived
    # And Hebrew:
    hebrew = "המערכת חייבת לתמוך במשתמשים מרובים"
    assert find_forbidden_phrase(hebrew) is None
    # And Devanagari:
    devanagari = "सिस्टम को कई उपयोगकर्ताओं का समर्थन करना चाहिए"
    assert find_forbidden_phrase(devanagari) is None
    # EXPECTED (Sprint F1): ARABIC / HEBREW / DEVANAGARI are in
    # WHITELIST_ALIASES at table-generation time.


def test_mixed_latin_cjk_passes_when_clean() -> None:
    """Mixed CJK + ASCII text with NO forbidden phrase passes cleanly.

    This pins the no-false-positive behavior: just because CJK appears
    alongside English does NOT cause the validator to flag anything.
    """
    text = "Implementation 实现 follows pattern from src/cache/redis.py"
    assert find_forbidden_phrase(text) is None
    fr = _fr(text)
    assert "实现" in fr.text

    # Korean (Hangul) + English:
    assert find_forbidden_phrase("Use the 캐시 module for fast lookups") is None
    # Japanese (Hiragana + Katakana) + English:
    assert find_forbidden_phrase("Implement キャッシュ via the ひらがな-named API") is None
    # EXPECTED (Sprint F1): HAN / HANGUL / HIRAGANA / KATAKANA are all
    # whitelisted, so mixed-script spec text passes cleanly.


def test_mixed_latin_cjk_caught_when_dirty() -> None:
    """Mixed CJK + English with a forbidden ENGLISH phrase is still caught.

    CJK characters around the forbidden phrase do NOT shield it from the
    validator -- the regex still matches the ASCII portion. This is the
    dual of ``test_mixed_latin_cjk_passes_when_clean``: CJK alone is
    fine, but it can't be used as camouflage around a forbidden English
    phrase.
    """
    # CJK characters preceding the soft-language phrase
    text = "Use cache 实现 or equivalent strategy for the 缓存 layer"
    matched = find_forbidden_phrase(text)
    assert matched is not None and matched.lower() == "or equivalent"
    with pytest.raises(ValidationError):
        _fr(text)

    # Also verify with the Chinese "or" character 或 mixed in -- the
    # Chinese 或 is NOT folded to ASCII (it's a HAN ideograph, whitelisted),
    # but the trailing English "or equivalent" still triggers.
    text2 = "Use cache 或 fallback, but no 'or equivalent' wording allowed"
    matched2 = find_forbidden_phrase(text2)
    assert matched2 is not None and matched2.lower() == "or equivalent"

    # Mixed Hangul + forbidden phrase
    text3 = "캐시 또는 'TBD' marker should be resolved"
    matched3 = find_forbidden_phrase(text3)
    assert matched3 is not None and matched3.upper() == "TBD"
    # EXPECTED (Sprint F1): CJK whitelist preserves the script, but
    # ASCII forbidden phrases inside the same string still fire.
