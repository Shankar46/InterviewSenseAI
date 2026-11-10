# backend/tests/test_authorization.py
#
# Authorization regression guard. It looks at EVERY route the app registers, so a
# new endpoint cannot ship without someone deciding how it is protected:
#
#   PUBLIC        no login needed (sign up, sign in, health pings)
#   USER_SCOPED   needs a login, acts only on the caller's own account
#   CHAT_SCOPED   needs a login AND ownership of the chat/session it names
#
# If you add a route, this file fails until you add it to exactly one list below.
import uuid

import pytest

from backend.main import app

PUBLIC = {
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("GET", "/api/health"),
    ("GET", "/api/agent"),                    # static "endpoint is alive" ping
}

USER_SCOPED = {
    ("GET", "/api/auth/me"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/logout-all"),
    ("GET", "/api/auth/sessions"),
    ("DELETE", "/api/auth/sessions/<session_id>"),
    ("POST", "/api/auth/change-password"),
    ("POST", "/api/auth/delete-account"),
    ("GET", "/api/usage"),
    ("POST", "/api/evaluate"),
    ("POST", "/api/ide/run"),
}

# how the route receives the chat id: "form", "query", "path" or "json"
CHAT_SCOPED = {
    ("POST", "/api/agent"): "json",
    ("POST", "/api/edtech/delete"): "form",
    ("POST", "/api/edtech/generate"): "form",
    ("POST", "/api/edtech/reset"): "form",
    ("GET", "/api/edtech/stats"): "query",
    ("GET", "/api/edtech/weekend"): "query",
    ("POST", "/api/interview/answer"): "form",
    ("GET", "/api/interview/report"): "query",
    ("POST", "/api/interview/reset"): "form",
    ("POST", "/api/interview/start"): "form",
    ("GET", "/api/notifications"): "query",
    ("POST", "/api/notifications/read"): "form",
    ("GET", "/api/sessions/<session_id>/messages"): "path",
    ("POST", "/api/sessions/<session_id>/messages"): "path",
    ("POST", "/api/workspace/generate"): "form",
    ("POST", "/generate"): "form",
}


def all_routes():
    return {(m, rule.rule)
            for rule in app.url_map.iter_rules() if rule.endpoint != "static"
            for m in rule.methods - {"HEAD", "OPTIONS"}}


def call(client, method, rule, chat, headers=None, kind=None):
    url = rule.replace("<session_id>", chat if kind == "path" else "abcdef0123456789")
    form = {"chat_id": chat, "role": "user", "content": "x", "answer": "a", "topic": "topic here",
            "assistant_type": "career", "domain": "it", "round_type": "tech", "company": "Acme"}
    kwargs = {"headers": headers or {}}
    if kind == "json":
        kwargs["json"] = {"chat_id": chat, "message": "hi"}
    elif kind == "path":
        kwargs["json"] = {"role": "user", "content": "x"}
    elif kind == "query":
        url += f"?chat_id={chat}"
    elif method in ("POST", "DELETE"):
        kwargs["data"] = form
    return client.open(url, method=method, **kwargs)


def test_every_route_is_classified_exactly_once():
    classified = [PUBLIC, USER_SCOPED, set(CHAT_SCOPED)]
    assert sum(len(s) for s in classified) == len(set().union(*classified)), "a route appears in two lists"
    actual, known = all_routes(), set().union(*classified)
    assert actual - known == set(), f"NEW route(s) with no declared protection: {sorted(actual - known)}"
    assert known - actual == set(), f"listed route(s) that no longer exist: {sorted(known - actual)}"


@pytest.mark.parametrize("method, rule", sorted(USER_SCOPED | set(CHAT_SCOPED)))
def test_protected_routes_reject_anonymous_callers(client, method, rule):
    kind = CHAT_SCOPED.get((method, rule))
    r = call(client, method, rule, str(uuid.uuid4()), kind=kind)
    assert r.status_code == 401, f"{method} {rule} answered {r.status_code} without a login"


@pytest.mark.parametrize("method, rule", sorted(USER_SCOPED | set(CHAT_SCOPED)))
def test_protected_routes_reject_garbage_tokens(client, method, rule):
    kind = CHAT_SCOPED.get((method, rule))
    for header in ("Bearer not-a-real-token", "Bearer " + "0" * 64, "Basic abc123"):
        r = call(client, method, rule, str(uuid.uuid4()), headers={"Authorization": header}, kind=kind)
        assert r.status_code == 401, f"{method} {rule} accepted {header!r}"


@pytest.mark.parametrize("method, rule", sorted(CHAT_SCOPED))
def test_chat_routes_refuse_a_user_who_does_not_own_the_chat(client, make_user, method, rule):
    owner, _ = make_user()
    intruder, _ = make_user()
    chat = str(uuid.uuid4())
    client.post(f"/api/sessions/{chat}/messages", json={"role": "user", "content": "mine"}, headers=owner)   # owner claims it
    r = call(client, method, rule, chat, headers=intruder, kind=CHAT_SCOPED[(method, rule)])
    assert r.status_code == 403, f"{method} {rule} let another user in (HTTP {r.status_code})"
    assert client.get(f"/api/sessions/{chat}/messages", headers=owner).get_json()["messages"][0]["content"] == "mine"


@pytest.mark.parametrize("method, rule", sorted(CHAT_SCOPED))
def test_chat_routes_refuse_missing_or_malformed_chat_ids(client, make_user, method, rule):
    headers, _ = make_user()
    kind = CHAT_SCOPED[(method, rule)]
    for bad in ("default", "../../etc/passwd", "x" * 200, "has space"):
        r = call(client, method, rule, bad, headers=headers, kind=kind)
        assert r.status_code in (400, 404), f"{method} {rule} accepted chat id {bad!r} (HTTP {r.status_code})"


def test_a_revoked_session_stops_working_on_every_protected_route(client, make_user):
    headers, _ = make_user()
    client.post("/api/auth/logout", headers=headers)
    for method, rule in sorted(USER_SCOPED - {("POST", "/api/auth/logout")}):
        r = call(client, method, rule, str(uuid.uuid4()), headers=headers)
        assert r.status_code == 401, f"{method} {rule} still worked after logout"
