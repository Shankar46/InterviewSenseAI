# backend/tests/test_llm_outage_and_quota.py
#
# End-to-end tests for the "AI outage" bugs found in the audit. Real Flask app,
# real (temporary) database, and a scripted fake AI provider that can fail on demand.
#
#   * outage used to return HTTP 200 with a "⚠️ ..." string and burn the daily quota
#   * an outage during a quiz recorded the student's day as FAILED
#   * an outage while creating a roadmap saved a generic plan as the real one
#   * at the daily limit even "yes" / "status" / progress refresh were blocked
import uuid
from types import SimpleNamespace

import pytest

from backend.db import load_session_state
from backend.tests.llm_fakes import ProviderError, career, plan_json, used, verdict

LIMIT = 3


@pytest.fixture(autouse=True)
def _small_allowance(monkeypatch):
    monkeypatch.setenv("SHARED_KEY_DAILY_LIMIT", str(LIMIT))


def study(client, headers, chat, topic=None, extra_headers=None):
    topic = topic or f"explain {uuid.uuid4().hex} in detail"
    return client.post("/api/workspace/generate", headers={**headers, **(extra_headers or {})},
                       data={"topic": topic, "mode": "5M", "chat_id": chat})


def day1_status(resp):
    return resp.get_json()["tracker"][0]["status"]


@pytest.fixture()
def quiz_ready(client, make_user, provider, chat_id):
    """A student with a roadmap, Day 1 started and the quiz issued (3 free steps after the plan)."""
    headers, _ = make_user()
    provider.push(plan_json())
    assert career(client, headers, chat_id, "Python Developer").status_code == 200
    assert career(client, headers, chat_id, "yes").status_code == 200
    assert "Quiz" in career(client, headers, chat_id, "done").get_json()["text"]
    return headers


# ── 1. outage: honest status code, nothing charged ────────────────────────

def test_outage_is_a_503_not_a_200_with_a_warning_string(client, make_user, provider, chat_id):
    headers, _ = make_user()
    provider.push(ProviderError(None))                       # connection reset / timeout
    r = study(client, headers, chat_id)
    body = r.get_json()
    assert r.status_code == 503
    assert body["status"] == "error" and body["code"] == "provider_unavailable" and body["retryable"] is True
    assert "answer" not in body and "⚠️" not in body["message"]


def test_outage_does_not_burn_the_daily_quota(client, make_user, provider, chat_id):
    headers, _ = make_user()
    provider.push(ProviderError(500), ProviderError(502))
    r = study(client, headers, chat_id)
    assert r.headers["X-Shared-Key-Remaining"] == str(LIMIT)       # the header the UI badge shows is correct too
    study(client, headers, chat_id)
    assert used(client, headers) == 0


def test_a_successful_answer_costs_exactly_one(client, make_user, provider, chat_id):
    headers, _ = make_user()
    provider.push("Real notes about the topic.")
    r = study(client, headers, chat_id)
    assert r.status_code == 200 and r.get_json()["answer"] == "Real notes about the topic."
    assert r.headers["X-Shared-Key-Remaining"] == str(LIMIT - 1)
    assert used(client, headers) == 1


def test_cache_hits_and_greetings_are_free(client, make_user, provider, chat_id):
    headers, _ = make_user()
    topic = f"explain caching {uuid.uuid4().hex}"
    provider.push("first answer")
    study(client, headers, chat_id, topic)
    again = study(client, headers, chat_id, topic)                 # served from cache: no provider call
    assert again.get_json()["answer"] == "first answer" and provider.calls == 1
    study(client, headers, chat_id, "hello")                       # greeting never reaches the model
    assert used(client, headers) == 1


def test_validation_errors_do_not_cost_quota(client, make_user, provider):
    headers, _ = make_user()
    r = client.post("/api/workspace/generate", headers=headers, data={"topic": "x", "chat_id": "default"})
    assert r.status_code == 400
    assert used(client, headers) == 0


def test_evaluate_endpoint_outage_is_a_503_and_free(client, make_user, provider):
    headers, _ = make_user()
    provider.push(ProviderError(503))
    r = client.post("/api/evaluate", headers=headers, data={"topic": "SQL", "answer": "joins combine tables"})
    assert r.status_code == 503 and r.get_json()["code"] == "provider_unavailable"
    assert used(client, headers) == 0


