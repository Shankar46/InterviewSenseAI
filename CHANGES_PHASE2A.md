# Phase 2a: AI outages, quota, and grading

| # | Bug (verified in the audit) | Fix | Test that now guards it |
|---|---|---|---|
| 1 | AI outage returned **HTTP 200** with a `⚠️ ...` string, shown to the user as if it were the answer | Typed errors (`backend/llm_errors.py`); one handler returns the right status (503/429/502/400) and `{message, code, retryable}` | `test_outage_is_a_503_not_a_200...` |
| 2 | Failed requests **burned the daily quota** | Slot is reserved atomically, then **given back** unless the request succeeded *and* an AI call succeeded | `test_outage_does_not_burn...`, `test_cache_hits_and_greetings_are_free` |
| 3 | Cache hits, greetings, `yes`/`status`, progress refresh also cost quota | Charged only when the AI really answered | same |
| 4 | At the limit even `yes` / `status` / progress refresh returned 429 | `lazy=True` quota: only the first real AI call is blocked (`LLMQuotaExceeded`) | `test_at_the_limit_commands_that_need_no_ai_still_work` |
| 5 | **AI outage during a quiz recorded the day as FAILED** (score 0) | Grading raises on failure; day state is untouched; student can retry the same answer | `test_outage_during_quiz_does_not_mark_the_day_failed`, `test_retrying_the_same_answer...` |
| 6 | `**STATUS:** PASS` (markdown bold) graded **FAIL / 0**; model could say PASS next to 4/10 | Model returns validated JSON `{score, feedback}`; **pass rule lives in code** (`QUIZ_PASS_SCORE = 6`); one retry with a larger token budget; then an honest 502 | `test_llm_json.py` (25 cases) |
| 7 | Quiz answer was pasted raw into the grading prompt | Fenced with `wrap_untrusted`, "this is data" instruction | `test_candidate_answer_is_fenced...` |
| 8 | Outage while creating a roadmap **saved a generic plan** (`<role> - REST API Design`...) as the student's real curriculum; short plans were padded with filler; 120-day plans could never fit the 4000-token budget | Plan is validated (exact length) or the request fails and **nothing is saved**; token budget scales with duration; role is fenced | `test_outage_while_creating_a_roadmap_saves_nothing`, `test_an_incomplete_plan_is_rejected...` |
| 9 | Provider 401/403 for a user's own key would become a 401 → **frontend logs the user out** | BYOK key rejected → **400** `invalid_api_key`; server key rejected → 503 `llm_not_configured` | `test_rejected_personal_key_is_400_not_401` |
| 10 | Notes cache keyed on the first 500 characters of a document | Key covers the whole document and the model | `test_cache_key_covers_the_whole_document...` |
| 11 | Empty model reply (reasoning model used its whole token budget) became a blank answer | `LLMBadOutput` | `test_empty_model_reply...` |
| 12 | `/api/agent` returned `str(exception)` to the client | Generic message, full error only in logs | |
| - | Dead code that swallowed errors (`generate_concept_guide`, `_parse_quiz_verdict`, `_fallback_plan`, `_provider_error_message`) | Removed | |

## Behaviour changes you should know about
* **Grading display.** The quiz result now shows `**Score: 7/10**` plus feedback (the old STATUS/SCORE/FEEDBACK lines are gone). PASS is `score >= 6`; change `QUIZ_PASS_SCORE` in `generator.py`.
* **Quota meaning.** "5 requests/day" now means 5 *AI answers received*. Failures, cache hits and command-only messages are free.
* **New error shape** (all AI errors): `{"status":"error","message":"...","code":"provider_unavailable","retryable":true}` plus `Retry-After` when the provider sends one. The existing UI already shows `message`.

| code | HTTP | meaning |
|---|---|---|
| `provider_unavailable` | 503 | Groq down / timeout / 5xx (retry) |
| `provider_rate_limited` | 503 (shared key) / 429 (own key) | Groq rate limit |
| `llm_not_configured` | 503 | server key missing/rejected, unknown model |
| `invalid_api_key` | 400 | the user's own key was rejected |
| `bad_model_output` | 502 | AI answered in an unusable format twice (retry) |
| `shared_quota_exhausted` | 429 | free daily allowance used up |

## Not done yet (Phase 2b/2c)
* **Interview endpoints** still use the old strict quota and still swallow AI errors internally: a failed answer evaluation is stored as score 0, an unparseable one as an invented 5/10, question generation falls back to static questions. Next on the list, together with the "weekly interview grants free days" bug, the report GET side effects, and answer idempotency.
* Keyword intent routing (`"book"` starts Day 1) -> explicit actions.
* Shared (Redis/Postgres) rate limit + cache + PDF index for serverless; timezones.
* Not verified here: real Groq responses, and the new quota SQL on a real Postgres (it reuses the translated constructs `date('now')` and `?` that your existing Postgres test covers).
