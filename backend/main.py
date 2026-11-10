# backend/main.py

import json
import logging
import os
import re
import sys

# Ensure the project root is on the path when running directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

from backend.career_assistant import generate_career_plan, get_weekend_interview_status
from backend.db import (
    delete_session,
    get_progress_stats,
    get_session_messages,
    get_streak,
    get_unread_notifications,
    init_db,
    mark_notifications_read,
    reset_awaiting_answers,
    register_user,
    save_message,
    verify_user,
    create_user_session,
    invalidate_user_session,
    check_or_register_chat,
    get_user_by_token,
    cleanup_expired_sessions,
    delete_user_account,
    list_user_sessions,
    login_clear_failures,
    login_locked_for,
    login_record_failure,
    revoke_session_by_id,
    revoke_user_sessions,
    set_user_password,
    user_password_matches,
)
from backend.passwords import MAX_LOGIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH, validate_password, validate_username
from backend.generator import generate_notes, evaluate_study_answer
from backend.llm_errors import LLMError
from backend.guardrails import validate_ai_input
from backend.interview_assistant import (
    InterviewError,
    get_report      as get_interview_report,
    reset_interview_session,
    start_interview,
    submit_answer,
)
from backend.utils import extract_text, split_into_topic_blocks
from backend.rate_limit import client_ip, rate_limit, periodic_cleanup
from backend.shared_key_quota import shared_key_daily_quota, shared_key_usage
from functools import wraps

# Explicitly load .env from project root relative to this file
_dir = os.path.dirname(os.path.abspath(__file__))
_parent = os.path.dirname(_dir)
load_dotenv(os.path.join(_parent, ".env"))

# ── Flask app ────────────────────────────────────────────────
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "16")) * 1024 * 1024


@app.before_request
def validate_ai_request_size():
    message = validate_ai_input(
        request.path,
        request.form,
        request.get_json(silent=True),
    )
    if message:
        return jsonify({"status": "error", "message": message}), 413


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── CORS ─────────────────────────────────────────────────────
_origins = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://127.0.0.1:5500,http://localhost:5500,http://127.0.0.1:5000,http://localhost:5000,http://127.0.0.1:8000,http://localhost:8000,null",
    ).split(",")
    if o.strip()
]
CORS(
    app,
    resources={r"/api/*": {"origins": _origins}, r"/generate": {"origins": _origins}},
    expose_headers=["X-Shared-Key-Mode", "X-Shared-Key-Remaining", "X-Shared-Key-Limit"],
)

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


@app.errorhandler(LLMError)
def _handle_llm_error(err: LLMError):
    """One place that turns any AI failure into an honest HTTP reply:
    right status code, a message the UI already displays, and whether a retry can help."""
    response = jsonify(err.to_dict())
    response.status_code = err.http_status
    if err.retry_after:
        response.headers["Retry-After"] = str(err.retry_after)
    return response


# ── Authentication Decorator & Helpers ────────────────────────