# ── 2. key problems must never look like a login problem ──────────────────

def test_rejected_server_key_is_503_not_401(client, make_user, provider, chat_id):
    headers, _ = make_user()
    provider.push(ProviderError(401))
    r = study(client, headers, chat_id)
    assert r.status_code == 503 and r.get_json()["code"] == "llm_not_configured"
    assert r.get_json()["retryable"] is False


def test_rejected_personal_key_is_400_not_401(client, make_user, provider, chat_id):
    """A 401 makes the frontend log the user out, so a bad BYOK key must never be one."""
    headers, _ = make_user()
    provider.push(ProviderError(401))
    r = study(client, headers, chat_id, extra_headers={"X-Groq-API-Key": "gsk_not_valid"})
    assert r.status_code == 400 and r.get_json()["code"] == "invalid_api_key"
    assert client.get("/api/auth/me", headers=headers).status_code == 200      # still logged in


def test_personal_key_never_touches_the_shared_quota(client, make_user, provider, chat_id):
    headers, _ = make_user()
    provider.push("answer with my own key")
    r = study(client, headers, chat_id, extra_headers={"X-Groq-API-Key": "gsk_mine"})
    assert r.status_code == 200 and r.headers["X-Shared-Key-Mode"] == "personal"
    assert used(client, headers) == 0


# ── 3. quiz: an outage must never fail the student's day ──────────────────

def test_outage_during_quiz_does_not_mark_the_day_failed(client, make_user, provider, chat_id, quiz_ready):
    headers = quiz_ready
    before = used(client, headers)
    provider.push(ProviderError(503))
    r = career(client, headers, chat_id, "Decorators wrap a function and return a new function.")
    assert r.status_code == 503 and r.get_json()["retryable"] is True

    status = career(client, headers, chat_id, "status")             # no AI call needed
    assert day1_status(status) == "pending"                          # was "failed" before the fix
    assert load_session_state(chat_id)["awaiting_answers"] is True   # the quiz is still open
    assert used(client, headers) == before                           # and nothing was charged


def test_retrying_the_same_answer_after_an_outage_works(client, make_user, provider, chat_id, quiz_ready):
    headers = quiz_ready
    provider.push(ProviderError(500), verdict(8))
    answer = "Decorators wrap a function and return a new function."
    assert career(client, headers, chat_id, answer).status_code == 503
    r = career(client, headers, chat_id, answer)
    assert r.status_code == 200 and "PASSED" in r.get_json()["text"] and "8/10" in r.get_json()["text"]
    assert day1_status(r) == "completed"
    assert used(client, headers) == 2                                # plan + the one successful grading


def test_a_real_low_score_is_still_a_real_fail(client, make_user, provider, chat_id, quiz_ready):
    provider.push(verdict(3, "Missing the key idea."))
    r = career(client, quiz_ready, chat_id, "I do not know")
    assert r.status_code == 200 and "FAILED" in r.get_json()["text"] and day1_status(r) == "failed"


def test_unusable_model_output_twice_is_an_error_not_a_failed_day(client, make_user, provider, chat_id, quiz_ready):
    headers = quiz_ready
    before = used(client, headers)
    calls_before = provider.calls
    provider.push("Looks good to me!", "Honestly great answer.")    # never valid JSON
    r = career(client, headers, chat_id, "Decorators wrap functions.")
    assert r.status_code == 502 and r.get_json()["code"] == "bad_model_output"
    assert provider.calls - calls_before == 2                         # one retry, then stop
    assert day1_status(career(client, headers, chat_id, "status")) == "pending"
    assert used(client, headers) == before


def test_one_bad_reply_then_a_good_one_costs_one_request(client, make_user, provider, chat_id, quiz_ready):
    headers = quiz_ready
    before = used(client, headers)
    provider.push("**STATUS:** PASS", verdict(9))                   # the format that used to be graded FAIL / 0
    r = career(client, headers, chat_id, "Decorators wrap functions.")
    assert r.status_code == 200 and day1_status(r) == "completed"
    assert used(client, headers) == before + 1


