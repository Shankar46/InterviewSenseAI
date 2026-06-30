# backend/evaluator.py
# Thin wrapper kept for any external callers that import this module directly.

from backend.generator import evaluate_quiz_answer


def evaluate_answers(user_answer: str, topic: str = "General Engineering Concepts", api_key: str = None) -> str:
    """
    Evaluate a user's quiz answer against the given topic.
    Returns the formatted evaluation string.
    """
    evaluation_text, passed, score = evaluate_quiz_answer(topic, user_answer, api_key=api_key)
    return evaluation_text
