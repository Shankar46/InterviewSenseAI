from collections.abc import Mapping


AI_REQUEST_PATHS = {
    "/api/workspace/generate",
    "/api/edtech/generate",
    "/generate",
    "/api/interview/start",
    "/api/interview/answer",
    "/api/interview/report",
    "/api/agent",
    "/api/evaluate",
}

MAX_AI_FIELD_CHARS = 12_000
MAX_AI_REQUEST_CHARS = 30_000


def _text_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for nested_value in value.values():
            yield from _text_values(nested_value)
    elif isinstance(value, (list, tuple)):
        for nested_value in value:
            yield from _text_values(nested_value)


def validate_ai_input(path: str, form, json_payload) -> str | None:
    """Return a client-safe validation message for oversized AI text input."""
    if path not in AI_REQUEST_PATHS:
        return None

    values = []
    if form:
        if hasattr(form, "lists"):
            values.extend(value for _, field_values in form.lists() for value in field_values)
        else:
            values.extend(value for _, value in form.items())
    values.extend(_text_values(json_payload))

    total_chars = 0
    for value in values:
        value_length = len(value)
        if value_length > MAX_AI_FIELD_CHARS:
            return f"Each AI input field must be {MAX_AI_FIELD_CHARS:,} characters or fewer."
        total_chars += value_length
        if total_chars > MAX_AI_REQUEST_CHARS:
            return f"AI request text must be {MAX_AI_REQUEST_CHARS:,} characters or fewer in total."
    return None
