import os
from functools import wraps

from flask import after_this_request, current_app, jsonify, request

from backend import llm_meter
from backend.db import get_shared_key_usage, refund_shared_key_request, reserve_shared_key_request
from backend.llm_errors import LLMQuotaExceeded


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


def _remaining(user_id: int, limit: int) -> int:
    return max(0, limit - get_shared_key_usage(user_id))


def shared_key_daily_quota(view=None, *, lazy: bool = False):
    """Enforce a per-user daily cap, but only when the request uses the SERVER key.

    You are charged for AI answers you actually received:
      * the slot is reserved up front (atomic, so parallel requests cannot overspend)
      * it is GIVEN BACK if the request failed, or if no AI call succeeded
        (cache hit, greeting, "yes"/"status" commands, provider outage, bad output)

    lazy=False (default): when the allowance is used up, answer 429 immediately.
    lazy=True: let the request run. Requests that never need the AI still work
        (progress refresh, "yes", "status"); the first real AI call raises
        LLMQuotaExceeded (HTTP 429, same message). Only use this on endpoints
        that let LLMError propagate instead of catching it.
    """
    def decorator(view):
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

            user_id = request.user["user_id"]
            limit = shared_key_daily_limit()
            allowed, remaining = reserve_shared_key_request(user_id, limit)
            shown = {"remaining": remaining}      # read when the response is finally built

            @after_this_request
            def add_shared_key_headers(response):
                response.headers["X-Shared-Key-Mode"] = "shared"
                response.headers["X-Shared-Key-Remaining"] = str(shown["remaining"])
                response.headers["X-Shared-Key-Limit"] = str(limit)
                return response

            if not allowed:
                exhausted = LLMQuotaExceeded(
                    f"Your shared Groq-key limit is used up for today "
                    f"({limit} AI questions). It resets at 00:00 UTC. Add your own "
                    "Groq API key in settings to continue with your own account.",
                    extra={"quota": {
                        "daily_limit": limit,
                        "requests_remaining": remaining,
                        "reset_at": "00:00 UTC",
                    }},
                )
                if not lazy:
                    return jsonify(exhausted.to_dict()), 429
                llm_meter.block(exhausted)

            try:
                response = current_app.make_response(view(*args, **kwargs))
            except Exception:
                if allowed:
                    refund_shared_key_request(user_id)
                shown["remaining"] = _remaining(user_id, limit)
                raise

            charged = response.status_code < 400 and llm_meter.successful_calls() > 0
            if allowed and not charged:
                refund_shared_key_request(user_id)
            shown["remaining"] = _remaining(user_id, limit)
            return response

        return wrapped

    return decorator(view) if view is not None else decorator
