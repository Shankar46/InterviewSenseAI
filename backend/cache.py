# backend/cache.py
#
# Simple in-process TTL cache. Two things this buys you:
#   1. Identical "notes" requests (same topic/mode/task/doc) within the TTL
#      window are served instantly instead of re-hitting the HF inference
#      API — this is your single biggest latency + cost win, since the LLM
#      call is by far the slowest part of every request (seconds to
#      low-minutes per your own 240s frontend timeout).
#   2. Reduces traffic to the upstream model provider, which matters if
#      you're on a rate-limited or pay-per-call HF endpoint.
#
# Not suitable for caching across multiple turns of a stateful conversation
# (career roadmap, interview Q&A) — only used for the stateless "study notes"
# generation path where same input -> same expected output.
#
# Swap to Redis (see bottom) if you run multiple processes/instances and want
# a shared cache instead of one-per-process.

import hashlib
import time
import threading

_lock = threading.Lock()
_store: dict[str, tuple[float, str]] = {}  # key -> (expires_at, value)

DEFAULT_TTL = 60 * 30  # 30 minutes — long enough to catch repeat student queries
MAX_ENTRIES = 2000     # crude bound so a busy day doesn't grow memory unbounded


def make_key(*parts: str) -> str:
    raw = "||".join(p or "" for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get(key: str):
    now = time.time()
    with _lock:
        entry = _store.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if now >= expires_at:
            del _store[key]
            return None
        return value


def set(key: str, value: str, ttl: int = DEFAULT_TTL):
    with _lock:
        if len(_store) >= MAX_ENTRIES:
            # Evict the oldest ~10% rather than doing per-request LRU bookkeeping
            oldest = sorted(_store.items(), key=lambda kv: kv[1][0])[: max(1, MAX_ENTRIES // 10)]
            for k, _ in oldest:
                _store.pop(k, None)
        _store[key] = (time.time() + ttl, value)


# ── Redis-backed variant (use when scaling beyond one process) ───────────
# import redis, os
# _r = redis.from_url(os.getenv("REDIS_URL"))
# def get(key): return _r.get(key)
# def set(key, value, ttl=DEFAULT_TTL): _r.setex(key, ttl, value)
