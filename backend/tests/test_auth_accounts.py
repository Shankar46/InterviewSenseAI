# backend/tests/test_auth_accounts.py
#
# Account behaviour, end to end (real Flask app, real temporary database).
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from backend import db, passwords
from backend.tests.llm_fakes import ProviderError   # noqa: F401  (keeps import side effects identical to other suites)

GOOD = "Tr0ub4dor-Test-pw"
OTHER = "Another-Good-Pass-9"
ROOT = Path(__file__).resolve().parents[2]


def uname(prefix="user"):
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def register(client, name, password=GOOD, ip=None):
    headers = {"X-Forwarded-For": ip} if ip else {}
    return client.post("/api/auth/register", data={"username": name, "password": password}, headers=headers)


def login(client, name, password=GOOD, ip=None, ua=None):
    headers = {}
    if ip:
        headers["X-Forwarded-For"] = ip
    if ua:
        headers["User-Agent"] = ua
    return client.post("/api/auth/login", data={"username": name, "password": password}, headers=headers)


def bearer(resp):
    return {"Authorization": "Bearer " + resp.get_json()["token"]}


def me(client, headers):
    return client.get("/api/auth/me", headers=headers).status_code


def fake_clock(monkeypatch, start=1_000_000):
    clock = [start]
    monkeypatch.setattr(db, "_now", lambda: clock[0])
    return clock


# ── sign up ───────────────────────────────────────────────────────────────

def test_signing_up_signs_you_in_immediately(client):
    """It used to answer 'please log in' and make the user type everything again."""
    name = uname()
    r = register(client, name)
    assert r.status_code == 201 and r.get_json()["username"] == name
    assert me(client, bearer(r)) == 200


def test_usernames_are_unique_ignoring_letter_case(client):
    name = uname("Mixed")
    assert register(client, name).status_code == 201
    for variant in (name.lower(), name.upper()):
        r = register(client, variant)
        assert r.status_code == 409 and "taken" in r.get_json()["message"]


def test_the_display_name_keeps_its_capitalisation_and_login_ignores_case(client):
    name = uname("Ravi")
    register(client, name)
    r = login(client, name.upper())
    assert r.status_code == 200 and r.get_json()["username"] == name


@pytest.mark.parametrize("bad", ["ab", "has space", "ravi@mail.com", "x" * 40, "r\u0430vi99"])
def test_bad_usernames_are_rejected(client, bad):
    r = register(client, bad)
    assert r.status_code == 400 and "Username" in r.get_json()["message"]


@pytest.mark.parametrize("password, fragment", [
    ("short1", "at least 8"), ("password123", "too common"), ("x" * 129, "at most 128"),
])
def test_weak_passwords_are_rejected_at_sign_up(client, password, fragment):
    r = register(client, uname(), password)
    assert r.status_code == 400 and fragment in r.get_json()["message"]


def test_password_may_not_contain_the_username(client):
    name = uname("zed")
    r = register(client, name, f"my-{name}-pass")
    assert r.status_code == 400 and "username" in r.get_json()["message"]


def test_the_password_is_used_exactly_as_typed(client):
    """Spaces used to be trimmed silently, so what you typed was not what was stored."""
    name, pwd = uname(), "  spaced out passphrase  "
    assert register(client, name, pwd).status_code == 201
    assert login(client, name, pwd).status_code == 200
    assert login(client, name, pwd.strip()).status_code == 401


def test_stored_hash_is_scrypt_not_the_password(client):
    name = uname()
    register(client, name)
    with db.get_connection() as conn:
        stored = conn.execute("SELECT password_hash FROM users WHERE username_lower = ?", (name.lower(),)).fetchone()[0]
    assert stored.startswith("scrypt$") and GOOD not in stored


# ── sign in ───────────────────────────────────────────────────────────────

def test_unknown_user_and_wrong_password_are_indistinguishable(client):
    name = uname()
    register(client, name)
    wrong = login(client, name, "definitely-not-it")
    ghost = login(client, uname("ghost"), "definitely-not-it")
    assert (wrong.status_code, wrong.get_json()) == (ghost.status_code, ghost.get_json())
    assert wrong.status_code == 401


def test_overlong_passwords_are_refused_without_hashing_them(client):
    name = uname()
    register(client, name)
    assert login(client, name, "x" * 5000).status_code == 401