def _bearer_token() -> str | None:
    """Extract the token from 'Authorization: Bearer <token>' (None if absent/malformed)."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def get_current_user():
    return get_user_by_token(_bearer_token())


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
        request.user = user
        return f(*args, **kwargs)
    return decorated_function


# chat ids are generated by the browser (crypto.randomUUID(), or the older
# "<timestamp>-<hex>" form). Accept only that alphabet/length so a client can't
# stuff huge or odd strings into the database.
_CHAT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def check_chat_auth(chat_id):
    """Return None if the logged-in user may use chat_id, else an error response.

    Previously a missing chat_id silently became the literal "default", which
    was one global session: the first user to touch it owned it and everyone
    else got 403. A chat_id is now required and must look like a real id."""
    user_id = request.user["user_id"]
    if not chat_id or chat_id == "default" or not _CHAT_ID_RE.match(chat_id):
        return jsonify({"status": "error", "message": "A valid chat_id is required."}), 400
    if not check_or_register_chat(chat_id, user_id):
        logger.warning("check_chat_auth FORBIDDEN: user_id=%d tried a chat they do not own", user_id)
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
    api_key       = req.headers.get("X-Groq-API-Key") or None

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

def _auth_ok(user_id: int, username: str, status: int = 200):
    """Create a session and return what the browser needs to stay signed in."""
    token = create_user_session(user_id, request.headers.get("User-Agent", ""))
    return jsonify({"status": "ok", "token": token, "username": username}), status


def _locked_response(wait_seconds: int):
    minutes = max(1, -(-wait_seconds // 60))          # round up
    response = jsonify({
        "status": "error", "code": "login_locked", "retryable": True, "retry_after": wait_seconds,
        "message": f"Too many failed attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
    })
    response.status_code = 429
    response.headers["Retry-After"] = str(wait_seconds)
    return response


@app.route("/api/auth/register", methods=["POST"])
@rate_limit(5, 300, scope="register")
def auth_register():
    """Create an account AND sign in, like other sites (it used to say "please log in" and
    make you type everything again). Passwords are used exactly as typed: no trimming."""
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if not username or not password:
        return jsonify({"status": "error", "message": "Username and password are required."}), 400
    problem = validate_username(username) or validate_password(password, username)
    if problem:
        return jsonify({"status": "error", "message": problem}), 400

    user_id = register_user(username, password)
    if user_id is None:
        return jsonify({"status": "error", "message": "That username is already taken."}), 409
    return _auth_ok(user_id, username, 201)


@app.route("/api/auth/login", methods=["POST"])
@rate_limit(8, 60, scope="login")
def auth_login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if not username or not password:
        return jsonify({"status": "error", "message": "Username and password are required."}), 400

    ip = client_ip()
    wait = login_locked_for(username, ip)
    if wait:
        return _locked_response(wait)             # even a correct password is refused while locked

    user = verify_user(username, password) if len(password) <= MAX_LOGIN_PASSWORD_LENGTH else None
    if not user:
        login_record_failure(username, ip)        # unknown usernames are counted too
        return jsonify({"status": "error", "message": "Invalid username or password."}), 401

    login_clear_failures(username, ip)
    return _auth_ok(user["user_id"], user["username"])


@app.route("/api/auth/logout", methods=["POST"])
@login_required
def auth_logout():
    token = _bearer_token()
    if token:
        invalidate_user_session(token)
    return jsonify({"status": "ok", "message": "Logged out successfully."})


@app.route("/api/auth/logout-all", methods=["POST"])
@login_required
def auth_logout_all():
    """Sign out of every device (including this one)."""
    count = revoke_user_sessions(request.user["user_id"])
    return jsonify({"status": "ok", "signed_out": count})


@app.route("/api/auth/sessions", methods=["GET"])
@login_required
def auth_sessions():
    return jsonify({"status": "ok", "sessions": list_user_sessions(request.user["user_id"], _bearer_token())})


@app.route("/api/auth/sessions/<session_id>", methods=["DELETE"])
@login_required
def auth_revoke_session(session_id):
    if not revoke_session_by_id(request.user["user_id"], session_id):
        return jsonify({"status": "error", "message": "Session not found."}), 404
    return jsonify({"status": "ok"})


def _confirm_current_password(field: str = "current_password"):
    """Sensitive actions re-ask for the password. Wrong attempts count toward the same
    lockout as sign-in, so a stolen token cannot be used to guess the password.
    Returns an error response, or None if the password is right."""
    username, ip = request.user["username"], client_ip()
    wait = login_locked_for(username, ip)
    if wait:
        return _locked_response(wait)
    password = request.form.get(field, "")
    if not password or len(password) > MAX_LOGIN_PASSWORD_LENGTH or not user_password_matches(request.user["user_id"], password):
        login_record_failure(username, ip)
        return jsonify({"status": "error", "message": "Your current password is incorrect."}), 403
    login_clear_failures(username, ip)
    return None


@app.route("/api/auth/change-password", methods=["POST"])
@login_required
@rate_limit(10, 300, scope="account")
def auth_change_password():
    err = _confirm_current_password("current_password")
    if err:
        return err
    new_password = request.form.get("new_password", "")
    problem = validate_password(new_password, request.user["username"])
    if problem:
        return jsonify({"status": "error", "message": problem}), 400
    if new_password == request.form.get("current_password", ""):
        return jsonify({"status": "error", "message": "The new password must be different."}), 400
    set_user_password(request.user["user_id"], new_password)
    # A password change must lock out whoever else had access: end every OTHER session.
    others = revoke_user_sessions(request.user["user_id"], keep_token=_bearer_token())
    return jsonify({"status": "ok", "message": "Password changed.", "other_sessions_signed_out": others})


@app.route("/api/auth/delete-account", methods=["POST"])
@login_required
@rate_limit(5, 300, scope="account")
def auth_delete_account():
    """Permanently delete the account and all of its data (asks for the password first)."""
    err = _confirm_current_password("password")
    if err:
        return err
    delete_user_account(request.user["user_id"])
    return jsonify({"status": "ok", "message": "Your account and all its data were deleted."})


@app.route("/api/auth/me", methods=["GET"])
@login_required
def auth_me():
    return jsonify({
        "status": "ok",
        "username": request.user["username"]
    })


@app.route("/api/usage", methods=["GET"])
@login_required
def usage_endpoint():
    return jsonify({"status": "ok", "quota": shared_key_usage(request.user["user_id"])})


# ── Routes ───────────────────────────────────────────────────

@app.route("/api/workspace/generate", methods=["POST"])
@login_required
@rate_limit(20, 60, scope="generate")
@shared_key_daily_quota(lazy=True)
def workspace_endpoint():
    try:
        return _handle_request(request)
    except LLMError:
        raise          # handled by _handle_llm_error (honest status code)
    except Exception:
        logger.exception("Workspace request failed.")
        return _study_error("Workspace request failed. Please try again.")


@app.route("/api/edtech/generate", methods=["POST"])
@login_required
@rate_limit(20, 60, scope="generate")
@shared_key_daily_quota(lazy=True)
def edtech_endpoint():
    try:
        return _handle_request(request)
    except LLMError:
        raise          # handled by _handle_llm_error (honest status code)
    except Exception:
        logger.exception("Career request failed.")
        return _career_error("Career assistant request failed. Please try again.")


@app.route("/generate", methods=["POST"])
@login_required
@rate_limit(20, 60, scope="generate")
@shared_key_daily_quota(lazy=True)
def legacy_endpoint():
    """Legacy route — kept for backwards compatibility."""
    try:
        return _handle_request(request)
    except LLMError:
        raise          # handled by _handle_llm_error (honest status code)
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

_INTERVIEW_DOMAINS = {"it", "non-it"}
_INTERVIEW_ROUNDS  = {"tech", "hr"}
_MAX_NAME_CHARS    = 120


def _bad_request(message: str):
    return jsonify({"status": "error", "message": message}), 400


@app.errorhandler(InterviewError)
def _handle_interview_error(err: InterviewError):
    """Wrong session state or bad input: a 4xx the UI can show, never a blind 500."""
    return jsonify({"status": "error", "message": err.message}), err.http_status


@app.route("/api/interview/start", methods=["POST"])
@login_required
@rate_limit(20, 60, scope="generate")
@shared_key_daily_quota(lazy=True)
def interview_start_endpoint():
    """Initialise a mock interview session and return the first question."""
    chat_id = request.form.get("chat_id", "").strip()
    err = check_chat_auth(chat_id)
    if err:
        return err

    role        = request.form.get("role", "Software Engineer").strip() or "Software Engineer"
    company     = request.form.get("company", "the company").strip() or "the company"
    jd_text     = request.form.get("jd_text", "").strip()
    resume_text = request.form.get("resume_text", "").strip()
    domain      = request.form.get("domain", "it").strip()
    round_type  = request.form.get("round_type", "tech").strip()
    if len(role) > _MAX_NAME_CHARS or len(company) > _MAX_NAME_CHARS:
        return _bad_request(f"Role and company must be at most {_MAX_NAME_CHARS} characters.")
    if domain not in _INTERVIEW_DOMAINS:
        return _bad_request("domain must be 'it' or 'non-it'.")
    if round_type not in _INTERVIEW_ROUNDS:
        return _bad_request("round_type must be 'tech' or 'hr'.")
    try:
        weekly_career_day = int(request.form.get("weekly_career_day", "0").strip() or "0")
    except ValueError:
        return _bad_request("weekly_career_day must be a whole number.")
    if not 0 <= weekly_career_day <= 400:
        return _bad_request("weekly_career_day is out of range.")

    try:
        # Support file uploads for JD / resume
        jd_file     = request.files.get("jd_file")
        resume_file = request.files.get("resume_file")
        if jd_file and jd_file.filename:
            jd_text     = extract_text(jd_file)[:4000] or jd_text
        if resume_file and resume_file.filename:
            resume_text = extract_text(resume_file)[:3000] or resume_text

        api_key = request.headers.get("X-Groq-API-Key") or None
        result = start_interview(chat_id, role, company, jd_text, resume_text, domain, round_type, weekly_career_day, api_key=api_key)
        return jsonify(result)
    except (LLMError, InterviewError):
        raise                      # handled above with the right status code
    except Exception:
        logger.exception("Interview start failed.")
        return jsonify({"status": "error", "message": "Failed to start interview. Please try again."}), 500


@app.route("/api/interview/answer", methods=["POST"])
@login_required
@rate_limit(20, 60, scope="generate")
@shared_key_daily_quota(lazy=True)
def interview_answer_endpoint():
    """Grade a candidate's answer and return feedback + next question or report."""
    chat_id = request.form.get("chat_id", "").strip()
    err = check_chat_auth(chat_id)
    if err:
        return err
    answer = request.form.get("answer", "").strip()
    raw_q  = request.form.get("q_num", "").strip()
    try:
        q_num = int(raw_q) if raw_q else None
    except ValueError:
        return _bad_request("q_num must be a whole number.")
    try:
        api_key = request.headers.get("X-Groq-API-Key") or None
        return jsonify(submit_answer(chat_id, answer, api_key=api_key, q_num=q_num))
    except (LLMError, InterviewError):
        raise
    except Exception:
        logger.exception("Interview answer evaluation failed.")
        return jsonify({"status": "error", "message": "Evaluation failed. Please try again."}), 500


