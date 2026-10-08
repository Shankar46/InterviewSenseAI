from types import SimpleNamespace

import pytest

from backend import generator


@pytest.fixture(autouse=True)
def clear_cached_client(monkeypatch):
    monkeypatch.setattr(generator, "_client", None)


def test_get_client_uses_explicit_groq_key(monkeypatch):
    created = []

    class FakeGroq:
        def __init__(self, api_key):
            self.api_key = api_key
            created.append(self)

    monkeypatch.setattr(generator, "Groq", FakeGroq)

    client = generator._get_client("gsk-user-key")

    assert client.api_key == "gsk-user-key"
    assert len(created) == 1


def test_get_client_uses_groq_environment_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-server-key")

    class FakeGroq:
        def __init__(self, api_key):
            self.api_key = api_key

    monkeypatch.setattr(generator, "Groq", FakeGroq)

    assert generator._get_client().api_key == "gsk-server-key"
    assert generator._get_client() is generator._client


def test_get_client_requires_groq_environment_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(EnvironmentError, match="GROQ_API_KEY"):
        generator._get_client()


def test_run_completion_uses_groq_chat_completions(monkeypatch):
    calls = {}
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: (
                    calls.update(kwargs)
                    or SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(content="  Groq response  ")
                            )
                        ]
                    )
                )
            )
        )
    )
    monkeypatch.setattr(generator, "_get_client", lambda api_key=None: client)

    result = generator.run_completion(
        [{"role": "user", "content": "Hello"}],
        max_tokens=123,
        temperature=0.2,
        api_key="gsk-user-key",
    )

    assert result == "Groq response"
    assert calls == {
        "model": generator.ACTIVE_MODEL,
        "messages": [
            generator._SAFETY_SYSTEM_MESSAGE,
            {"role": "user", "content": "Hello"},
        ],
        "max_completion_tokens": 123,
        "temperature": 0.2,
    }


@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (401, "Groq rejected the API key"),
        (402, "no available API credits"),
        (429, "usage or rate limit"),
        (404, "was not found or is unavailable"),
    ],
)
def test_generate_notes_explains_groq_api_errors(monkeypatch, status_code, message):
    class GroqApiError(Exception):
        def __init__(self):
            self.status_code = status_code

    def fail_completion(*args, **kwargs):
        raise GroqApiError()

    monkeypatch.setattr(generator, "run_completion", fail_completion)

    response = generator.generate_notes(
        user_input="Explain a unique test topic",
        mode="10 Marks",
        task="review",
    )

    assert message in response
