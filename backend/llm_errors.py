# backend/llm_errors.py
#
# Everything that can go wrong when we talk to the AI provider, as typed errors.
#
# Why this exists: the old code caught every failure and returned a string like
# "⚠️ Generation service temporarily unavailable" with HTTP 200. The app then
# treated that string as a real answer: it was cached-or-not by luck, it used up
# the student's daily quota, and (in the quiz flow) it was graded as a FAILED day.
# Now a failure is an exception that carries the right HTTP status, a message
# that is safe to show, and whether trying again can help.


class LLMError(Exception):
    http_status = 502
    code = "llm_error"
    retryable = True

    def __init__(self, user_message, *, http_status=None, code=None,
                 retryable=None, retry_after=None, extra=None):
        super().__init__(user_message)
        self.user_message = user_message
        if http_status is not None:
            self.http_status = http_status
        if code is not None:
            self.code = code
        if retryable is not None:
            self.retryable = retryable
        self.retry_after = retry_after
        self.extra = extra or {}

    def to_dict(self) -> dict:
        # "message" is the field the frontend already displays for any non-OK reply.
        return {
            "status": "error",
            "message": self.user_message,
            "code": self.code,
            "retryable": self.retryable,
            **self.extra,
        }


class LLMNotConfigured(LLMError):
    """Server-side problem a retry cannot fix (missing/rejected key, unknown model)."""
    http_status = 503
    code = "llm_not_configured"
    retryable = False


class LLMInvalidKey(LLMError):
    """The USER's own (BYOK) key was rejected. 400 on purpose, never 401:
    the frontend logs the user out on any 401."""
    http_status = 400
    code = "invalid_api_key"
    retryable = False


class LLMRateLimited(LLMError):
    http_status = 429
    code = "provider_rate_limited"


class LLMUnavailable(LLMError):
    http_status = 503
    code = "provider_unavailable"


class LLMBadOutput(LLMError):
    """The model answered, but not in a form we can trust (bad/short/empty JSON)."""
    http_status = 502
    code = "bad_model_output"


class LLMQuotaExceeded(LLMError):
    http_status = 429
    code = "shared_quota_exhausted"
    retryable = False


def _retry_after(exc) -> int | None:
    try:
        raw = exc.response.headers.get("retry-after")
        return max(1, int(float(raw))) if raw else None
    except Exception:
        return None


def classify_provider_error(exc: Exception, *, byok: bool, model: str) -> LLMError:
    """Turn a raw provider/network exception into the right LLMError."""
    status = getattr(exc, "status_code", None)

    if status in (401, 403):
        if byok:
            return LLMInvalidKey(
                "Groq rejected your API key. Check the key in Settings, "
                "or remove it to use the shared key."
            )
        return LLMNotConfigured(
            "The server's AI key was rejected by Groq. Please tell the administrator."
        )
    if status == 402:
        who = "Your Groq account has" if byok else "The AI service has"
        return LLMUnavailable(f"{who} no available credits right now.", retryable=False)
    if status == 404:
        return LLMNotConfigured(
            f"The AI model '{model}' is not available to this Groq account. "
            "Set GROQ_MODEL to an active model."
        )
    if status == 429:
        if byok:
            return LLMRateLimited(
                "Your Groq account's rate limit was reached. Wait a moment and try again.",
                retry_after=_retry_after(exc),
            )
        return LLMRateLimited(
            "The AI service is busy right now. Please try again in a moment.",
            http_status=503, retry_after=_retry_after(exc),
        )
    if status in (400, 413, 422):
        return LLMError(
            "The AI provider could not process this request (it may be too long).",
            code="provider_bad_request", retryable=False,
        )
    # 5xx, timeouts, connection resets, DNS: no status or a server-side one.
    return LLMUnavailable("The AI service is temporarily unavailable. Please try again in a moment.")
