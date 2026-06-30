import os
import json
import logging
import sqlite3
import hashlib
import secrets
from contextlib import contextmanager

if os.environ.get("VERCEL"):
    DB_NAME = "/tmp/interviewsense.db"
else:
    DB_NAME = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "interviewsense.db")
logger = logging.getLogger(__name__)


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_NAME, timeout=15, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _safe_json_list(raw: str) -> list:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, ValueError):
        logger.warning("Discarding corrupt JSON column value.")
        return []


def init_db():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username        TEXT UNIQUE NOT NULL,
                password_hash   TEXT NOT NULL,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS user_sessions (
                session_token   TEXT PRIMARY KEY,
                user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                expires_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_chats (
                chat_id         TEXT PRIMARY KEY,
                user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS course_sessions (
                chat_id         TEXT PRIMARY KEY,
                role            TEXT    NOT NULL DEFAULT 'Python Developer',
                duration_days   INTEGER NOT NULL DEFAULT 30,
                hours_per_day   TEXT    NOT NULL DEFAULT '2',
                level           TEXT    NOT NULL DEFAULT 'beginner',
                dsa_track       TEXT    NOT NULL DEFAULT 'yes',
                current_day     INTEGER NOT NULL DEFAULT 1,
                started         INTEGER NOT NULL DEFAULT 0,
                awaiting_answers INTEGER NOT NULL DEFAULT 0,
                last_quiz       TEXT    NOT NULL DEFAULT '',
                day_plan        TEXT    NOT NULL DEFAULT '[]',
                created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS progress (
                chat_id         TEXT NOT NULL,
                day             INTEGER NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending',
                score           INTEGER,
                completion_date TEXT,
                notes           TEXT,
                PRIMARY KEY (chat_id, day)
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id         TEXT NOT NULL,
                type            TEXT NOT NULL DEFAULT 'info',
                title           TEXT NOT NULL,
                body            TEXT NOT NULL DEFAULT '',
                is_read         INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS interview_sessions (
                chat_id       TEXT    PRIMARY KEY,
                role          TEXT    NOT NULL DEFAULT '',
                company       TEXT    NOT NULL DEFAULT '',
                jd_text       TEXT    NOT NULL DEFAULT '',
                resume_text   TEXT    NOT NULL DEFAULT '',
                status        TEXT    NOT NULL DEFAULT 'active',
                question_idx  INTEGER NOT NULL DEFAULT 0,
                total_q       INTEGER NOT NULL DEFAULT 0,
                question_bank TEXT    NOT NULL DEFAULT '[]',
                created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS interview_qa (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id      TEXT    NOT NULL,
                q_index      INTEGER NOT NULL,
                question     TEXT    NOT NULL,
                q_type       TEXT    NOT NULL DEFAULT 'jd',
                user_answer  TEXT,
                score        INTEGER,
                feedback     TEXT,
                strengths    TEXT,
                gaps         TEXT,
                model_answer TEXT,
                asked_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE (chat_id, q_index)
            );
        """)

        # Safely add any missing columns for older databases
        _migrate(conn)
    try:
        from backend.interview_assistant import init_interview_db
        init_interview_db()
    except Exception as e:
        logger.warning("Failed to run interview db init: %s", e)
    logger.info("Database initialised at %s", DB_NAME)


def _migrate(conn):
    """Non-destructive schema migrations for existing databases."""
    # Check users table schema
    users_existing = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if users_existing and "username" not in users_existing:
        logger.info("Migrating legacy users table to new schema...")
        conn.execute("ALTER TABLE users RENAME TO users_old")
        
        # Rename dependent tables to update/clear foreign key references
        conn.execute("ALTER TABLE user_sessions RENAME TO user_sessions_old")
        conn.execute("ALTER TABLE user_chats RENAME TO user_chats_old")
        
        conn.execute("""
            CREATE TABLE users (
                user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username        TEXT UNIQUE NOT NULL,
                password_hash   TEXT NOT NULL,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        
        conn.execute("""
            CREATE TABLE user_sessions (
                session_token   TEXT PRIMARY KEY,
                user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                expires_at      TEXT NOT NULL
            )
        """)
        
        conn.execute("""
            CREATE TABLE user_chats (
                chat_id         TEXT PRIMARY KEY,
                user_id         INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        
        has_email = "email" in users_existing
        has_password = "password" in users_existing
        has_id = "id" in users_existing
        
        select_id = "id" if has_id else "NULL"
        select_username = "email" if has_email else "''"
        select_password = "password" if has_password else "''"
        select_created = "created_at" if "created_at" in users_existing else "(datetime('now'))"
        
        conn.execute(f"""
            INSERT INTO users (user_id, username, password_hash, created_at)
            SELECT {select_id}, {select_username}, {select_password}, {select_created} FROM users_old
        """)
        
        # Copy data for dependent tables if any existed
        conn.execute("""
            INSERT INTO user_sessions (session_token, user_id, created_at, expires_at)
            SELECT session_token, user_id, created_at, expires_at FROM user_sessions_old
        """)
        conn.execute("""
            INSERT INTO user_chats (chat_id, user_id)
            SELECT chat_id, user_id FROM user_chats_old
        """)
        
        conn.execute("DROP TABLE users_old")
        conn.execute("DROP TABLE user_sessions_old")
        conn.execute("DROP TABLE user_chats_old")
        logger.info("Legacy users and dependent tables migrated successfully.")

    existing = {row[1] for row in conn.execute("PRAGMA table_info(course_sessions)").fetchall()}
    migrations = {
        "day_plan":    "ALTER TABLE course_sessions ADD COLUMN day_plan TEXT NOT NULL DEFAULT '[]'",
        "created_at":  "ALTER TABLE course_sessions ADD COLUMN created_at TEXT NOT NULL DEFAULT (datetime('now'))",
        "updated_at":  "ALTER TABLE course_sessions ADD COLUMN updated_at TEXT NOT NULL DEFAULT (datetime('now'))",
    }
    for col, sql in migrations.items():
        if col not in existing:
            conn.execute(sql)

    prog_existing = {row[1] for row in conn.execute("PRAGMA table_info(progress)").fetchall()}
    prog_migrations = {
        "completion_date": "ALTER TABLE progress ADD COLUMN completion_date TEXT",
        "score":           "ALTER TABLE progress ADD COLUMN score INTEGER",
        "notes":           "ALTER TABLE progress ADD COLUMN notes TEXT",
    }
    for col, sql in prog_migrations.items():
        if col not in prog_existing:
            conn.execute(sql)



# ── Session state ────────────────────────────────────────────

def save_session_state(chat_id: str, state: dict):
    plan_json = json.dumps(state.get("day_plan", []))
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO course_sessions
                (chat_id, role, duration_days, hours_per_day, level, dsa_track,
                 current_day, started, awaiting_answers, last_quiz, day_plan, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(chat_id) DO UPDATE SET
                role             = excluded.role,
                duration_days    = excluded.duration_days,
                hours_per_day    = excluded.hours_per_day,
                level            = excluded.level,
                dsa_track        = excluded.dsa_track,
                current_day      = excluded.current_day,
                started          = excluded.started,
                awaiting_answers = excluded.awaiting_answers,
                last_quiz        = excluded.last_quiz,
                day_plan         = excluded.day_plan,
                updated_at       = datetime('now')
        """, (
            chat_id,
            state["role"],
            int(state["duration_days"]),
            str(state["hours_per_day"]),
            state["level"],
            "yes" if state.get("dsa_track") else "no",
            int(state["current_day"]),
            1 if state.get("started") else 0,
            1 if state.get("awaiting_answers") else 0,
            state.get("last_quiz", ""),
            plan_json,
        ))


def load_session_state(chat_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT role, duration_days, hours_per_day, level, dsa_track,
                      current_day, started, awaiting_answers, last_quiz, day_plan
               FROM course_sessions WHERE chat_id = ?""",
            (chat_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "role":             row["role"],
        "duration_days":    row["duration_days"],
        "hours_per_day":    row["hours_per_day"],
        "level":            row["level"],
        "dsa_track":        row["dsa_track"] == "yes",
        "current_day":      row["current_day"],
        "started":          row["started"] == 1,
        "awaiting_answers": row["awaiting_answers"] == 1,
        "last_quiz":        row["last_quiz"] or "",
        "day_plan":         _safe_json_list(row["day_plan"]),
    }


def delete_session(chat_id: str):
    with get_connection() as conn:
        conn.execute("DELETE FROM course_sessions WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM progress WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM notifications WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM user_chats WHERE chat_id = ?", (chat_id,))


# ── Progress tracking ────────────────────────────────────────

def log_day_completion(chat_id: str, day: int, status: str, date_str: str, score: int = None, notes: str = None):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO progress (chat_id, day, status, completion_date, score, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, day) DO UPDATE SET
                status          = excluded.status,
                completion_date = excluded.completion_date,
                score           = excluded.score,
                notes           = excluded.notes
        """, (chat_id, int(day), status, date_str, score, notes))


def get_session_progress_map(chat_id: str, total_days: int) -> dict:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT day, status FROM progress WHERE chat_id = ?", (chat_id,)
        ).fetchall()
    status_map = {day: "pending" for day in range(1, total_days + 1)}
    for row in rows:
        day = row["day"]
        if 1 <= day <= total_days:
            status_map[day] = row["status"]
    return status_map


def get_progress_stats(chat_id: str) -> dict:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM progress WHERE chat_id = ? GROUP BY status",
            (chat_id,)
        ).fetchall()
    stats = {"completed": 0, "failed": 0, "pending": 0}
    for row in rows:
        if row["status"] in stats:
            stats[row["status"]] = row["cnt"]
    return stats


def get_last_completed_date(chat_id: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT completion_date FROM progress
               WHERE chat_id = ? AND status = 'completed'
               ORDER BY day DESC LIMIT 1""",
            (chat_id,),
        ).fetchone()
    return row["completion_date"] if row else None


def get_streak(chat_id: str) -> int:
    """Return consecutive completed days ending at the most recent completed day."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT day FROM progress WHERE chat_id = ? AND status = 'completed' ORDER BY day DESC",
            (chat_id,)
        ).fetchall()
    if not rows:
        return 0
    days = [r["day"] for r in rows]
    streak = 1
    for i in range(1, len(days)):
        if days[i - 1] - days[i] == 1:
            streak += 1
        else:
            break
    return streak


# ── Session flags ────────────────────────────────────────────

def reset_awaiting_answers(chat_id: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE course_sessions SET awaiting_answers = 0, updated_at = datetime('now') WHERE chat_id = ?",
            (chat_id,)
        )


# ── Notifications ────────────────────────────────────────────

def push_notification(chat_id: str, notif_type: str, title: str, body: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO notifications (chat_id, type, title, body) VALUES (?, ?, ?, ?)",
            (chat_id, notif_type, title, body)
        )


def get_unread_notifications(chat_id: str) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT id, type, title, body, created_at
               FROM notifications WHERE chat_id = ? AND is_read = 0
               ORDER BY created_at DESC LIMIT 20""",
            (chat_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def mark_notifications_read(chat_id: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE chat_id = ?", (chat_id,)
        )


# ── Password & User Authentication Helpers ───────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hash_bytes = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return f"{salt}:{hash_bytes.hex()}"


def check_password(password: str, hashed: str) -> bool:
    try:
        salt, hash_hex = hashed.split(":")
        hash_bytes = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        return secrets.compare_digest(hash_bytes.hex(), hash_hex)
    except Exception:
        return False


def register_user(username: str, password_raw: str) -> int | None:
    try:
        hashed = hash_password(password_raw)
        with get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, hashed)
            )
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None


def verify_user(username: str, password_raw: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT user_id, username, password_hash FROM users WHERE username = ?",
            (username,)
        ).fetchone()
    if row and check_password(password_raw, row["password_hash"]):
        return {"user_id": row["user_id"], "username": row["username"]}
    return None


def create_user_session(user_id: int) -> str:
    token = secrets.token_hex(32)
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO user_sessions (session_token, user_id, expires_at)
               VALUES (?, ?, datetime('now', '+30 days'))""",
            (token, user_id)
        )
    return token


def invalidate_user_session(token: str):
    with get_connection() as conn:
        conn.execute("DELETE FROM user_sessions WHERE session_token = ?", (token,))


def check_or_register_chat(chat_id: str, user_id: int) -> bool:
    if not chat_id:
        return False
    with get_connection() as conn:
        row = conn.execute(
            "SELECT user_id FROM user_chats WHERE chat_id = ?",
            (chat_id,)
        ).fetchone()
        if row:
            return row["user_id"] == user_id
        else:
            try:
                conn.execute(
                    "INSERT INTO user_chats (chat_id, user_id) VALUES (?, ?)",
                    (chat_id, user_id)
                )
                return True
            except sqlite3.IntegrityError:
                return False