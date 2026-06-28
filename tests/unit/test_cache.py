"""Tests for the SQLite cache layer."""


from devloop.cache import CacheBackend, hash_args


def test_hash_args_deterministic():
    h1 = hash_args("tool", {"x": 1, "y": 2})
    h2 = hash_args("tool", {"y": 2, "x": 1})
    assert h1 == h2  # sort_keys=True


def test_skeleton_roundtrip(tmp_path):
    cache = CacheBackend(tmp_path / "cache.db")
    assert cache.get_skeleton("abc") is None
    payload = {"text": "hello", "files": 42}
    cache.set_skeleton("abc", "/repo", payload)
    out = cache.get_skeleton("abc")
    assert out == payload
    cache.close()


def test_tool_cache_roundtrip(tmp_path):
    cache = CacheBackend(tmp_path / "cache.db")
    assert cache.get_tool("abc", "file_read", {"path": "x"}) is None
    cache.set_tool("abc", "file_read", {"path": "x"}, "contents")
    assert cache.get_tool("abc", "file_read", {"path": "x"}) == "contents"
    cache.close()


def test_invalidate_commit(tmp_path):
    cache = CacheBackend(tmp_path / "cache.db")
    cache.set_skeleton("abc", "/r", {"x": 1})
    cache.set_tool("abc", "t", {"a": 1}, "r")
    n = cache.invalidate_commit("abc")
    assert n == 2
    assert cache.get_skeleton("abc") is None
    assert cache.get_tool("abc", "t", {"a": 1}) is None
    cache.close()


def test_ttl_eviction(tmp_path):
    cache = CacheBackend(tmp_path / "cache.db", ttl_days=0)  # immediate expiration
    cache.set_skeleton("abc", "/r", {"x": 1})
    import time
    time.sleep(0.01)
    # With ttl_days=0 the freshness check is `now - created > 0` -> always True
    assert cache.get_skeleton("abc") is None
    cache.close()
