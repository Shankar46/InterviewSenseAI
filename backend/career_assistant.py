# backend/career_assistant.py

import json
import logging
import os
import re
from datetime import date

from dotenv import load_dotenv

from backend.db import (
    get_last_completed_date,
    get_session_progress_map,
    get_streak,
    load_session_state,
    log_day_completion,
    push_notification,
    save_session_state,
)
from backend.generator import evaluate_quiz_answer, run_completion

load_dotenv()
logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────
ACTIVE_MODEL = "Qwen/Qwen2.5-72B-Instruct"

POSITIVE_HINTS  = frozenset({"yes", "ready", "start", "lets start", "let's start", "go ahead", "begin", "ok", "okay", "sure"})
DONE_HINTS      = frozenset({"i learned", "i have learned", "i studied", "i completed", "i finished", "done", "completed", "finished"})
REFRESH_COMMANDS = frozenset({"refresh_fetch", "__refresh__"})
SKIP_HINTS      = frozenset({"skip", "skip day", "next day", "skip this"})
STATUS_HINTS    = frozenset({"status", "progress", "how am i doing", "my progress", "stats"})


# ── Plan generation ──────────────────────────────────────────

def _fallback_plan(role: str, duration_days: int) -> list:
    topics = [
        "Python Fundamentals & Data Structures",
        "OOP & Design Patterns",
        "Algorithms & Complexity Analysis",
        "Database Design & SQL Queries",
        "REST API Design & Flask",
        "System Design Basics",
        "Testing & TDD",
        "Git & CI/CD Workflows",
        "Cloud Deployment Concepts",
        "Behavioural & HR Interview Questions",
    ]
    plan = []
    for i in range(duration_days):
        topic = topics[i % len(topics)]
        plan.append({
            "day":   i + 1,
            "topic": f"{role} — {topic}",
            "focus": f"Deep dive into {topic.lower()}. Practice implementation, review tradeoffs, and prepare a 2-minute verbal explanation.",
        })
    return plan


def _normalize_plan(raw: list, role: str, duration_days: int) -> list:
    if not isinstance(raw, list) or not raw:
        return _fallback_plan(role, duration_days)
    result = []
    for i in range(duration_days):
        item = raw[i] if i < len(raw) and isinstance(raw[i], dict) else {}
        result.append({
            "day":   i + 1,
            "topic": str(item.get("topic") or f"{role} Core Module {i + 1}")[:140],
            "focus": str(item.get("focus") or "Implement, debug, and explain tradeoffs clearly.")[:500],
        })
    return result