@app.route("/api/interview/report", methods=["GET"])
@login_required
@rate_limit(20, 60, scope="generate")
@shared_key_daily_quota(lazy=True)
def interview_report_endpoint():
    """Return the interview report card. Read-only: viewing it changes nothing."""
    chat_id = request.args.get("chat_id", "").strip()
    err = check_chat_auth(chat_id)
    if err:
        return err
    try:
        api_key = request.headers.get("X-Groq-API-Key") or None
        return jsonify(get_interview_report(chat_id, api_key=api_key))
    except (LLMError, InterviewError):
        raise
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
@shared_key_daily_quota(lazy=True)
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
        api_key = request.headers.get("X-Groq-API-Key") or None
        result = generate_career_plan(
            user_input=message,
            history=[],
            career_config={},
            chat_id=chat_id,
            api_key=api_key,
        )
        return jsonify({"status": "success", "data": result})
    except LLMError:
        raise
    except Exception:
        logger.exception("Agent endpoint failed.")
        return jsonify({"status": "error", "message": "Request failed. Please try again."}), 500


# ── Entry point ───────────────────────────────────────────────


# ── Message persistence endpoints ─────────────────────────────

MAX_MESSAGE_CHARS = 20_000
_MESSAGE_ROLES = {"user", "assistant"}


