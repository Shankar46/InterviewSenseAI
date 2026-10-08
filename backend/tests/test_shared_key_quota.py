import sqlite3
from contextlib import contextmanager

from flask import Flask, jsonify, request

from backend import db, shared_key_quota


def test_shared_key_requests_stop_at_daily_limit(tmp_path, monkeypatch):
    database_path = tmp_path / "quota.db"

    @contextmanager
    def temporary_connection():
        conn = sqlite3.connect(database_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    monkeypatch.setattr(db, "get_connection", temporary_connection)
    with temporary_connection() as conn:
        conn.execute("CREATE TABLE users (user_id INTEGER PRIMARY KEY)")
        conn.execute(
            """CREATE TABLE shared_key_usage (
                user_id INTEGER NOT NULL,
                usage_date TEXT NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, usage_date)
            )"""
        )
        conn.execute("INSERT INTO users (user_id) VALUES (7)")

    assert db.reserve_shared_key_request(7, 2) == (True, 1)
    assert db.reserve_shared_key_request(7, 2) == (True, 0)
    assert db.reserve_shared_key_request(7, 2) == (False, 0)
    assert db.get_shared_key_usage(7) == 2


def _quota_test_app():
    app = Flask(__name__)

    @app.before_request
    def authenticate_test_user():
        request.user = {"user_id": 12}

    @app.route("/generate", methods=["POST"])
    @shared_key_quota.shared_key_daily_quota
    def generate():
        return jsonify({"status": "ok"})

    @app.route("/api/evaluate", methods=["POST"])
    @shared_key_quota.shared_key_daily_quota
    def evaluate():
        return jsonify({"status": "ok"})

    return app


def test_shared_key_quota_returns_limit_message_and_headers(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "server-key")
    monkeypatch.setenv("SHARED_KEY_DAILY_LIMIT", "5")
    monkeypatch.setattr(
        shared_key_quota,
        "reserve_shared_key_request",
        lambda user_id, daily_limit: (False, 0),
    )

    response = _quota_test_app().test_client().post("/generate")

    assert response.status_code == 429
    assert "5 AI questions" in response.json["message"]
    assert response.headers["X-Shared-Key-Mode"] == "shared"
    assert response.headers["X-Shared-Key-Remaining"] == "0"
    assert response.headers["X-Shared-Key-Limit"] == "5"


def test_personal_key_bypasses_shared_daily_quota(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "server-key")

    def unexpected_reservation(*args):
        raise AssertionError("Personal-key requests must not consume shared quota")

    monkeypatch.setattr(
        shared_key_quota, "reserve_shared_key_request", unexpected_reservation
    )

    response = _quota_test_app().test_client().post(
        "/generate", headers={"X-Groq-API-Key": "user-key"}
    )

    assert response.status_code == 200
    assert response.headers["X-Shared-Key-Mode"] == "personal"


def test_evaluate_form_key_bypasses_shared_quota(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "server-key")

    def unexpected_reservation(*args):
        raise AssertionError("Personal-key requests must not consume shared quota")

    monkeypatch.setattr(
        shared_key_quota, "reserve_shared_key_request", unexpected_reservation
    )

    response = _quota_test_app().test_client().post(
        "/api/evaluate", data={"api_key": "user-key"}
    )

    assert response.status_code == 200
    assert response.headers["X-Shared-Key-Mode"] == "personal"


def test_other_form_key_does_not_bypass_shared_quota(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "server-key")
    reservations = []
    monkeypatch.setattr(
        shared_key_quota,
        "reserve_shared_key_request",
        lambda user_id, daily_limit: reservations.append(user_id) or (True, 19),
    )

    response = _quota_test_app().test_client().post(
        "/generate", data={"api_key": "ignored-user-key"}
    )

    assert response.status_code == 200
    assert reservations == [12]
    assert response.headers["X-Shared-Key-Mode"] == "shared"


def test_missing_server_key_requires_personal_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    response = _quota_test_app().test_client().post("/generate")

    assert response.status_code == 503
    assert "not configured" in response.json["message"]
