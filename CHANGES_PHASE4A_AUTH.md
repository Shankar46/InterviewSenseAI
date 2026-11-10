# Phase 4a: accounts, authentication and authorization

## What changed, compared with how larger sites work

| Area | Before | Now |
|---|---|---|
| **Sign-up** | "Please sign in", form cleared, retype everything | Signs you in immediately (201 + session) |
| **Password storage** | PBKDF2, 100k rounds | **scrypt** (N=2^15, r=8, p=3, per-hash salt). Old hashes keep working and are **upgraded silently at next login** |
| **Password rules** | length >= 6, silently *trimmed* | 8-128 characters, no composition rules (NIST style), block-list of common passwords, may not contain the username, **used exactly as typed** (spaces kept, Unicode normalised) |
| **Usernames** | case-sensitive, any characters ("Alice" and "alice" were two accounts, look-alike Unicode allowed) | unique ignoring case, 3-32 of `A-Z a-z 0-9 . _ -`; display name keeps your capitalisation |
| **Brute force** | 8 requests/min per IP, nothing per account | After **5** wrong passwords: account + address locked 15 min (HTTP 429 + `Retry-After`, even the right password is refused). After **30** from anywhere: the account locks for everyone. Unknown usernames count too, so the lockout does not reveal which accounts exist. Stored in the database (works across serverless instances) |
| **User enumeration** | unknown user returned faster than wrong password | Same message, same status, same time (dummy hash is computed for unknown users) |
| **Sessions** | one fixed 30-day token, no way to see or end it | List devices, sign out one device, **sign out everywhere**; password change ends all *other* sessions |
| **Sensitive actions** | none existed | Change password and delete account re-ask for the current password; wrong guesses count toward the same lockout (a stolen token cannot be used to guess it) |
| **Account deletion** | not possible; deleting one chat even left its interview answers behind | `POST /api/auth/delete-account` removes the account and *all* its data in one transaction; deleting a chat now also removes interview data |
| **Authorization** | ownership checks existed but nothing guaranteed new routes would have them | `test_authorization.py` enumerates every route: each must be declared PUBLIC / USER_SCOPED / CHAT_SCOPED, must reject anonymous and garbage tokens, and chat routes must refuse non-owners (86 checks). Adding a route without deciding fails the build |
| **Existing databases** | n/a | Migrated in place on SQLite *and* Postgres: `username_lower` backfilled, unique index created (skipped with a warning if two old accounts differ only by case) |
| **Browser** | `autocomplete=current-password` always | `new-password` while signing up (browser offers a strong generated password), `current-password` while signing in; `name` attributes added |
| **Label warning** | `<label for="ic-resume">` pointed at nothing | now points at the real `ic-resume-file` input |

## New / changed API

| Method + path | Purpose |
|---|---|
| `POST /api/auth/register` | create account **and sign in** -> `201 {token, username}`; 400 policy message, 409 name taken |
| `POST /api/auth/login` | `401` wrong credentials, `429 login_locked` (+`Retry-After`) |
| `GET /api/auth/sessions` | devices signed in (`id`, `device`, `created_at`, `current`) |
| `DELETE /api/auth/sessions/<id>` | sign out one device (404 if it is not yours) |
| `POST /api/auth/logout-all` | sign out every device including this one |
| `POST /api/auth/change-password` | `current_password`, `new_password` -> ends other sessions |
| `POST /api/auth/delete-account` | `password` -> deletes account and all data |

## Things to know
* **Existing users are not affected.** Sign-in never applies the new password rules, so a 6-character password still works (and is upgraded to scrypt the first time). The rules apply when creating an account or changing a password.
* **scrypt costs about 0.2 s per sign-in** on a laptop (that is the point). On a small serverless instance expect a few tenths of a second more.
* `PASSWORD_HASH_FAST=1` (tests only) is ignored on Vercel and whenever `DATABASE_URL` is set.
* The 15-minute account lockout means someone who knows a username can lock that person out for 15 minutes by failing 30 times. That is the usual trade-off; the threshold is high (30/hour) and the address-level lock (5) does not affect the real owner on another network.

## Not done (needs decisions or external services)
* **Password reset and email verification.** Need an email provider (Resend, Brevo, SES...) and a verified sending domain. Today a forgotten password cannot be recovered.
* **"Sign in with Google/GitHub".** Needs OAuth client credentials and redirect URLs.
* **HttpOnly-cookie sessions + CSRF protection.** The standard for big sites, but the token currently lives in `localStorage`. The XSS fixes (sanitiser, CSP, pinned libraries) reduce that risk but do not remove it. Cookies work cleanly once frontend and API share one origin (Vercel does; your local `file://` setup does not).
* **Two-factor authentication**, an **account-settings screen** in the UI (the API exists; there is no screen for it yet), and a **"have I been pwned" breach check** for passwords.
* The client address still comes from `X-Forwarded-For`, which a caller can fake unless a trusted proxy overwrites it. That weakens only the per-address lock (the per-account lock still holds); it is on the serverless roadmap.
