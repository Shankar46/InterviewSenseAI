import os
from functools import wraps

from flask import after_this_request, jsonify, request

from backend.db import get_shared_key_usage, reserve_shared_key_request


def shared_key_daily_limit() -> int:
    raw_limit = os.getenv("SHARED_KEY_DAILY_LIMIT", "5")
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise RuntimeError("SHARED_KEY_DAILY_LIMIT must be a positive integer.") from exc
    if limit < 1:
        raise RuntimeError("SHARED_KEY_DAILY_LIMIT must be a positive integer.")
    return limit


def shared_key_usage(user_id: int) -> dict:
    limit = shared_key_daily_limit()
    used = get_shared_key_usage(user_id)
    return {
        "server_key_configured": bool(os.getenv("GROQ_API_KEY")),
        "daily_limit": limit,
        "requests_used": used,
        "requests_remaining": max(0, limit - used),
        "reset_at": "00:00 UTC",
    }


def shared_key_daily_quota(view):
    """Enforce a per-user daily cap only when a request uses the server key."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        api_key = request.headers.get("X-Groq-API-Key", "").strip()
        if request.path == "/api/evaluate":
            api_key = api_key or request.form.get("api_key", "").strip()
        if api_key:
            @after_this_request
            def add_personal_key_header(response):
                response.headers["X-Shared-Key-Mode"] = "personal"
                return response

            return view(*args, **kwargs)

        if not os.getenv("GROQ_API_KEY"):
            return jsonify({
                "status": "error",
                "message": (
                    "The server Groq key is not configured. Add your own Groq API key "
                    "in settings or ask the administrator to configure GROQ_API_KEY."
                ),
            }), 503

        limit = shared_key_daily_limit()
        allowed, remaining = reserve_shared_key_request(
            request.user["user_id"], limit
        )

        @after_this_request
        def add_shared_key_headers(response):
            response.headers["X-Shared-Key-Mode"] = "shared"
            response.headers["X-Shared-Key-Remaining"] = str(remaining)
            response.headers["X-Shared-Key-Limit"] = str(limit)
            return response

        if not allowed:
            return jsonify({
                "status": "error",
                "message": (
                    f"Your shared Groq-key limit is used up for today "
                    f"({limit} AI questions). It resets at 00:00 UTC. Add your own "
                    "Groq API key in settings to continue with your own account."
                ),
                "quota": {
                    "daily_limit": limit,
                    "requests_remaining": remaining,
                    "reset_at": "00:00 UTC",
                },
            }), 429

        return view(*args, **kwargs)

    return wrapped
