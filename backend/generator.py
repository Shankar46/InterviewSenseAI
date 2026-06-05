# backend/generator.py

import os
import re
import logging

from dotenv import load_dotenv
from huggingface_hub import InferenceClient

from backend.prompts import get_prompt

load_dotenv()
logger = logging.getLogger(__name__)

ACTIVE_MODEL = "Qwen/Qwen2.5-72B-Instruct"
MAX_HISTORY_TURNS = 4
MAX_CONTENT_CHARS = 4000

_SMALL_TALK = {
    "hello": "Hello! Welcome to InterviewSense AI. Choose Study mode for academic work or Career mode to build your roadmap.",
    "hi":    "Hi there! How can I help with your studies or interview preparation today?",
    "hey":   "Hey! Ready to get started? Ask me anything or upload a document.",
}

_client: InferenceClient | None = None


def _get_client() -> InferenceClient:
    global _client
    if _client is None:
        api_key = os.getenv("HF_TOKEN") or os.getenv("HF_API_KEY")
        if not api_key:
            raise EnvironmentError("No Hugging Face API key found. Set HF_TOKEN or HF_API_KEY.")
        _client = InferenceClient(provider="auto", api_key=api_key)
    return _client


def _extract_content(response) -> str:
    message = response.choices[0].message
    if isinstance(message, dict):
        return message.get("content", "").strip()
    return getattr(message, "content", "").strip()


def _normalize_history(history: list) -> list:
    """Return last N turns sanitised for the messages array."""
    clean = []
    for msg in (history or [])[-MAX_HISTORY_TURNS:]:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "")
        content = (msg.get("content") or "").strip()
        if role in {"user", "assistant"} and content and content != "__loading__":
            clean.append({"role": role, "content": content[:MAX_CONTENT_CHARS]})
    return clean


def _small_talk_reply(text: str) -> str | None:
    normalised = re.sub(r"[^a-z\s]", "", (text or "").strip().lower())
    return _SMALL_TALK.get(normalised)


def run_completion(messages: list, max_tokens: int = 1800, temperature: float = 0.3) -> str:
    """Low-level wrapper — raises on API errors so callers can handle them."""
    client = _get_client()
    response = client.chat_completion(
        model=ACTIVE_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return _extract_content(response)


def generate_notes(
    user_input: str,
    mode: str,
    task: str = "notes",
    chat_history: list = None,
    file_text: str = "",
) -> str:
    """
    Main entry point for the Study workspace.
    Returns a formatted string ready to send to the client.
    """
    history = _normalize_history(chat_history)

    # Handle greetings without hitting the model
    reply = _small_talk_reply(user_input)
    if reply:
        return reply

    prompt = get_prompt(
        task=task,
        topic=user_input,
        mode=mode,
        history=history,
        file_text=file_text,
    )

    system_msg = {
        "role": "system",
        "content": (
            "You are an elite academic AI that produces clear, well-structured output "
            "strictly matching the assigned task and format. Never mix formats."
        ),
    }

    messages = [system_msg] + history + [{"role": "user", "content": prompt}]

    try:
        return run_completion(messages)
    except EnvironmentError as e:
        logger.error("API key not configured: %s", e)
        return "⚠️ The AI provider token is not configured on the server. Please set HF_TOKEN."
    except Exception:
        logger.exception("Text generation failed.")
        return "⚠️ Generation service temporarily unavailable. Please try again in a moment."


def evaluate_quiz_answer(topic: str, user_answer: str) -> tuple[str, bool, int]:
    """
    Evaluates a quiz answer against the given topic.
    Returns (evaluation_text, passed: bool, score: int).
    """
    prompt = (
        f"You are a strict technical interviewer evaluating a candidate's answer.\n\n"
        f"TOPIC: {topic}\n\n"
        f"CANDIDATE ANSWER:\n{user_answer}\n\n"
        f"Evaluate the answer. Your response MUST follow this exact format:\n"
        f"STATUS: PASS or FAIL\n"
        f"SCORE: X/10\n"
        f"FEEDBACK:\n<2-4 sentences of specific gap analysis and what was correct or missing>"
    )

    try:
        result = run_completion(
            [{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.1,
        )
    except Exception:
        logger.exception("Quiz evaluation failed.")
        return ("Evaluation service is temporarily unavailable. Please try again.", False, 0)

    upper = result.upper()
    passed = "STATUS: PASS" in upper or (
        "STATUS: FAIL" not in upper and
        any(f"SCORE: {s}" in upper for s in ("6/10", "7/10", "8/10", "9/10", "10/10"))
    )

    score = 0
    score_match = re.search(r"SCORE:\s*(\d+)\s*/\s*10", result, re.IGNORECASE)
    if score_match:
        score = int(score_match.group(1))

    return (result, passed, score)