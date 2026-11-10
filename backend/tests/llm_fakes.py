# backend/tests/llm_fakes.py
# A scripted stand-in for the Groq client plus small request helpers shared by the
# integration tests. Items pushed onto the provider are reply strings or exceptions.
import json
import threading
from types import SimpleNamespace

CFG = {"role": "Python Developer", "duration": "30 days", "level": "beginner"}


class ProviderError(Exception):
    def __init__(self, status_code=None):
        super().__init__(f"provider error {status_code}")
        self.status_code = status_code


class FakeProvider:
    def __init__(self):
        self.script, self.calls, self.last_prompt = [], 0, ""
        self._lock = threading.Lock()

    def push(self, *items):
        self.script.extend(items)

    @property
    def chat(self):
        return SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        with self._lock:
            self.calls += 1
            self.last_prompt = kwargs["messages"][-1]["content"]
            item = self.script.pop(0) if self.script else "default stub answer"
        if isinstance(item, Exception):
            raise item
        msg = SimpleNamespace(content=item)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")])


def plan_json(n=30):
    return json.dumps([{"topic": f"AI Topic {i + 1}", "focus": f"Focus {i + 1}"} for i in range(n)])


def verdict(score, feedback="Solid explanation."):
    return json.dumps({"score": score, "feedback": feedback})


def used(client, headers):
    return client.get("/api/usage", headers=headers).get_json()["quota"]["requests_used"]


def career(client, headers, chat, text):
    return client.post("/api/edtech/generate", headers=headers,
                       data={"assistant_type": "career", "topic": text, "chat_id": chat,
                             "career_config": json.dumps(CFG)})
