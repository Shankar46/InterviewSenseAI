# backend/tests/test_cache.py
import time
from backend import cache


def test_set_and_get_roundtrip():
    key = cache.make_key("a", "b", "c")
    cache.set(key, "hello", ttl=10)
    assert cache.get(key) == "hello"


def test_missing_key_returns_none():
    assert cache.get("nonexistent-key-xyz") is None


def test_expired_entry_returns_none():
    key = cache.make_key("expiring")
    cache.set(key, "value", ttl=0)  # already expired
    time.sleep(0.01)
    assert cache.get(key) is None


def test_same_inputs_produce_same_key():
    k1 = cache.make_key("notes", "task", "10 Marks", "machine learning")
    k2 = cache.make_key("notes", "task", "10 Marks", "machine learning")
    assert k1 == k2


def test_different_inputs_produce_different_keys():
    k1 = cache.make_key("notes", "task", "10 Marks", "machine learning")
    k2 = cache.make_key("notes", "task", "5 Marks", "machine learning")
    assert k1 != k2