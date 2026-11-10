# Phase 1 changes

| # | Problem found in audit | Fix | Proof |
|---|---|---|---|
| 1 | Message endpoints readable/writable with no login | `@login_required` + chat ownership check + role/size validation | `test_auth_and_messages.py` |
| 2 | `/api/edtech/weekend` unauthenticated | login + ownership | test |
| 3 | `saveMessage` sent FormData, server read JSON → nothing saved | client sends JSON; server accepts JSON *or* form | `test_form_encoded_save_actually_persists` |
| 4 | Messages came back in random order (1-second timestamps) | order by `id`; table created once at startup, not per save | `test_messages_come_back_in_the_order…` |
| 5 | Deleting a chat left its messages behind | `delete_session` also deletes messages | test |
| 6 | Global `"default"` chat id: first user owns it, all others 403 | chat_id required + format-validated (400 otherwise); client uses `crypto.randomUUID()` | tests |
| 7 | Session tokens stored in plain text | SHA-256 digest stored; raw token only ever lives in the browser | `test_raw_token_is_never_stored`, `test_a_stored_hash_cannot_be_replayed…` |
| 8 | XSS: `marked` → `innerHTML` unsanitised; toasts/notifications used `innerHTML` | DOMPurify (fails closed), `textContent` for toasts/notifications, links get `rel=noopener` | `frontend/tests/xss.test.js` (12 checks) |
| 9 | CDN scripts unpinned / no integrity | `marked@9.1.6`, `dompurify@3.4.17` with SRI hashes. (3.2.6 was first used and found vulnerable by `npm audit`; upgraded, `USE_PROFILES` removed, form/svg/math/style tags forbidden.) CI now runs `npm audit --audit-level=high`. | index.html, `npm audit` = 0 |
| 10 | No CSP / security headers | CSP, nosniff, Referrer-Policy, X-Frame-Options, Permissions-Policy (mic allowed for interviews) | vercel.json (**untested on a live Vercel deploy**) |
| 11 | Injection sanitiser flagged one letter (`[You are now D]AN`), the test enforced the bug; extra spaces bypassed it | whole-phrase, whitespace-tolerant patterns; test corrected | `test_injection_guard.py` |
| 12 | Anti-injection notice named `<<<DOCUMENT_CONTENT_START>>>` but the code emitted `<<<DOCUMENT CONTENT_START>>>` | default label fixed; notice also names the USER_TOPIC fence; untrusted text can no longer forge the closing fence | `test_default_fence_label_matches…` |
| 13 | Rate-limit tests depended on run order | `conftest.py` resets global state; tests use a throw-away DB (`SQLITE_PATH`) | each test passes alone & reversed |
| 14 | Unused packages / Qwen leftover / debug pages shipped | removed `fastapi`, `starlette`, `uvicorn`, `annotated-doc`; deleted `debug_*.html/js`, `test_career_direct.html` | clean-venv install + 54 tests |

Correction to the audit: `lxml`, `Pillow`, `XlsxWriter` are required by `python-pptx`
(used for PPTX upload), so they stay in requirements.txt.

NOT in this phase (see roadmap): structured LLM output, explicit-action intent
routing, quota refund on failure, interview idempotency / free-credit bug,
shared (Redis/Postgres) rate-limit & cache for serverless, timezone handling.
