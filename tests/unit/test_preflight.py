"""Tests for preflight check."""

from devloop.spec_phase.preflight import preflight


def test_passes_typical_chinese_request():
    res = preflight("给商品页加用户评论功能")
    assert res.ok


def test_passes_typical_english_request():
    res = preflight("Add user authentication to the API")
    assert res.ok


def test_fails_too_short():
    res = preflight("x")
    assert not res.ok
    assert "short" in res.reason.lower() or "char" in res.reason.lower()


def test_fails_no_verb():
    res = preflight("product page rating")
    assert not res.ok


def test_fails_only_punctuation():
    res = preflight("...........................")
    assert not res.ok


def test_passes_with_feature_colon_pattern():
    # "Feature: ..." common in tickets — verb 'add' satisfies anyway
    res = preflight("Feature: add a search bar")
    assert res.ok
