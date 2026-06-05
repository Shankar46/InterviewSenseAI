import os
import json
import logging
import sqlite3
from contextlib import contextmanager

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
        """)

        # Safely add any missing columns for older databases
        _migrate(conn)
    logger.info("Database initialised at %s", DB_NAME)


def _migrate(conn):
    """Non-destructive schema migrations for existing databases."""
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