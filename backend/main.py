# backend/main.py

import json
import logging
import os
import sys

# Ensure the project root is on the path when running directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

from backend.career_assistant import generate_career_plan
from backend.db import (
    delete_session,
    get_progress_stats,
    get_streak,
    get_unread_notifications,
    init_db,
    mark_notifications_read,
    reset_awaiting_answers,
)
from backend.generator import generate_notes
from backend.utils import extract_text, split_into_topic_blocks

load_dotenv()

# Normalise token env var
if not os.getenv("HF_TOKEN") and os.getenv("HF_API_KEY"):
    os.environ["HF_TOKEN"] = os.environ["HF_API_KEY"]

# ── Flask app ────────────────────────────────────────────────
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "16")) * 1024 * 1024

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
logging.getLogger("transformers").setLevel(logging.ERROR)

# ── CORS ─────────────────────────────────────────────────────
_origins = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:5500,http://localhost:5500,http://127.0.0.1:5000,http://localhost:5000,null",
    ).split(",")
    if o.strip()
]
CORS(app, resources={r"/api/*": {"origins": _origins}, r"/generate": {"origins": _origins}})

# ── DB init ──────────────────────────────────────────────────
init_db()

# In-memory PDF session cache: {chat_id: [{"title": ..., "content": ...}]}
_pdf_cache: dict[str, list] = {}


# ── Helpers ──────────────────────────────────────────────────

def _parse_field(raw, default):
    """Safe JSON parse of a form field, returns default on failure."""
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, type(default)) else default
    except (json.JSONDecodeError, ValueError):
        return default


def _normalize_mode(raw: str) -> str:
    return {"2M": "2 Marks", "5M": "5 Marks", "10M": "10 Marks"}.get(raw, raw or "10 Marks")


def _study_response(answer: str) -> dict:
    return {"answer": answer, "progress": {}}


def _career_error(msg: str) -> tuple:
    return jsonify({"text": msg, "tracker": [{"day": 1, "status": "pending"}]}), 500


def _study_error(msg: str) -> tuple:
    return jsonify({"answer": msg, "progress": {}}), 500


# ── Route handler ─────────────────────────────────────────────

def _handle_request(req) -> object:
    topic         = req.form.get("topic", "").strip()
    mode          = _normalize_mode(req.form.get("mode", "10 Marks"))
    task          = req.form.get("task_type", "notes").strip().lower() or "notes"
    assistant     = req.form.get("assistant_type", "study").strip().lower() or "study"
    chat_id       = req.form.get("chat_id", "default").strip() or "default"
    history       = _parse_field(req.form.get("history"), [])
    career_config = _parse_field(req.form.get("career_config"), {})

    # ── Career path ───────────────────────────────────────────
    if assistant == "career":
        result = generate_career_plan(
            user_input=topic,
            history=history,
            career_config=career_config,
            chat_id=chat_id,
        )
        if isinstance(result, dict):
            return jsonify(result)
        return jsonify({"answer": result, "progress": {}})

    # ── Study path ────────────────────────────────────────────
    file = req.files.get("file")
    file_text = ""

    if file and file.filename:
        file_text = extract_text(file)

        # Document-wide summary request → return topic index
        if _is_doc_wide_request(topic) and file_text:
            blocks = split_into_topic_blocks(file_text)
            if not blocks:
                blocks = [{"title": "Document Overview", "content": file_text[:2000]}]
            _pdf_cache[chat_id] = blocks
            index_lines = "\n".join(f"{i+1}. {b['title']}" for i, b in enumerate(blocks))
            return jsonify(_study_response(
                f"### Document Topics Extracted\n\n{index_lines}\n\n"
                f"Type a topic number to get detailed notes on that section."
            ))

    # Numeric input = user picking a topic from the PDF index
    if topic.isdigit() and chat_id in _pdf_cache:
        idx = int(topic) - 1
        blocks = _pdf_cache[chat_id]
        if 0 <= idx < len(blocks):
            block = blocks[idx]
            query = (
                f"Explain ONLY this topic using the provided content.\n\n"
                f"TOPIC: {block['title']}\n\n"
                f"CONTENT: {block['content']}"
            )
            answer = generate_notes(
                user_input=query,
                mode=mode,
                task=task,
                chat_history=[],
                file_text=block["content"][:1200],
            )
            return jsonify(_study_response(f"## {block['title']}\n\n{answer}"))

    # General query
    answer = generate_notes(
        user_input=topic,
        mode=mode,
        task=task,
        chat_history=history,
        file_text=file_text[:1200] if file_text else "",
    )
    return jsonify(_study_response(answer))


