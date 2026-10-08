from backend.guardrails import (
    MAX_AI_FIELD_CHARS,
    MAX_AI_REQUEST_CHARS,
    validate_ai_input,
)


def test_accepts_normal_ai_request_fields():
    assert validate_ai_input(
        "/api/workspace/generate",
        {"topic": "Explain machine learning"},
        None,
    ) is None


def test_rejects_ai_field_over_limit():
    message = validate_ai_input(
        "/api/workspace/generate",
        {"topic": "x" * (MAX_AI_FIELD_CHARS + 1)},
        None,
    )

    assert message == (
        f"Each AI input field must be {MAX_AI_FIELD_CHARS:,} characters or fewer."
    )


def test_rejects_combined_json_text_over_limit():
    message = validate_ai_input(
        "/api/agent",
        {},
        {"message": [
            "x" * MAX_AI_FIELD_CHARS,
            "y" * MAX_AI_FIELD_CHARS,
            "z" * (MAX_AI_REQUEST_CHARS - 2 * MAX_AI_FIELD_CHARS + 1),
        ]},
    )

    assert message == (
        f"AI request text must be {MAX_AI_REQUEST_CHARS:,} characters or fewer in total."
    )


def test_does_not_restrict_non_ai_routes():
    assert validate_ai_input(
        "/api/sessions/chat/messages",
        {"content": "x" * (MAX_AI_FIELD_CHARS + 1)},
        None,
    ) is None