def _generate_plan(role: str, level: str, duration_days: int, dsa_track: bool) -> list:
    dsa_note = "Include dedicated DSA problem-solving days (arrays, trees, graphs, DP) woven throughout." if dsa_track else ""

    prompt = f"""You are a senior technical interviewer and curriculum designer.
Create a complete, day-by-day interview preparation plan.

Role: {role}
Experience Level: {level}
Duration: {duration_days} days
{dsa_note}

Return ONLY a valid JSON array with exactly {duration_days} objects.
Each object: {{"day": <int>, "topic": "<specific topic name>", "focus": "<concrete study tasks and engineering focus>"}}

Requirements:
- Topics must be concrete and role-specific (name actual frameworks, tools, patterns).
- Each topic must be unique — no duplicates.
- Focus must be actionable (e.g. "implement a LRU cache, analyse time complexity, explain to interviewer").
- Distribute fundamentals, system design, DSA, and behavioural rounds proportionally.

Return raw JSON only. No markdown fences, no commentary."""

    try:
        raw = run_completion(
            [{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.35,
        )
        # Strip markdown fences if model ignores instructions
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("` \n")
        return _normalize_plan(json.loads(raw), role, duration_days)
    except Exception as e:
        logger.exception("LLM plan generation failed; using fallback plan. Error: %s", e)
        return _fallback_plan(role, duration_days)


# ── State helpers ────────────────────────────────────────────

def _state_from_config(config: dict) -> dict:
    role = (config.get("role") or "Python Developer").strip()[:120]
    match = re.search(r"(\d+)", str(config.get("duration", "30 days")))
    duration = max(1, min(int(match.group(1)) if match else 30, 120))
    return {
        "role":             role,
        "duration_days":    duration,
        "hours_per_day":    str(config.get("hours_per_day", "2"))[:10],
        "level":            str(config.get("level", "beginner")).strip().lower()[:40],
        "dsa_track":        str(config.get("dsa_track", "yes")).lower() == "yes",
        "current_day":      1,
        "started":          False,
        "awaiting_answers": False,
        "last_quiz":        "",
        "day_plan":         [],
    }


def _tracker(chat_id: str, total_days: int) -> list:
    progress = get_session_progress_map(chat_id, total_days)
    return [{"day": d, "status": progress[d]} for d in range(1, total_days + 1)]


def _today() -> str:
    return date.today().strftime("%Y-%m-%d")


# ── Formatters ───────────────────────────────────────────────

def _fmt_roadmap(state: dict) -> str:
    preview = state["day_plan"][:7]
    lines = [
        f"## 🗺️ Career Roadmap: {state['role']}",
        f"**Level:** {state['level'].title()} · **Duration:** {state['duration_days']} days · **Daily commitment:** {state['hours_per_day']} hrs",
        "",
        "### First 7 Days Preview",
    ]
    for d in preview:
        lines.append(f"- **Day {d['day']}** — {d['topic']}\n  _{d['focus']}_")
    lines += [
        "",
        f"*Full {state['duration_days']}-day curriculum is loaded and ready.*",
    ]
    return "\n".join(lines)


def _fmt_day_start(state: dict) -> str:
    plan = state["day_plan"]
    idx = max(0, min(state["current_day"] - 1, len(plan) - 1))
    entry = plan[idx]
    streak = get_streak(state.get("_chat_id", ""))
    streak_line = f"\n\n🔥 **Current streak: {streak} day{'s' if streak != 1 else ''}**" if streak > 0 else ""
    return (
        f"## Day {entry['day']} — {entry['topic']}\n\n"
        f"**Focus:** {entry['focus']}{streak_line}\n\n"
        f"---\n"
        f"Study this topic, build something, and when ready — type **done** or describe what you learned "
        f"to trigger your Day {entry['day']} assessment quiz."
    )


def _fmt_status(state: dict, chat_id: str) -> str:
    stats = get_session_progress_map(chat_id, state["duration_days"])
    done  = sum(1 for s in stats.values() if s == "completed")
    failed = sum(1 for s in stats.values() if s == "failed")
    pend  = sum(1 for s in stats.values() if s == "pending")
    streak = get_streak(chat_id)
    pct = round((done / state["duration_days"]) * 100)
    return (
        f"## 📊 Progress Report — {state['role']}\n\n"
        f"| Metric | Value |\n|---|---|\n"
        f"| Current Day | Day {state['current_day']} of {state['duration_days']} |\n"
        f"| Completed | {done} days ({pct}%) |\n"
        f"| Failed | {failed} days |\n"
        f"| Remaining | {pend} days |\n"
        f"| Streak | 🔥 {streak} days |\n"
    )


# ── Main entry point ─────────────────────────────────────────

def generate_career_plan(
    user_input: str,
    history: list = None,
    career_config: dict = None,
    chat_id: str = "default",
) -> dict:
    career_config = career_config or {}
    cleaned = (user_input or "").strip().lower()
    state = load_session_state(chat_id)

    # ── Silent refresh (frontend progress fetch) ──────────────
    if cleaned in REFRESH_COMMANDS:
        if not state:
            # New session - return empty tracker for frontend to wait
            return {"text": "", "tracker": _default_tracker(career_config)}
        if not state["day_plan"]:
            state["day_plan"] = _generate_plan(state["role"], state["level"], state["duration_days"], state["dsa_track"])
            save_session_state(chat_id, state)
        
        # Always return the roadmap text for refresh
        text = _fmt_roadmap(state)
        if state["started"]:
            state["_chat_id"] = chat_id
            text += f"\n\n---\n\n{_fmt_day_start(state)}"
        else:
            text += f"\n\nType **yes** to begin Day 1 of your roadmap."
        return {"text": text, "tracker": _tracker(chat_id, state["duration_days"])}

    # ── Status request ────────────────────────────────────────
    if any(hint in cleaned for hint in STATUS_HINTS) and state:
        return {"text": _fmt_status(state, chat_id), "tracker": _tracker(chat_id, state["duration_days"])}

    # ── New session ───────────────────────────────────────────
    if not state:
        state = _state_from_config(career_config)
        # If the user typed a role directly (not a command), use it
        if user_input and not any(hint in cleaned for hint in POSITIVE_HINTS):
            candidate = user_input.strip()
            if 3 <= len(candidate) <= 120:
                state["role"] = candidate
        state["day_plan"] = _generate_plan(state["role"], state["level"], state["duration_days"], state["dsa_track"])
        save_session_state(chat_id, state)
        push_notification(chat_id, "info", "Roadmap created!", f"Your {state['duration_days']}-day {state['role']} plan is ready.")
        return {
            "text": f"{_fmt_roadmap(state)}\n\nType **yes** to lock in this curriculum and start Day 1.",
            "tracker": _tracker(chat_id, state["duration_days"]),
        }

    # Ensure plan exists (recovery path)
    if not state["day_plan"]:
        state["day_plan"] = _generate_plan(state["role"], state["level"], state["duration_days"], state["dsa_track"])
        save_session_state(chat_id, state)

    # ── Awaiting quiz answers ─────────────────────────────────
    if state["awaiting_answers"]:
        return _handle_quiz_answer(user_input, cleaned, state, chat_id)

    # ── Skip day ──────────────────────────────────────────────
    if any(hint in cleaned for hint in SKIP_HINTS):
        return _handle_skip(state, chat_id)

    # ── Start / advance day ───────────────────────────────────
    if any(hint in cleaned for hint in POSITIVE_HINTS):
        return _handle_start(state, chat_id)

    # ── Completion / study report ─────────────────────────────
    if any(hint in cleaned for hint in DONE_HINTS) or len(cleaned) > 20:
        return _handle_completion(user_input, state, chat_id)

    # ── Fallback: show current day status ────────────────────
    plan = state["day_plan"]
    idx = state["current_day"] - 1
    entry = plan[idx] if idx < len(plan) else {"topic": "Advanced Topics"}
    return {
        "text": (
            f"### Day {state['current_day']} — {entry['topic']}\n\n"
            f"Type **yes** to begin today's session, **done** after studying to take the quiz, "
            f"or **status** to see your overall progress."
        ),
        "tracker": _tracker(chat_id, state["duration_days"]),
    }


# ── Sub-handlers ─────────────────────────────────────────────

def _handle_quiz_answer(user_input: str, cleaned: str, state: dict, chat_id: str) -> dict:
    plan = state["day_plan"]
    idx = state["current_day"] - 1
    topic = plan[idx]["topic"] if idx < len(plan) else "Core Engineering Concepts"

    evaluation, passed, score = evaluate_quiz_answer(topic, user_input)

    status = "completed" if passed else "failed"
    log_day_completion(chat_id, state["current_day"], status, _today(), score=score)

    completed_day = state["current_day"]

    if passed:
        if state["current_day"] < state["duration_days"]:
            state["current_day"] += 1
        streak = get_streak(chat_id)
        push_notification(chat_id, "success", f"Day {completed_day} complete! 🎉", f"Score: {score}/10 · Streak: {streak} days")
    else:
        push_notification(chat_id, "warning", f"Day {completed_day} — review needed", f"Score: {score}/10. Revisit the topic before moving on.")

    state["awaiting_answers"] = False
    save_session_state(chat_id, state)

    result_label = "✅ PASSED" if passed else "❌ FAILED — review recommended"
    return {
        "text": (
            f"## Day {completed_day} Assessment — {result_label}\n\n"
            f"{evaluation}\n\n"
            f"{'Type **yes** to start Day ' + str(state['current_day']) + '.' if passed else 'Type **yes** when you are ready to retry or continue.'}"
        ),
        "tracker": _tracker(chat_id, state["duration_days"]),
    }


def _handle_start(state: dict, chat_id: str) -> dict:
    last_date = get_last_completed_date(chat_id)

    # Consolidation lock: one milestone per calendar day
    if last_date == _today() and state["started"]:
        return {
            "text": (
                f"### ⏸️ Daily limit reached\n\n"
                f"You have already completed a session today. "
                f"Come back tomorrow to tackle Day {state['current_day']}. "
                f"Use the time to practice and consolidate what you learned."
            ),
            "tracker": _tracker(chat_id, state["duration_days"]),
        }

    state["started"] = True
    state["_chat_id"] = chat_id
    save_session_state(chat_id, state)
    return {"text": _fmt_day_start(state), "tracker": _tracker(chat_id, state["duration_days"])}


def _handle_completion(user_input: str, state: dict, chat_id: str) -> dict:
    plan = state["day_plan"]
    idx = state["current_day"] - 1
    entry = plan[idx] if idx < len(plan) else {"day": state["current_day"], "topic": "Advanced Engineering Concepts"}

    quiz = (
        f"Answer both questions in a single message for your Day {entry['day']} evaluation:\n\n"
        f"**Q1.** Explain the core concept of **{entry['topic']}** — including how it works, "
        f"its key components, and one real-world use case.\n\n"
        f"**Q2.** Describe a significant limitation or failure mode of {entry['topic']} "
        f"and how you would address it in a production system."
    )

    state["awaiting_answers"] = True
    state["last_quiz"] = quiz
    save_session_state(chat_id, state)

    return {
        "text": f"## 📝 Day {entry['day']} Quiz — {entry['topic']}\n\n{quiz}",
        "tracker": _tracker(chat_id, state["duration_days"]),
    }


def _handle_skip(state: dict, chat_id: str) -> dict:
    skipped_day = state["current_day"]
    log_day_completion(chat_id, skipped_day, "failed", _today(), score=0, notes="Skipped by user")

    if state["current_day"] < state["duration_days"]:
        state["current_day"] += 1
        save_session_state(chat_id, state)
        push_notification(chat_id, "warning", f"Day {skipped_day} skipped", "Try to revisit skipped topics later.")
        return {
            "text": (
                f"Day {skipped_day} marked as skipped. Moving to **Day {state['current_day']}**.\n\n"
                f"Type **yes** to begin Day {state['current_day']}."
            ),
            "tracker": _tracker(chat_id, state["duration_days"]),
        }
    return {
        "text": "You have reached the end of your roadmap. All days are either completed or skipped.",
        "tracker": _tracker(chat_id, state["duration_days"]),
    }


def _default_tracker(career_config: dict) -> list:
    match = re.search(r"(\d+)", str(career_config.get("duration", "30 days")))
    total = max(1, min(int(match.group(1)) if match else 30, 120))
    return [{"day": i + 1, "status": "pending"} for i in range(total)]


# ── Backwards-compat alias ────────────────────────────────────
build_default_tracker_from_config = _default_tracker
buildDefaultTrackerFromConfig = _default_tracker