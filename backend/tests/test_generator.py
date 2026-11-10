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


class _ProviderError(Exception):
    def __init__(self, status_code=None):
        super().__init__(f"provider error {status_code}")
        self.status_code = status_code


def _client_that_raises(exc):
    def create(**kwargs):
        raise exc
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.mark.parametrize(
    ("status", "byok", "expected_cls", "http", "retryable"),
    [
        (401, True,  "LLMInvalidKey",    400, False),   # never 401: the UI logs the user out on 401
        (403, True,  "LLMInvalidKey",    400, False),
        (401, False, "LLMNotConfigured", 503, False),   # server key rejected = operator problem
        (402, False, "LLMUnavailable",   503, False),
        (404, False, "LLMNotConfigured", 503, False),
        (429, True,  "LLMRateLimited",   429, True),    # their own Groq account is rate-limited
        (429, False, "LLMRateLimited",   503, True),    # our shared key is busy: not the user's fault
        (500, False, "LLMUnavailable",   503, True),
        (None, False, "LLMUnavailable",  503, True),    # timeout / connection reset: no status at all
    ],
)
def test_run_completion_turns_provider_failures_into_typed_errors(monkeypatch, status, byok, expected_cls, http, retryable):
    from backend import llm_errors
    monkeypatch.setattr(generator, "_get_client", lambda api_key=None: _client_that_raises(_ProviderError(status)))

    with pytest.raises(llm_errors.LLMError) as caught:
        generator.run_completion([{"role": "user", "content": "hi"}], api_key="gsk-mine" if byok else None)

    err = caught.value
    assert type(err).__name__ == expected_cls
    assert err.http_status == http
    assert err.retryable is retryable
    assert err.http_status != 401
    assert err.user_message and "Traceback" not in err.user_message


def test_missing_server_key_is_a_clear_configuration_error(monkeypatch):
    from backend.llm_errors import LLMNotConfigured
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(LLMNotConfigured, match="GROQ_API_KEY"):
        generator.run_completion([{"role": "user", "content": "hi"}])


def test_empty_model_reply_is_an_error_not_a_blank_answer(monkeypatch):
    from backend.llm_errors import LLMBadOutput
    reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: reply)))
    monkeypatch.setattr(generator, "_get_client", lambda api_key=None: client)
    with pytest.raises(LLMBadOutput):
        generator.run_completion([{"role": "user", "content": "hi"}])


def test_generate_notes_lets_failures_propagate_and_never_caches_them(monkeypatch):
    from backend.llm_errors import LLMUnavailable
    calls = []

    def fail(*a, **k):
        calls.append(1)
        raise LLMUnavailable("down")

    monkeypatch.setattr(generator, "run_completion", fail)
    for _ in range(2):    # a second identical request must hit the provider again, not a cached error
        with pytest.raises(LLMUnavailable):
            generator.generate_notes(user_input="unique topic aaa111", mode="10 Marks")
    assert len(calls) == 2


def test_cache_key_covers_the_whole_document_and_the_model(monkeypatch):
    """Two different documents that start with the same 500 characters used to share one answer."""
    seen = []
    monkeypatch.setattr(generator, "run_completion", lambda messages, **kw: seen.append(messages[-1]["content"]) or f"answer-{len(seen)}")
    head = "Chapter 1. " + "x" * 600
    a = generator.generate_notes(user_input="summarise cachecase-77", mode="10 Marks", file_text=head + " ALPHA")
    b = generator.generate_notes(user_input="summarise cachecase-77", mode="10 Marks", file_text=head + " BETA")
    assert a != b and len(seen) == 2
    again = generator.generate_notes(user_input="summarise cachecase-77", mode="10 Marks", file_text=head + " ALPHA")
    assert again == a and len(seen) == 2      # a genuine repeat is still served from cache
