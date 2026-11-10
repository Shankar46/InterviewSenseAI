# backend/tests/test_auth_and_messages.py
#
# Integration tests: real Flask app, real (temporary) database, no mocking of
# our own code. Each test below reproduces a bug found in the audit.
from backend import db


# ── message endpoints must require login + ownership ──────────────────────

def test_messages_require_login(client, chat_id):
    assert client.get(f"/api/sessions/{chat_id}/messages").status_code == 401
    r = client.post(f"/api/sessions/{chat_id}/messages", json={"role": "user", "content": "x"})
    assert r.status_code == 401


def test_other_users_cannot_read_or_write_my_chat(client, make_user, chat_id):
    alice, _ = make_user()
    bob, _ = make_user()
    ok = client.post(f"/api/sessions/{chat_id}/messages", json={"role": "user", "content": "private"}, headers=alice)
    assert ok.status_code == 200
    assert client.get(f"/api/sessions/{chat_id}/messages", headers=bob).status_code == 403
    r = client.post(f"/api/sessions/{chat_id}/messages", json={"role": "assistant", "content": "injected"}, headers=bob)
    assert r.status_code == 403


def test_form_encoded_save_actually_persists(client, make_user, chat_id):
    """The browser sends FormData; the server used to read only JSON and silently saved nothing."""
    headers, _ = make_user()
    r = client.post(f"/api/sessions/{chat_id}/messages", data={"role": "user", "content": "hello"}, headers=headers)
    assert r.get_json()["saved"] is True
    msgs = client.get(f"/api/sessions/{chat_id}/messages", headers=headers).get_json()["messages"]
    assert msgs == [{"role": "user", "content": "hello"}]


def test_messages_come_back_in_the_order_they_were_saved(client, make_user, chat_id):
    headers, _ = make_user()
    for i in range(12):   # all inside the same second: created_at alone cannot order these
        client.post(f"/api/sessions/{chat_id}/messages", json={"role": "user", "content": f"m{i}"}, headers=headers)
    got = [m["content"] for m in client.get(f"/api/sessions/{chat_id}/messages", headers=headers).get_json()["messages"]]
    assert got == [f"m{i}" for i in range(12)]


def test_message_validation(client, make_user, chat_id):
    headers, _ = make_user()
    url = f"/api/sessions/{chat_id}/messages"
    assert client.post(url, json={"role": "system", "content": "x"}, headers=headers).status_code == 400
    assert client.post(url, json={"role": "user", "content": "x" * 20_001}, headers=headers).status_code == 413
    r = client.post(url, json={"role": "user", "content": "__loading__"}, headers=headers)
    assert r.get_json()["saved"] is False


def test_deleting_a_session_also_deletes_its_messages(client, make_user, chat_id):
    headers, _ = make_user()
    client.post(f"/api/sessions/{chat_id}/messages", json={"role": "user", "content": "bye"}, headers=headers)
    assert client.post("/api/edtech/delete", data={"chat_id": chat_id}, headers=headers).status_code == 200
    assert db.get_session_messages(chat_id) == []


# ── other previously-open endpoint ───────────────────────────────────────

def test_weekend_endpoint_requires_login(client, chat_id):
    assert client.get(f"/api/edtech/weekend?chat_id={chat_id}").status_code == 401


# ── chat_id: no more global "default" ────────────────────────────────────

def test_default_and_missing_chat_ids_are_rejected_not_shared(client, make_user):
    headers, _ = make_user()
    for body in ({}, {"chat_id": "default"}, {"chat_id": ""}, {"chat_id": "../../etc"}, {"chat_id": "x" * 200}):
        r = client.post("/api/edtech/reset", data=body, headers=headers)
        assert r.status_code == 400, body


def test_two_users_no_longer_collide_on_a_missing_chat_id(client, make_user):
    a, _ = make_user()
    b, _ = make_user()
    for h in (a, b):
        r = client.post("/api/edtech/reset", data={}, headers=h)
        assert r.status_code == 400          # clear error for both, instead of 200 for one and 403 for the other


# ── session tokens ───────────────────────────────────────────────────────

def test_raw_token_is_never_stored(client, make_user):
    headers, name = make_user()
    raw = headers["Authorization"].split(" ", 1)[1]
    with db.get_connection() as conn:
        stored = [r[0] for r in conn.execute("SELECT session_token FROM user_sessions").fetchall()]
    assert raw not in stored
    assert db._hash_token(raw) in stored


def test_logout_invalidates_the_token(client, make_user):
    headers, _ = make_user()
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_a_stored_hash_cannot_be_replayed_as_a_token(client, make_user):
    """If the database leaks, the digests in it must not work as logins."""
    headers, _ = make_user()
    raw = headers["Authorization"].split(" ", 1)[1]
    leaked_hash = db._hash_token(raw)
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {leaked_hash}"})
    assert r.status_code == 401


def test_malformed_authorization_headers(client):
    for value in ("Bearer", "Bearer ", "Basic abc", "", "Bearer a b c"):
        assert client.get("/api/auth/me", headers={"Authorization": value}).status_code == 401, value
    # scheme is case-insensitive per RFC 7235
    assert client.get("/api/auth/me", headers={"Authorization": "bearer nope"}).status_code == 401
