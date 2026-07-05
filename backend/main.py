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
    register_user,
    verify_user,
    create_user_session,
    invalidate_user_session,
    check_or_register_chat,
    get_connection,
    cleanup_expired_sessions,
)
from backend.generator import generate_notes
from backend.interview_assistant import (
    get_report      as get_interview_report,
    reset_interview_session,
    start_interview,
    submit_answer,
)
from backend.utils import extract_text, split_into_topic_blocks
from backend.rate_limit import rate_limit, periodic_cleanup
from functools import wraps

# Explicitly load .env from project root relative to this file
_dir = os.path.dirname(os.path.abspath(__file__))
_parent = os.path.dirname(_dir)
load_dotenv(os.path.join(_parent, ".env"))

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
        "http://127.0.0.1:5500,http://localhost:5500,http://127.0.0.1:5000,http://localhost:5000,http://127.0.0.1:8000,http://localhost:8000,null",
    ).split(",")
    if o.strip()
]
CORS(app, resources={r"/api/*": {"origins": _origins}, r"/generate": {"origins": _origins}})

# ── DB init ──────────────────────────────────────────────────
init_db()
periodic_cleanup()  # rate-limiter housekeeping thread

# Lazily purge expired sessions on a timer rather than on every login,
# so we don't add latency to the hot auth path.
import threading as _threading
def _session_gc_loop():
    import time
    while True:
        time.sleep(1800)
        try:
            cleanup_expired_sessions()
        except Exception:
            logger.exception("Session cleanup failed")
_threading.Thread(target=_session_gc_loop, daemon=True).start()

# In-memory PDF session cache: {chat_id: (expires_at, [{"title":..., "content":...}])}
# NOTE: this is process-local. If you run multiple gunicorn worker processes
# (recommended below), a user's PDF index lookup can land on a different
# worker than the one that cached it, producing "topic not found" errors.
# Two ways to fix that:
#   (a) run with --workers 1 --threads N (one process, many threads) — simplest,
#       fine up to moderate concurrency since the bottleneck is the LLM call,
#       not Python CPU time; or
#   (b) move this cache to Redis/SQLite, keyed by chat_id, with the same TTL.
# Default deployment below uses (a) for simplicity; switch to (b) if you need
# multiple processes for true multi-core scaling.
import time as _time
_pdf_cache: dict[str, tuple[float, list]] = {}
_PDF_CACHE_TTL = 3600
_pdf_cache_lock = _threading.Lock()


def _pdf_cache_set(chat_id: str, blocks: list):
    with _pdf_cache_lock:
        _pdf_cache[chat_id] = (_time.time() + _PDF_CACHE_TTL, blocks)
        if len(_pdf_cache) > 500:  # bound memory under sustained traffic
            now = _time.time()
            for k in [k for k, (exp, _) in _pdf_cache.items() if exp < now]:
                del _pdf_cache[k]


def _pdf_cache_get(chat_id: str):
    with _pdf_cache_lock:
        entry = _pdf_cache.get(chat_id)
        if not entry:
            return None
        expires_at, blocks = entry
        if _time.time() >= expires_at:
            del _pdf_cache[chat_id]
            return None
        return blocks


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


# ── Authentication Decorator & Helpers ────────────────────────

def get_current_user():
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]
    
    with get_connection() as conn:
        row = conn.execute(
            """SELECT u.user_id, u.username FROM user_sessions s
               JOIN users u ON s.user_id = u.user_id
               WHERE s.session_token = ? AND datetime('now') < s.expires_at""",
            (token,)
        ).fetchone()
        if row:
            return {"user_id": row["user_id"], "username": row["username"]}
    return None


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
        request.user = user
        return f(*args, **kwargs)
    return decorated_function


def check_chat_auth(chat_id):
    user_id = request.user["user_id"]
    logger.info("check_chat_auth: checking chat_id=%r for user_id=%d", chat_id, user_id)
    if not chat_id or chat_id == "default":
        pass
    if not check_or_register_chat(chat_id, user_id):
        logger.warning("check_chat_auth FORBIDDEN: chat_id=%r is not owned by user_id=%d", chat_id, user_id)
        return jsonify({"status": "error", "message": "Forbidden: You do not own this session."}), 403
    return None



# ── Route handler ─────────────────────────────────────────────