def _is_doc_wide_request(topic: str) -> bool:
    keywords = {
        "full pdf", "whole pdf", "entire pdf", "all topics",
        "each topic", "every topic", "explain pdf", "summarize pdf",
        "summarise pdf", "list topics", "show topics", "extract topics",
    }
    t = (topic or "").lower()
    return not topic or any(kw in t for kw in keywords)


# ── Routes ───────────────────────────────────────────────────

@app.route("/api/workspace/generate", methods=["POST"])
def workspace_endpoint():
    try:
        return _handle_request(request)
    except Exception:
        logger.exception("Workspace request failed.")
        return _study_error("Workspace request failed. Please try again.")


@app.route("/api/edtech/generate", methods=["POST"])
def edtech_endpoint():
    try:
        return _handle_request(request)
    except Exception:
        logger.exception("Career request failed.")
        return _career_error("Career assistant request failed. Please try again.")


@app.route("/generate", methods=["POST"])
def legacy_endpoint():
    """Legacy route — kept for backwards compatibility."""
    try:
        return _handle_request(request)
    except Exception:
        logger.exception("Legacy request failed.")
        return _study_error("Request failed. Please try again.")


@app.route("/api/edtech/reset", methods=["POST"])
def reset_endpoint():
    """Clear awaiting_answers flag without deleting session data."""
    try:
        chat_id = request.form.get("chat_id", "default").strip() or "default"
        reset_awaiting_answers(chat_id)
        return jsonify({"status": "ok", "message": "Session flags reset."})
    except Exception:
        logger.exception("Reset failed.")
        return jsonify({"status": "error", "message": "Reset failed."}), 500


@app.route("/api/edtech/delete", methods=["POST"])
def delete_session_endpoint():
    """Fully wipe a session and its progress from the DB."""
    try:
        chat_id = request.form.get("chat_id", "").strip()
        if not chat_id:
            return jsonify({"status": "error", "message": "chat_id required"}), 400
        delete_session(chat_id)
        return jsonify({"status": "ok", "message": "Session deleted."})
    except Exception:
        logger.exception("Session delete failed.")
        return jsonify({"status": "error", "message": "Delete failed."}), 500


@app.route("/api/edtech/stats", methods=["GET"])
def stats_endpoint():
    """Return progress stats and streak for a chat session."""
    try:
        chat_id = request.args.get("chat_id", "default").strip() or "default"
        stats = get_progress_stats(chat_id)
        streak = get_streak(chat_id)
        return jsonify({"status": "ok", "stats": stats, "streak": streak})
    except Exception:
        logger.exception("Stats request failed.")
        return jsonify({"status": "error"}), 500


@app.route("/api/notifications", methods=["GET"])
def notifications_endpoint():
    """Return unread notifications for a session."""
    try:
        chat_id = request.args.get("chat_id", "default").strip() or "default"
        notifs = get_unread_notifications(chat_id)
        return jsonify({"status": "ok", "notifications": notifs, "count": len(notifs)})
    except Exception:
        logger.exception("Notifications request failed.")
        return jsonify({"status": "error", "notifications": [], "count": 0}), 500


@app.route("/api/notifications/read", methods=["POST"])
def mark_read_endpoint():
    """Mark all notifications as read for a session."""
    try:
        chat_id = request.form.get("chat_id", "default").strip() or "default"
        mark_notifications_read(chat_id)
        return jsonify({"status": "ok"})
    except Exception:
        logger.exception("Mark read failed.")
        return jsonify({"status": "error"}), 500


@app.route("/api/health", methods=["GET"])
def health_endpoint():
    return jsonify({"status": "ok", "service": "InterviewSense AI"})


# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        use_reloader=False,
    )
