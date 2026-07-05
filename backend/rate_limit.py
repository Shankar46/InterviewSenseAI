# backend/rate_limit.py
#
# Lightweight in-process rate limiter. No Redis dependency required, but the
# limiter object is process-local — if you scale to multiple gunicorn worker
# *processes* (not threads), each process gets its own counters, so effective
# limits multiply by worker count. That's fine for a single small VM; if you
# move to multiple instances/containers behind a load balancer, swap the
# in-memory store below for Redis (the public interface stays the same —
# see _RedisStore stub at the bottom).

import time
import threading
from collections import defaultdict, deque
from functools import wraps
from flask import request, jsonify

_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)


def _client_key():
    # Prefer authenticated user if available (set by login_required upstream),
    # fall back to IP. Authenticated keying prevents one user on a shared NAT
    # from rate-limiting everyone else on that IP.
    user = getattr(request, "user", None)
    if user:
        return f"user:{user['user_id']}"
    fwd = request.headers.get("X-Forwarded-For", "")
    ip = fwd.split(",")[0].strip() if fwd else request.remote_addr
    return f"ip:{ip}"


def rate_limit(max_requests: int, window_seconds: int, scope: str = "default"):
    """Decorator: cap a route to max_requests per window_seconds per client.

    Usage:
        @app.route("/api/auth/login", methods=["POST"])
        @rate_limit(5, 60, scope="login")   # 5 attempts / minute / IP
        def auth_login(): ...
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            key = f"{scope}:{_client_key()}"
            now = time.monotonic()
            with _lock:
                dq = _hits[key]
                while dq and now - dq[0] > window_seconds:
                    dq.popleft()
                if len(dq) >= max_requests:
                    retry_after = max(1, int(window_seconds - (now - dq[0])))
                    resp = jsonify({
                        "status": "error",
                        "message": "Too many requests. Please slow down.",
                    })
                    resp.status_code = 429
                    resp.headers["Retry-After"] = str(retry_after)
                    return resp
                dq.append(now)
            return f(*args, **kwargs)
        return wrapped
    return decorator


def periodic_cleanup(interval_seconds: int = 300):
    """Background thread to stop the _hits dict growing unbounded from
    one-off / abandoned client keys. Call once at app startup."""
    def _loop():
        while True:
            time.sleep(interval_seconds)
            now = time.monotonic()
            with _lock:
                # Use a safe, longer inactivity threshold (e.g., 1 hour) so that
                # rate limit windows larger than interval_seconds are not wiped prematurely.
                dead = [k for k, dq in _hits.items() if not dq or now - dq[-1] > 3600]
                for k in dead:
                    del _hits[k]
    t = threading.Thread(target=_loop, daemon=True)
    t.start()



# ── Redis-backed variant (use when scaling beyond one process) ───────────
# from redis import Redis
# class _RedisStore:
#     def __init__(self, url): self.r = Redis.from_url(url)
#     def allow(self, key, max_requests, window_seconds):
#         pipe = self.r.pipeline()
#         now = time.time()
#         pipe.zremrangebyscore(key, 0, now - window_seconds)
#         pipe.zadd(key, {str(now): now})
#         pipe.zcard(key)
#         pipe.expire(key, window_seconds)
#         _, _, count, _ = pipe.execute()
#         return count <= max_requests