def test_old_pbkdf2_accounts_still_log_in_and_are_upgraded_to_scrypt(client):
    name, pwd, salt = uname("legacy"), "old-account-pass1", "cd" * 16
    legacy = f"{salt}:{hashlib.pbkdf2_hmac('sha256', pwd.encode(), salt.encode(), 100000).hex()}"
    with db.get_connection() as conn:
        conn.execute("INSERT INTO users (username, username_lower, password_hash) VALUES (?, ?, ?)",
                     (name, name.lower(), legacy))
    assert login(client, name, pwd).status_code == 200
    with db.get_connection() as conn:
        upgraded = conn.execute("SELECT password_hash FROM users WHERE username_lower = ?", (name.lower(),)).fetchone()[0]
    assert upgraded.startswith("scrypt$")
    assert login(client, name, pwd).status_code == 200            # and the upgraded hash works
    assert login(client, name, "wrong-password").status_code == 401


def test_accounts_made_when_passwords_were_trimmed_can_still_sign_in_with_the_space(client):
    name, pwd, salt = uname("trim"), "trimmed-pass-1", "ef" * 16
    legacy = f"{salt}:{hashlib.pbkdf2_hmac('sha256', pwd.encode(), salt.encode(), 100000).hex()}"
    with db.get_connection() as conn:
        conn.execute("INSERT INTO users (username, username_lower, password_hash) VALUES (?, ?, ?)",
                     (name, name.lower(), legacy))
    assert login(client, name, pwd + " ").status_code == 200       # old UI trimmed it; the typed space is forgiven


# ── brute-force protection ────────────────────────────────────────────────

def test_five_wrong_passwords_lock_that_account_from_that_address(client, monkeypatch):
    clock = fake_clock(monkeypatch)
    name = uname()
    register(client, name)
    codes = [login(client, name, "wrong-pass-%d" % i, ip="9.9.9.9").status_code for i in range(5)]
    assert codes == [401] * 5

    locked = login(client, name, GOOD, ip="9.9.9.9")               # even the CORRECT password is refused
    body = locked.get_json()
    assert locked.status_code == 429 and body["code"] == "login_locked"
    assert locked.headers["Retry-After"] == str(body["retry_after"]) and 0 < body["retry_after"] <= 900
    assert "Try again in" in body["message"]

    clock[0] += 901                                                 # time passes
    assert login(client, name, GOOD, ip="9.9.9.9").status_code == 200


def test_a_lockout_does_not_affect_other_accounts_or_other_addresses(client, monkeypatch):
    fake_clock(monkeypatch)
    victim, bystander = uname(), uname()
    register(client, victim)
    register(client, bystander)
    for i in range(5):
        login(client, victim, "wrong-pass-%d" % i, ip="9.9.9.9")
    assert login(client, victim, GOOD, ip="9.9.9.9").status_code == 429
    assert login(client, victim, GOOD, ip="5.5.5.5").status_code == 200        # the real owner, elsewhere
    assert login(client, bystander, GOOD, ip="9.9.9.9").status_code == 200     # same address, other account


def test_unknown_usernames_lock_exactly_like_real_ones(client, monkeypatch):
    """If only real accounts locked, the lockout itself would reveal which usernames exist."""
    fake_clock(monkeypatch)
    real, ghost = uname(), uname("ghost")
    register(client, real)
    # (separate addresses: the per-address rate limiter allows only 8 requests/minute and is not what is tested here)
    pattern = lambda name, ip: [login(client, name, "nope-nope-nope", ip=ip).status_code for _ in range(7)]
    assert pattern(real, "7.7.7.7") == pattern(ghost, "7.7.7.8") == [401] * 5 + [429] * 2


def test_a_correct_login_resets_the_per_address_counter(client, monkeypatch):
    fake_clock(monkeypatch)
    name = uname()
    register(client, name)
    for _ in range(3):
        login(client, name, "wrong-pass-x", ip="9.9.9.9")
    assert login(client, name, GOOD, ip="9.9.9.9").status_code == 200
    for _ in range(4):                       # without the reset, 3 + 4 = 7 failures would already have locked it
        assert login(client, name, "wrong-pass-y", ip="9.9.9.9").status_code == 401


def test_guessing_from_many_addresses_still_locks_the_account(client, monkeypatch):
    """Rotating the (spoofable) client address must not defeat the per-account limit."""
    fake_clock(monkeypatch)
    name = uname()
    register(client, name)
    for i in range(30):
        assert login(client, name, "wrong-pass-z", ip=f"10.0.{i // 250}.{i % 250 + 1}").status_code == 401
    r = login(client, name, GOOD, ip="203.0.113.77")                # brand-new address, correct password
    assert r.status_code == 429 and r.get_json()["code"] == "login_locked"


# ── sessions ──────────────────────────────────────────────────────────────

