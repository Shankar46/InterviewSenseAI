# backend/llm_meter.py
#
# Per-request bookkeeping shared by the quota decorator and the LLM gateway.
#
#  * success counter  -> the quota is charged only if the AI really answered
#                        (cache hits, greetings, "yes"/"status" commands are free)
#  * block flag       -> when the user's shared-key allowance is used up, requests
#                        that never need the AI still work; the first real AI call
#                        raises LLMQuotaExceeded.
#
# Everything is a no-op outside a Flask request (scripts, tests of pure helpers).
from flask import g, has_request_context


def block(err: Exception) -> None:
    if has_request_context():
        g.llm_block = err


def check() -> None:
    """Called right before every provider call."""
    if has_request_context():
        err = g.get("llm_block")
        if err is not None:
            raise err


def record_success() -> None:
    if has_request_context():
        g.llm_ok_calls = g.get("llm_ok_calls", 0) + 1


def successful_calls() -> int:
    return g.get("llm_ok_calls", 0) if has_request_context() else 0
