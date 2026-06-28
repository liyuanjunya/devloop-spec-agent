"""Tests for the JSON extraction helper."""

import pytest

from devloop.llm.json_helpers import extract_json


def test_extracts_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extracts_json_in_code_fence():
    text = """
Some prose.

```json
{
  "foo": "bar",
  "x": [1, 2, 3]
}
```

trailing prose.
"""
    assert extract_json(text) == {"foo": "bar", "x": [1, 2, 3]}


def test_extracts_array():
    assert extract_json("[1, 2, 3]") == [1, 2, 3]


def test_heuristic_recovery_when_braced():
    text = "Here is the answer: { \"k\": 42 } — done"
    assert extract_json(text) == {"k": 42}


def test_raises_on_no_json():
    with pytest.raises(ValueError):
        extract_json("definitely not json")
