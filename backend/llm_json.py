# backend/llm_json.py
import json
import re

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str):
    """Return the first JSON object/array found in a model reply.

    Models wrap JSON in ```fences```, add "Here is the result:", or append notes.
    json.JSONDecoder.raw_decode parses exactly one value from the start of the
    string and ignores what follows, so we try each '{' / '[' until one parses.
    """
    if not text or not text.strip():
        raise ValueError("empty model reply")
    s = text.strip()
    fenced = _FENCE.search(s)
    if fenced:
        s = fenced.group(1).strip()
    decoder = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch in "{[":
            try:
                value, _ = decoder.raw_decode(s[i:])
                return value
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON value found in model reply")