def _handle_request(req) -> object:
    topic         = req.form.get("topic", "").strip()
    mode          = _normalize_mode(req.form.get("mode", "10 Marks"))
    task          = req.form.get("task_type", "notes").strip().lower() or "notes"
    assistant     = req.form.get("assistant_type", "study").strip().lower() or "study"
    chat_id       = req.form.get("chat_id", "default").strip() or "default"
    
    # Ownership Check
    err = check_chat_auth(chat_id)
    if err:
        return err

    history       = _parse_field(req.form.get("history"), [])
    career_config = _parse_field(req.form.get("career_config"), {})
    api_key       = req.headers.get("X-HF-API-Key") or None

    # ── Career path ───────────────────────────────────────────
    if assistant == "career":
        result = generate_career_plan(
            user_input=topic,
            history=history,
            career_config=career_config,
            chat_id=chat_id,
            api_key=api_key,
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
            _pdf_cache_set(chat_id, blocks)
            index_lines = "\n".join(f"{i+1}. {b['title']}" for i, b in enumerate(blocks))
            return jsonify(_study_response(
                f"### Document Topics Extracted\n\n{index_lines}\n\n"
                f"Type a topic number to get detailed notes on that section."
            ))

    # Numeric input = user picking a topic from the PDF index
    if topic.isdigit() and _pdf_cache_get(chat_id):
        idx = int(topic) - 1
        blocks = _pdf_cache_get(chat_id)
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
                api_key=api_key,
            )
            return jsonify(_study_response(f"## {block['title']}\n\n{answer}"))

    # General query
    answer = generate_notes(
        user_input=topic,
        mode=mode,
        task=task,
        chat_history=history,
        file_text=file_text[:1200] if file_text else "",
        api_key=api_key,
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


# ── Auth Routes ──────────────────────────────────────────────

@app.route("/api/auth/register", methods=["POST"])
@rate_limit(5, 300, scope="register")
def auth_register():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    if not username or not password:
        return jsonify({"status": "error", "message": "Username and password are required."}), 400
    if len(username) < 3:
        return jsonify({"status": "error", "message": "Username must be at least 3 characters."}), 400
    if len(password) < 6:
        return jsonify({"status": "error", "message": "Password must be at least 6 characters."}), 400
        
    user_id = register_user(username, password)
    if user_id is None:
        return jsonify({"status": "error", "message": "Username already exists."}), 400
        
    return jsonify({"status": "ok", "message": "Registration successful. Please log in."})


@app.route("/api/auth/login", methods=["POST"])
@rate_limit(8, 60, scope="login")
def auth_login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    if not username or not password:
        return jsonify({"status": "error", "message": "Username and password are required."}), 400
        
    user = verify_user(username, password)
    if not user:
        return jsonify({"status": "error", "message": "Invalid username or password."}), 401
        
    token = create_user_session(user["user_id"])
    return jsonify({
        "status": "ok",
        "token": token,
        "username": user["username"]
    })


@app.route("/api/auth/logout", methods=["POST"])
@login_required
def auth_logout():
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        invalidate_user_session(token)
    return jsonify({"status": "ok", "message": "Logged out successfully."})


@app.route("/api/auth/me", methods=["GET"])
@login_required
def auth_me():
    return jsonify({
        "status": "ok",
        "username": request.user["username"]
    })


# ── Routes ───────────────────────────────────────────────────

@app.route("/api/workspace/generate", methods=["POST"])
@login_required
@rate_limit(20, 60, scope="generate")
def workspace_endpoint():
    try:
        return _handle_request(request)
    except Exception:
        logger.exception("Workspace request failed.")
        return _study_error("Workspace request failed. Please try again.")


@app.route("/api/edtech/generate", methods=["POST"])
@login_required
@rate_limit(20, 60, scope="generate")
def edtech_endpoint():
    try:
        return _handle_request(request)
    except Exception:
        logger.exception("Career request failed.")
        return _career_error("Career assistant request failed. Please try again.")


@app.route("/generate", methods=["POST"])
@login_required
def legacy_endpoint():
    """Legacy route — kept for backwards compatibility."""
    try:
        return _handle_request(request)
    except Exception:
        logger.exception("Legacy request failed.")
        return _study_error("Request failed. Please try again.")


@app.route("/api/edtech/reset", methods=["POST"])
@login_required
def reset_endpoint():
    """Clear awaiting_answers flag without deleting session data."""
    try:
        chat_id = request.form.get("chat_id", "default").strip() or "default"
        err = check_chat_auth(chat_id)
        if err:
            return err
        reset_awaiting_answers(chat_id)
        return jsonify({"status": "ok", "message": "Session flags reset."})
    except Exception:
        logger.exception("Reset failed.")
        return jsonify({"status": "error", "message": "Reset failed."}), 500


@app.route("/api/edtech/delete", methods=["POST"])
@login_required
def delete_session_endpoint():
    """Fully wipe a session and its progress from the DB."""
    try:
        chat_id = request.form.get("chat_id", "").strip()
        if not chat_id:
            return jsonify({"status": "error", "message": "chat_id required"}), 400
        err = check_chat_auth(chat_id)
        if err:
            return err
        delete_session(chat_id)
        return jsonify({"status": "ok", "message": "Session deleted."})
    except Exception:
        logger.exception("Session delete failed.")
        return jsonify({"status": "error", "message": "Delete failed."}), 500


@app.route("/api/edtech/stats", methods=["GET"])
@login_required
def stats_endpoint():
    """Return progress stats and streak for a chat session."""
    try:
        chat_id = request.args.get("chat_id", "default").strip() or "default"
        err = check_chat_auth(chat_id)
        if err:
            return err
        stats = get_progress_stats(chat_id)
        streak = get_streak(chat_id)
        return jsonify({"status": "ok", "stats": stats, "streak": streak})
    except Exception:
        logger.exception("Stats request failed.")
        return jsonify({"status": "error"}), 500


@app.route("/api/notifications", methods=["GET"])
@login_required
def notifications_endpoint():
    """Return unread notifications for a session."""
    try:
        chat_id = request.args.get("chat_id", "default").strip() or "default"
        err = check_chat_auth(chat_id)
        if err:
            return err
        notifs = get_unread_notifications(chat_id)
        return jsonify({"status": "ok", "notifications": notifs, "count": len(notifs)})
    except Exception:
        logger.exception("Notifications request failed.")
        return jsonify({"status": "error", "notifications": [], "count": 0}), 500


@app.route("/api/notifications/read", methods=["POST"])
@login_required
def mark_read_endpoint():
    """Mark all notifications as read for a session."""
    try:
        chat_id = request.form.get("chat_id", "default").strip() or "default"
        err = check_chat_auth(chat_id)
        if err:
            return err
        mark_notifications_read(chat_id)
        return jsonify({"status": "ok"})
    except Exception:
        logger.exception("Mark read failed.")
        return jsonify({"status": "error"}), 500


@app.route("/api/health", methods=["GET"])
def health_endpoint():
    return jsonify({"status": "ok", "service": "InterviewSense AI"})


# ── Interview routes ─────────────────────────────────────────

@app.route("/api/interview/start", methods=["POST"])
@login_required
def interview_start_endpoint():
    """Initialise a mock interview session and return the first question."""
    try:
        chat_id     = request.form.get("chat_id", "default").strip() or "default"
        err = check_chat_auth(chat_id)
        if err:
            return err
        role        = request.form.get("role", "Software Engineer").strip()
        company     = request.form.get("company", "the company").strip()
        jd_text     = request.form.get("jd_text", "").strip()
        resume_text = request.form.get("resume_text", "").strip()
        domain      = request.form.get("domain", "it").strip()
        round_type  = request.form.get("round_type", "tech").strip()
        weekly_career_day = int(request.form.get("weekly_career_day", "0").strip() or "0")

        # Support file uploads for JD / resume
        jd_file     = request.files.get("jd_file")
        resume_file = request.files.get("resume_file")
        if jd_file and jd_file.filename:
            jd_text     = extract_text(jd_file)[:4000] or jd_text
        if resume_file and resume_file.filename:
            resume_text = extract_text(resume_file)[:3000] or resume_text

        api_key = request.headers.get("X-HF-API-Key") or None
        result = start_interview(chat_id, role, company, jd_text, resume_text, domain, round_type, weekly_career_day, api_key=api_key)
        return jsonify(result)
    except Exception:
        logger.exception("Interview start failed.")
        return jsonify({"status": "error", "message": "Failed to start interview. Please try again."}), 500


@app.route("/api/interview/answer", methods=["POST"])
@login_required
def interview_answer_endpoint():
    """Evaluate a candidate's answer and return feedback + next question or report."""
    try:
        chat_id = request.form.get("chat_id", "default").strip() or "default"
        err = check_chat_auth(chat_id)
        if err:
            return err
        answer  = request.form.get("answer", "").strip()
        api_key = request.headers.get("X-HF-API-Key") or None
        result  = submit_answer(chat_id, answer, api_key=api_key)
        return jsonify(result)
    except Exception:
        logger.exception("Interview answer evaluation failed.")
        return jsonify({"status": "error", "message": "Evaluation failed. Please try again."}), 500


@app.route("/api/interview/report", methods=["GET"])
@login_required
def interview_report_endpoint():
    """Return the final interview report card."""
    try:
        chat_id = request.args.get("chat_id", "default").strip() or "default"
        err = check_chat_auth(chat_id)
        if err:
            return err
        api_key = request.headers.get("X-HF-API-Key") or None
        result  = get_interview_report(chat_id, api_key=api_key)
        return jsonify(result)
    except Exception:
        logger.exception("Interview report fetch failed.")
        return jsonify({"status": "error", "message": "Report unavailable."}), 500


@app.route("/api/interview/reset", methods=["POST"])
@login_required
def interview_reset_endpoint():
    """Wipe the interview session so the user can start fresh."""
    try:
        chat_id = request.form.get("chat_id", "").strip()
        if chat_id:
            err = check_chat_auth(chat_id)
            if err:
                return err
            reset_interview_session(chat_id)
        return jsonify({"status": "ok"})
    except Exception:
        logger.exception("Interview reset failed.")
        return jsonify({"status": "error"}), 500


@app.route("/api/ide/run", methods=["POST"])
@login_required
@rate_limit(10, 60, scope="ide")
def ide_run_endpoint():
    """Execute python, javascript, java, or cpp code safely using a remote sandboxed Judge0 API runtime."""
    import requests
    import re
    try:
        language = request.form.get("language", "python").strip().lower()
        code     = request.form.get("code", "").strip()

        if not code:
            return jsonify({"output": "No code provided."})

        # Preprocess Java code so public class matches Main (compiles inside Main.java in Judge0)
        if language == "java":
            code = re.sub(r"public\s+class\s+\w+", "public class Main", code)

        lang_id_map = {
            "python": 100,
            "javascript": 102,
            "js": 102,
            "java": 91,
            "cpp": 105,
            "c++": 105
        }

        lang_id = lang_id_map.get(language)
        if not lang_id:
            return jsonify({"output": f"Language '{language}' execution is not supported in the secure sandbox."})

        url = "https://ce.judge0.com/submissions?wait=true"
        payload = {
            "source_code": code,
            "language_id": lang_id
        }

        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code in (200, 201):
                res = r.json()
                status = res.get("status", {})
                status_id = status.get("id")
                status_desc = status.get("description", "Unknown Status")

                stdout = res.get("stdout") or ""
                stderr = res.get("stderr") or ""
                compile_output = res.get("compile_output") or ""

                if status_id == 6: # Compilation Error
                    output = f"Compilation Error:\n{compile_output}"
                elif status_id == 5: # Time Limit Exceeded
                    output = "Error: Code execution timed out (Time Limit Exceeded in sandbox)."
                else:
                    output = stdout
                    if stderr:
                        output += f"\nRuntime Error:\n{stderr}"
                    if not output:
                        output = f"Code executed successfully with status '{status_desc}' and no output."
            else:
                output = f"Sandbox API Error: Server returned status code {r.status_code}."
        except requests.Timeout:
            output = "Error: Sandbox request timed out (15 seconds limit)."
        except Exception as e:
            output = f"Execution Sandbox Error: Unable to complete code run request ({str(e)})."

        return jsonify({"output": output})
    except Exception as e:
        logger.exception("IDE execution failed")
        return jsonify({"output": f"Execution Error: {str(e)}"}), 500


@app.route("/api/agent", methods=["GET"])
def agent_health_check():
    return jsonify({"status": "InterviewSense AI Agent Endpoint Active"})


@app.route("/api/agent", methods=["POST"])
@login_required
@rate_limit(20, 60, scope="generate")
def agent_endpoint():
    """Replaces the old standalone backend/agent.py FastAPI app, which had
    no auth, no rate limit, and no chat ownership check on this same call."""
    try:
        payload = request.get_json(silent=True) or {}
        message = (payload.get("message") or "").strip()
        if not message:
            return jsonify({"status": "error", "message": "message is required"}), 400
        chat_id = (payload.get("chat_id") or "default").strip() or "default"
        err = check_chat_auth(chat_id)
        if err:
            return err
        api_key = request.headers.get("X-HF-API-Key") or None
        result = generate_career_plan(
            user_input=message,
            history=[],
            career_config={},
            chat_id=chat_id,
            api_key=api_key,
        )
        return jsonify({"status": "success", "data": result})
    except Exception as e:
        logger.exception("Agent endpoint failed.")
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        use_reloader=False,
    )