def test_session_list_names_devices_and_marks_the_current_one(client):
    name = uname()
    register(client, name)
    phone = bearer(login(client, name, ua="Mozilla/5.0 (iPhone) Safari"))
    laptop = bearer(login(client, name, ua="Mozilla/5.0 (Windows) Chrome"))
    sessions = client.get("/api/auth/sessions", headers=laptop).get_json()["sessions"]
    current = [s for s in sessions if s["current"]]
    assert len(sessions) >= 3 and len(current) == 1 and "Chrome" in current[0]["device"]
    assert any("iPhone" in s["device"] for s in sessions)
    assert all(len(s["id"]) == 16 for s in sessions)
    assert me(client, phone) == 200


def test_you_can_sign_out_one_other_device(client):
    name = uname()
    register(client, name)
    phone = bearer(login(client, name, ua="PhoneBrowser"))
    laptop = bearer(login(client, name, ua="LaptopBrowser"))
    phone_id = next(s["id"] for s in client.get("/api/auth/sessions", headers=laptop).get_json()["sessions"]
                    if "PhoneBrowser" in s["device"])
    assert client.delete(f"/api/auth/sessions/{phone_id}", headers=laptop).status_code == 200
    assert me(client, phone) == 401 and me(client, laptop) == 200


def test_you_cannot_sign_out_someone_elses_device(client):
    a, b = uname(), uname()
    register(client, a)
    register(client, b)
    a_headers = bearer(login(client, a, ua="A-Browser"))
    b_headers = bearer(login(client, b))
    a_id = next(s["id"] for s in client.get("/api/auth/sessions", headers=a_headers).get_json()["sessions"] if s["current"])
    assert client.delete(f"/api/auth/sessions/{a_id}", headers=b_headers).status_code == 404
    assert me(client, a_headers) == 200


def test_sign_out_everywhere_ends_every_session_including_this_one(client):
    name = uname()
    register(client, name)
    tokens = [bearer(login(client, name)) for _ in range(3)]
    r = client.post("/api/auth/logout-all", headers=tokens[0])
    assert r.status_code == 200 and r.get_json()["signed_out"] >= 3
    assert [me(client, t) for t in tokens] == [401, 401, 401]


# ── changing the password ─────────────────────────────────────────────────

def change(client, headers, current, new):
    return client.post("/api/auth/change-password", headers=headers,
                       data={"current_password": current, "new_password": new})


def test_changing_the_password_signs_out_other_devices_but_not_this_one(client):
    name = uname()
    register(client, name)
    here, there = bearer(login(client, name)), bearer(login(client, name))
    r = change(client, here, GOOD, OTHER)
    assert r.status_code == 200 and r.get_json()["other_sessions_signed_out"] >= 1
    assert me(client, here) == 200 and me(client, there) == 401
    assert login(client, name, GOOD).status_code == 401
    assert login(client, name, OTHER).status_code == 200


def test_changing_the_password_needs_the_current_one(client):
    name = uname()
    register(client, name)
    headers = bearer(login(client, name))
    r = change(client, headers, "not-my-password", OTHER)
    assert r.status_code == 403 and login(client, name, GOOD).status_code == 200      # unchanged


def test_wrong_current_passwords_count_toward_the_lockout(client, monkeypatch):
    """A stolen token must not let someone guess the password through this form."""
    fake_clock(monkeypatch)
    name = uname()
    register(client, name)
    headers = bearer(login(client, name))
    assert [change(client, headers, f"guess-number-{i}", OTHER).status_code for i in range(5)] == [403] * 5
    assert change(client, headers, GOOD, OTHER).status_code == 429


def test_the_new_password_must_pass_the_same_rules_and_differ(client):
    name = uname()
    register(client, name)
    headers = bearer(login(client, name))
    assert change(client, headers, GOOD, "short").status_code == 400
    assert change(client, headers, GOOD, "password123").status_code == 400
    assert change(client, headers, GOOD, GOOD).status_code == 400


# ── deleting the account ──────────────────────────────────────────────────

def chat_rows(chat):
    tables = ("course_sessions", "progress", "notifications", "messages", "interview_sessions", "interview_qa", "user_chats")
    with db.get_connection() as conn:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE chat_id = ?", (chat,)).fetchone()[0] for t in tables}


def seed_chat(client, headers, chat):
    client.post(f"/api/sessions/{chat}/messages", json={"role": "user", "content": "hello"}, headers=headers)
    db.push_notification(chat, "info", "title", "body")
    db.log_day_completion(chat, 1, "completed", "2026-01-01", score=7)
    with db.get_connection() as conn:
        conn.execute("INSERT INTO interview_sessions (chat_id) VALUES (?)", (chat,))
        conn.execute("INSERT INTO interview_qa (chat_id, q_index, question) VALUES (?, 0, 'q')", (chat,))
        conn.execute("INSERT INTO course_sessions (chat_id) VALUES (?)", (chat,))