@app.route("/api/sessions/<session_id>/messages", methods=["GET"])
@login_required
def get_messages_endpoint(session_id):
    """Load saved messages for a session the caller owns."""
    err = check_chat_auth(session_id)
    if err:
        return err
    try:
        msgs = get_session_messages(session_id, limit=200)
        return jsonify({"status": "ok", "messages": msgs})
    except Exception:
        logger.exception("Get messages failed.")
        return jsonify({"status": "error", "message": "Could not load messages."}), 500


@app.route("/api/sessions/<session_id>/messages", methods=["POST"])
@login_required
@rate_limit(120, 60, scope="messages")
def save_message_endpoint(session_id):
    """Save one message. Accepts JSON or form data (the old client sent form
    data while the old server only read JSON, so nothing was ever stored)."""
    err = check_chat_auth(session_id)
    if err:
        return err
    data    = request.get_json(silent=True) or request.form
    role    = (data.get("role") or "").strip()
    content = (data.get("content") or "").strip()
    if role not in _MESSAGE_ROLES:
        return jsonify({"status": "error", "message": "role must be 'user' or 'assistant'."}), 400
    if not content or content == "__loading__":
        return jsonify({"status": "ok", "saved": False})
    if len(content) > MAX_MESSAGE_CHARS:
        return jsonify({"status": "error", "message": f"Message is over {MAX_MESSAGE_CHARS:,} characters."}), 413
    try:
        save_message(session_id, role, content)
    except Exception:
        logger.exception("Save message failed.")
        return jsonify({"status": "error", "message": "Could not save message."}), 500
    return jsonify({"status": "ok", "saved": True})


# ── Evaluate endpoint ─────────────────────────────────────────

@app.route("/api/evaluate", methods=["POST"])
@login_required
@rate_limit(20, 60, scope="generate")
@shared_key_daily_quota(lazy=True)
def evaluate_endpoint():
    """Standalone rubric evaluation for study workspace."""
    try:
        topic       = request.form.get("topic", "General Knowledge").strip()
        answer      = request.form.get("answer", "").strip()
        answer_type = request.form.get("answer_type", "exam").strip()
        api_key     = request.headers.get("X-Groq-API-Key") or request.form.get("api_key", "").strip() or None
        if not answer:
            return jsonify({"status": "error", "message": "No answer provided."}), 400
        result = evaluate_study_answer(answer, topic, answer_type, api_key=api_key)
        return jsonify({"status": "ok", "evaluation": result})
    except LLMError:
        raise
    except Exception:
        logger.exception("Evaluation endpoint failed.")
        return jsonify({"status": "error", "message": "Evaluation failed."}), 500


# ── Weekend status endpoint ───────────────────────────────────

@app.route("/api/edtech/weekend", methods=["GET"])
@login_required
def weekend_status_endpoint():
    """Check if weekend mock interview is available for this session."""
    chat_id = request.args.get("chat_id", "").strip()
    err = check_chat_auth(chat_id)
    if err:
        return err
    try:
        from backend.db import load_session_state
        state   = load_session_state(chat_id)
        weekend = get_weekend_interview_status(chat_id, state) if state else None
        return jsonify({"status": "ok", "weekend": weekend})
    except Exception:
        logger.exception("Weekend status failed.")
        return jsonify({"status": "ok", "weekend": None})


if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
        use_reloader=False,
    )