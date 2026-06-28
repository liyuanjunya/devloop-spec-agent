"""Hypothesis fuzz tests for the soft-language schema validators (DevLoop Sprint F2 — A4).

Where ``test_soft_language_adversarial.py`` pins the boundary one case at a time,
this file generates *thousands* of random separator / plural mutations of every
canonical forbidden phrase and asserts the validator catches them all. The fuzz
also pins a curated set of negative examples (``if-statement``, ``or-pattern``,
ticket references like ``TBD-1234``) to guard against regex over-reach.

These tests run on every CI build (~3-4 seconds for 500 examples per case) and
are the failure mode that flips when a future bypass channel is discovered.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from devloop.spec_phase.schemas.spec import find_forbidden_phrase

# ---------------------------------------------------------------------------
# Strategy material
# ---------------------------------------------------------------------------

# Canonical phrases the schema layer must reject. Tuples represent the
# whitespace-joined English form; the fuzz inserts arbitrary separators
# between tokens and optional plural suffixes after the last token.
CANONICAL_PHRASES: list[tuple[str, ...]] = [
    ("or", "equivalent"),
    ("or", "similar"),
    ("TBD",),
    ("to", "be", "decided"),
    ("to", "be", "determined"),
    ("if", "needed"),
    ("as", "needed"),
    ("TBA",),
    ("placeholder",),
]

# Inter-token separators the regex SEP class must accept. Covers ASCII
# whitespace, hyphen, underscore, period, middle-dot, and the named
# zero-width Cf chars (ZWSP / ZWNJ / ZWJ).
SEPARATORS: list[str] = [
    " ",
    "  ",
    "\t",
    "-",
    "_",
    ".",
    "\u00b7",   # middle dot
    "\u200b",   # zero-width space
    "\u200c",   # zero-width non-joiner
    "\u200d",   # zero-width joiner
]

# Plural / suffix mutations on the trailing token. Only ``or equivalent``
# and ``or similar`` are documented as pluralizable; the others are not
# expected to pluralize (they're abbreviations or have no English plural
# as a soft phrase).
PLURAL_SUFFIXES: list[str] = ["", "s", "es"]

# Plural-friendly phrases the validator MUST catch even with ``s`` / ``es``.
PLURAL_FRIENDLY: set[tuple[str, ...]] = {
    ("or", "equivalent"),
    ("or", "similar"),
}


# ---------------------------------------------------------------------------
# Fuzz 1 — every separator combination on every canonical phrase
# ---------------------------------------------------------------------------


@given(
    phrase=st.sampled_from(CANONICAL_PHRASES),
    separators=st.lists(
        st.sampled_from(SEPARATORS), min_size=0, max_size=3
    ),
)
@settings(
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_fuzz_separator_mutations(
    phrase: tuple[str, ...], separators: list[str]
) -> None:
    """For every canonical phrase, joining tokens with ANY separator from
    ``SEPARATORS`` (or any short prefix thereof, cycling) MUST be caught."""
    # Pad the separator list so we always have one per token gap.
    if len(separators) < len(phrase) - 1:
        separators = separators + [" "] * (len(phrase) - 1 - len(separators))
    text = ""
    for i, word in enumerate(phrase):
        text += word
        if i < len(phrase) - 1:
            text += separators[i % len(separators)] if separators else " "
    result = find_forbidden_phrase(text)
    assert result is not None, f"FAILED to catch mutation: {text!r}"


# ---------------------------------------------------------------------------
# Fuzz 2 — plural-suffix mutations on the trailing token
# ---------------------------------------------------------------------------


@given(
    phrase=st.sampled_from(CANONICAL_PHRASES),
    suffix=st.sampled_from(PLURAL_SUFFIXES),
)
@settings(
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_fuzz_plural_mutations(
    phrase: tuple[str, ...], suffix: str
) -> None:
    """Appending a plural-ish suffix to the last token must NOT defeat the
    validator on the two phrases that are documented as pluralizable.

    For non-pluralizable phrases (``TBD``, ``to be decided``, ``if needed``)
    the result is informational — we don't assert either way because plural
    forms of those are not real soft language.
    """
    text = " ".join((*phrase[:-1], phrase[-1] + suffix))
    result = find_forbidden_phrase(text)
    if phrase in PLURAL_FRIENDLY:
        assert result is not None, f"FAILED to catch plural mutation: {text!r}"
    # Empty-suffix case is just the canonical singular and must always match.
    if suffix == "":
        assert result is not None, f"FAILED to catch canonical singular: {text!r}"


# ---------------------------------------------------------------------------
# Fuzz 3 — combined separator + plural + parenthesized middle word
# ---------------------------------------------------------------------------


@given(
    phrase=st.sampled_from(
        [("if", "needed"), ("as", "needed"), ("or", "equivalent"), ("or", "similar")]
    ),
    open_paren=st.booleans(),
    close_paren=st.booleans(),
    separator=st.sampled_from(SEPARATORS),
    suffix=st.sampled_from(PLURAL_SUFFIXES),
)
@settings(
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_fuzz_combined_separator_paren_plural(
    phrase: tuple[str, str],
    open_paren: bool,
    close_paren: bool,
    separator: str,
    suffix: str,
) -> None:
    """Combine separator + optional parens + optional plural — all the
    boundary-mutation vectors at once. Should still be caught for every
    combination on the two-word phrases listed above.

    ``needed`` is not pluralizable as a soft phrase (``if neededs`` /
    ``as neededs`` are not real soft language), so we coerce the suffix to
    empty for those phrases and only fuzz parens / separator on them.
    """
    if phrase[1] == "needed":
        suffix = ""
    second = phrase[1] + suffix
    lhs = phrase[0] + separator
    if open_paren:
        lhs += "("
    text = lhs + second
    if close_paren:
        text += ")"
    result = find_forbidden_phrase(text)
    assert result is not None, (
        f"FAILED to catch combined mutation: {text!r} "
        f"(phrase={phrase}, sep={separator!r}, suffix={suffix!r}, "
        f"open={open_paren}, close={close_paren})"
    )


# ---------------------------------------------------------------------------
# Negative-fuzz — curated false-positive guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # Hyphenated identifiers that share a token with a forbidden phrase
        "if-statement compatibility",
        "or-pattern matching",
        # Plain English that uses the same connectives but no forbidden tail
        "for several reasons we proceed",
        "Option A is preferred over Option B",
        "to be implemented in next sprint",
        # Ticket-reference shapes (TBD- / TBA- followed by alphanumerics)
        "TBD-1234",
        "TBA-99",
        "TBD_1234",
        # Identifier-style with the forbidden token jammed inside
        "PLACEHOLDERvalue",
        "xyzTBD",
        "TBDxyz",
        # No-gap concatenation must NOT trigger ``if needed`` / ``as needed``
        "ifneeded",
        "asneeded",
        # Real words that share a stem
        "or equivalency check passes",
    ],
)
def test_negative_examples_not_falsely_flagged(text: str) -> None:
    """Curated set of look-alike strings that must NOT trigger the validator.

    ``placeholder_value`` is the documented debatable case — we don't include
    it here because either match outcome is acceptable per the F2 design.
    """
    result = find_forbidden_phrase(text)
    assert result is None, f"FALSE POSITIVE on {text!r} -- matched: {result!r}"


def test_placeholder_underscore_identifier_documented_behavior() -> None:
    """``placeholder_value`` is a debatable case: ``_`` is a word char in
    Python's regex ``\\w``, so ``\\bplaceholder\\b`` does NOT see a boundary
    between ``placeholder`` and ``_value``. The current design leaves this
    as a non-match — document the behavior so any future change is
    deliberate."""
    assert find_forbidden_phrase("placeholder_value") is None
    # And the plural variant likewise (``placeholders_value``) — the trailing
    # ``s`` lands inside the identifier so no word boundary is found.
    assert find_forbidden_phrase("placeholders_value") is None
