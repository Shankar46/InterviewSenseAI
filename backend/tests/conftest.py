# backend/tests/conftest.py
#
# Shared test setup. Two jobs:
#   1. Point the app at a throw-away SQLite file BEFORE backend.db is imported,
#      so tests never touch (or depend on) a developer's real database.
#   2. Reset process-global state between tests. The old rate-limit tests
#      leaked counters into each other and only passed in one particular order.
import os
import tempfile
import uuid

_TMP = tempfile.mkdtemp(prefix="isai-tests-")
os.environ["SQLITE_PATH"] = os.path.join(_TMP, "test.db")
os.environ.pop("DATABASE_URL", None)
os.environ["PASSWORD_HASH_FAST"] = "1"      # cheap scrypt in tests; production cost is checked in test_passwords.py
os.environ.setdefault("GROQ_API_KEY", "test-server-key")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_global_state():
    from backend import rate_limit
    with rate_limit._lock:
        rate_limit._hits.clear()
    yield


@pytest.fixture()
def client():
    from backend.main import app
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def make_user(client):
    """Create + log in a unique user; returns (Authorization headers, username)."""
    def _make():
        name = "u" + uuid.uuid4().hex[:10]
        client.post("/api/auth/register", data={"username": name, "password": "Tr0ub4dor-Test-pw"})
        r = client.post("/api/auth/login", data={"username": name, "password": "Tr0ub4dor-Test-pw"})
        assert r.status_code == 200, r.get_json()
        return {"Authorization": "Bearer " + r.get_json()["token"]}, name
    return _make


@pytest.fixture()
def chat_id():
    return str(uuid.uuid4())


@pytest.fixture()
def provider(monkeypatch):
    """Scripted fake AI provider. Each test file sets SHARED_KEY_DAILY_LIMIT to what it needs."""
    from backend import generator
    from backend.tests.llm_fakes import FakeProvider
    p = FakeProvider()
    monkeypatch.setattr(generator, "_get_client", lambda api_key=None: p)
    return p