# ── 4. roadmap creation ───────────────────────────────────────────────────

def test_outage_while_creating_a_roadmap_saves_nothing(client, make_user, provider, chat_id):
    headers, _ = make_user()
    provider.push(ProviderError(503))
    r = career(client, headers, chat_id, "Python Developer")
    assert r.status_code == 503
    assert load_session_state(chat_id) is None        # used to hold a generic "REST API Design" plan
    assert used(client, headers) == 0
    provider.push(plan_json())
    ok = career(client, headers, chat_id, "Python Developer")        # the retry starts from scratch
    assert ok.status_code == 200 and len(ok.get_json()["tracker"]) == 30


def test_the_saved_plan_is_the_ai_plan_not_a_generic_fallback(client, make_user, provider, chat_id):
    headers, _ = make_user()
    provider.push(plan_json())
    career(client, headers, chat_id, "Python Developer")
    plan = load_session_state(chat_id)["day_plan"]
    assert [d["topic"] for d in plan[:2]] == ["AI Topic 1", "AI Topic 2"]
    assert len(plan) == 30 and all(d["day"] == i + 1 for i, d in enumerate(plan))


def test_an_incomplete_plan_is_rejected_not_padded_with_filler(client, make_user, provider, chat_id):
    headers, _ = make_user()
    provider.push(plan_json(20), plan_json(29))                      # too short, twice
    r = career(client, headers, chat_id, "Python Developer")
    assert r.status_code == 502 and r.get_json()["code"] == "bad_model_output"
    assert load_session_state(chat_id) is None


# ── 5. at the limit: free actions keep working, AI calls are blocked ──────

def test_at_the_limit_commands_that_need_no_ai_still_work(client, make_user, provider, chat_id, monkeypatch):
    monkeypatch.setenv("SHARED_KEY_DAILY_LIMIT", "1")
    headers, _ = make_user()
    provider.push(plan_json())
    assert career(client, headers, chat_id, "Python Developer").status_code == 200      # uses the only request
    assert used(client, headers) == 1

    assert career(client, headers, chat_id, "status").status_code == 200                # blocked before the fix
    assert career(client, headers, chat_id, "yes").status_code == 200
    assert "Quiz" in career(client, headers, chat_id, "done").get_json()["text"]

    r = career(client, headers, chat_id, "My long answer about decorators and closures.")   # needs the AI
    body = r.get_json()
    assert r.status_code == 429 and body["code"] == "shared_quota_exhausted"
    assert body["quota"]["daily_limit"] == 1 and "own Groq API key" in body["message"]
    assert day1_status(career(client, headers, chat_id, "status")) == "pending"
    assert used(client, headers) == 1


def test_at_the_limit_a_study_question_gets_429_and_never_calls_the_provider(client, make_user, provider, chat_id, monkeypatch):
    monkeypatch.setenv("SHARED_KEY_DAILY_LIMIT", "1")
    headers, _ = make_user()
    provider.push("first")
    assert study(client, headers, chat_id).status_code == 200
    calls = provider.calls
    r = study(client, headers, chat_id)
    assert r.status_code == 429 and r.get_json()["code"] == "shared_quota_exhausted"
    assert provider.calls == calls


def test_interview_start_at_the_limit_gets_429_and_never_calls_the_provider(client, make_user, provider, chat_id, monkeypatch):
    monkeypatch.setenv("SHARED_KEY_DAILY_LIMIT", "1")
    headers, _ = make_user()
    provider.push("first")
    study(client, headers, chat_id)
    r = client.post("/api/interview/start", headers=headers, data={"chat_id": chat_id, "role": "Dev", "jd_text": "x"})
    assert r.status_code == 429 and provider.calls == 1


def test_retry_after_header_is_passed_through_for_provider_rate_limits(client, make_user, provider, chat_id):
    headers, _ = make_user()
    err = ProviderError(429)
    err.response = SimpleNamespace(headers={"retry-after": "12"})
    provider.push(err)
    r = study(client, headers, chat_id)
    assert r.status_code == 503 and r.headers["Retry-After"] == "12"