def test_deleting_an_account_removes_every_trace_and_only_that_account(client):
    mine, theirs = uname(), uname()
    register(client, mine)
    register(client, theirs)
    my_h, their_h = bearer(login(client, mine)), bearer(login(client, theirs))
    my_chat, their_chat = str(uuid.uuid4()), str(uuid.uuid4())
    seed_chat(client, my_h, my_chat)
    seed_chat(client, their_h, their_chat)
    assert all(v >= 1 for v in chat_rows(my_chat).values())

    r = client.post("/api/auth/delete-account", headers=my_h, data={"password": GOOD})
    assert r.status_code == 200
    assert all(v == 0 for v in chat_rows(my_chat).values())           # includes the interview tables
    assert all(v >= 1 for v in chat_rows(their_chat).values())        # the other account is untouched
    assert me(client, my_h) == 401 and login(client, mine).status_code == 401
    assert me(client, their_h) == 200


def test_deleting_needs_the_password_and_wrong_ones_change_nothing(client):
    name = uname()
    register(client, name)
    headers = bearer(login(client, name))
    for body in ({"password": "wrong-password"}, {}):
        assert client.post("/api/auth/delete-account", headers=headers, data=body).status_code == 403
    assert me(client, headers) == 200 and login(client, name).status_code == 200


def test_a_deleted_username_can_be_registered_again(client):
    name = uname()
    h = bearer(register(client, name))
    client.post("/api/auth/delete-account", headers=h, data={"password": GOOD})
    assert register(client, name).status_code == 201


def test_deleting_a_single_chat_now_also_deletes_its_interview_data(client):
    name = uname()
    h = bearer(register(client, name))
    chat = str(uuid.uuid4())
    seed_chat(client, h, chat)
    db.delete_session(chat)
    assert all(v == 0 for v in chat_rows(chat).values())


# ── upgrading an existing database ────────────────────────────────────────

def run_init_on(db_path: Path, snippet: str) -> dict:
    code = ("import json; from backend import db; db.init_db(); " + snippet)
    env = {**os.environ, "SQLITE_PATH": str(db_path), "PASSWORD_HASH_FAST": "1", "PYTHONWARNINGS": "ignore"}
    env.pop("DATABASE_URL", None)
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


LEGACY_SCHEMA = """
CREATE TABLE users (user_id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE user_sessions (session_token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                            created_at TEXT NOT NULL DEFAULT (datetime('now')), expires_at TEXT NOT NULL);
CREATE TABLE user_chats (chat_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE);
"""


def make_legacy_db(tmp_path, names):
    import sqlite3
    path = tmp_path / "legacy.db"
    con = sqlite3.connect(path)
    con.executescript(LEGACY_SCHEMA)
    salt = "ab" * 16
    legacy = f"{salt}:{hashlib.pbkdf2_hmac('sha256', b'legacy-pass-1', salt.encode(), 100000).hex()}"
    for n in names:
        con.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (n, legacy))
    con.commit()
    con.close()
    return path


def test_an_existing_database_is_upgraded_in_place_and_old_logins_keep_working(tmp_path):
    path = make_legacy_db(tmp_path, ["Alice", "bob"])
    result = run_init_on(path, (
        "con = db.get_connection().__enter__(); "
        "rows = [dict(r) for r in con.execute('SELECT username, username_lower FROM users ORDER BY user_id')]; "
        "idx = [r[1] for r in con.execute('PRAGMA index_list(users)')]; "
        "user = db.verify_user('ALICE', 'legacy-pass-1'); "
        "print(json.dumps({'rows': rows, 'idx': idx, 'login': user and user['username']}))"
    ))
    assert result["rows"] == [{"username": "Alice", "username_lower": "alice"}, {"username": "bob", "username_lower": "bob"}]
    assert "idx_users_username_lower" in result["idx"]
    assert result["login"] == "Alice"


def test_a_database_with_case_clashing_accounts_still_starts(tmp_path):
    path = make_legacy_db(tmp_path, ["Sam", "sam"])
    result = run_init_on(path, (
        "con = db.get_connection().__enter__(); "
        "idx = [r[1] for r in con.execute('PRAGMA index_list(users)')]; "
        "n = con.execute('SELECT COUNT(*) FROM users').fetchone()[0]; "
        "print(json.dumps({'idx': idx, 'users': n}))"
    ))
    assert result["users"] == 2 and "idx_users_username_lower" not in result["idx"]     # warned, did not crash
