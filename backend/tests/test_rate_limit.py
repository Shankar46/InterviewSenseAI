# backend/tests/test_rate_limit.py
from flask import Flask
from backend.rate_limit import rate_limit


def _make_app():
    app = Flask(__name__)

    @app.route("/limited", methods=["POST"])
    @rate_limit(3, 60, scope="test_limited")
    def limited():
        return {"ok": True}

    return app


def test_allows_requests_under_the_limit():
    app = _make_app()
    client = app.test_client()
    for _ in range(3):
        resp = client.post("/limited")
        assert resp.status_code == 200


def test_blocks_requests_over_the_limit():
    app = _make_app()
    client = app.test_client()
    for _ in range(3):
        client.post("/limited")
    resp = client.post("/limited")
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


def test_different_ips_have_independent_limits():
    app = _make_app()
    client = app.test_client()
    for _ in range(3):
        resp = client.post("/limited", environ_overrides={"REMOTE_ADDR": "1.1.1.1"})
        assert resp.status_code == 200
    # A different client IP should not be blocked by the first client's usage
    resp = client.post("/limited", environ_overrides={"REMOTE_ADDR": "2.2.2.2"})
    assert resp.status_code == 200