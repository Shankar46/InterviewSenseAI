# backend/interview_assistant.py
# Mock interview engine — generates questions from JD/resume/company,
# evaluates answers, and produces a final report card.

import json
import logging
import re

from backend.db import get_connection, load_session_state, push_notification
from backend.generator import run_completion

logger = logging.getLogger(__name__)

TOTAL_QUESTIONS = 10          # questions per session
CAREER_RATIO    = 5           # 1 career question per CAREER_RATIO interview questions


# ── Question bank generation ──────────────────────────────────

def _generate_question_bank(
    role: str, company: str, jd_text: str, resume_text: str, career_topics: list, domain: str, round_type: str, weekly_career_day: int = 0
) -> list:
    """Generate a mixed question bank from JD/company/resume + career daily topics, tailored by domain/round."""

    if weekly_career_day > 0:
        jd_q_count = 10
        coding_q_count = 2
    else:
        career_q_count = max(1, TOTAL_QUESTIONS // CAREER_RATIO) if career_topics else 0
        jd_q_count     = TOTAL_QUESTIONS - career_q_count
        coding_q_count = 0

    jd_section     = (jd_text     or "No JD provided.")[:3000]
    resume_section  = (resume_text or "No resume provided.")[:2000]

    domain_label = "IT/Technical" if domain == "it" else "Non-IT"
    round_label = "Technical/Functional Round" if round_type == "tech" else "HR/Managerial Round"

    if weekly_career_day > 0:
        prompt = f"""You are a senior technical interviewer at {company} conducting a weekly mock interview evaluation for a {role} position.
Based on the candidate's learning curriculum for the week (curriculum day: {weekly_career_day}):
JOB DESCRIPTION/CURRICULUM TOPICS:
{jd_section}

CANDIDATE RESUME:
{resume_section}

Generate exactly {jd_q_count + coding_q_count} questions as a JSON array:
- {jd_q_count} standard interview questions related to the curriculum (types: "jd", "resume", "company")
- {coding_q_count} coding questions (type: "coding") containing coding tasks/puzzles suited for this role

Each object: {{"question": "<full question/coding task>", "type": "<company|jd|resume|coding>", "hint": "<what a great answer/solution covers>"}}

Return ONLY a valid JSON array. No markdown fences, no commentary."""
    else:
        prompt = f"""You are a senior interviewer at {company}.
You are conducting a structured mock interview for a {role} position.
This is a {round_label} in the {domain_label} domain.

JOB DESCRIPTION:
{jd_section}

CANDIDATE RESUME:
{resume_section}

Generate exactly {jd_q_count} interview questions as a JSON array.
Depending on the round type ({round_label}) and domain ({domain_label}), focus the questions on:
"""
        if round_type == "hr":
            prompt += """- HR / Managerial fit: behavioral, leadership, situational scenarios, collaboration, conflicts, problem-solving, alignment with company values. Do NOT ask deeply technical coding or mathematical questions. (type: "company" or "resume")"""
        elif domain == "it":
            prompt += """- IT / Technical skills: programming, software engineering concepts, system design, machine learning, data structures, algorithms, or database queries. (type: "jd" or "resume")"""
        else:
            prompt += """- Non-IT / Functional skills: business analysis, case study questions, logic puzzles, market sizing, process mapping, data analysis, domain-specific concepts. (type: "jd" or "resume")"""

        prompt += """

Each object: {"question": "<full question>", "type": "<company|jd|resume>", "hint": "<what a great answer covers — 1 sentence>"}

Return ONLY a valid JSON array. No markdown fences, no commentary."""

    try:
        raw = run_completion(
            [{"role": "user", "content": prompt}],
            max_tokens=3000,
            temperature=0.4,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("` \n")
        questions = json.loads(raw)
        if not isinstance(questions, list):
            raise ValueError("Expected list")
    except Exception as exc:
        logger.exception("Question bank generation failed (%s) — using fallback", exc)
        questions = _fallback_questions(role, company, jd_q_count)
        if weekly_career_day > 0:
            questions.append({"question": "Write a function to reverse a linked list.", "type": "coding", "hint": "Node swaps, edge cases"})
            questions.append({"question": "Implement a function to check if a binary tree is balanced.", "type": "coding", "hint": "Height recursion, complexity"})

    # Normalise and cap
    result = []
    for q in questions[:(jd_q_count + coding_q_count)]:
        result.append({
            "question": str(q.get("question", "Tell me about yourself.")),
            "type":     q.get("type", "jd"),
            "hint":     str(q.get("hint", "")),
        })

    # Inject career questions at interval positions (every CAREER_RATIO slots)
    if weekly_career_day == 0 and career_topics and career_q_count > 0:
        career_qs = _build_career_questions(career_topics, career_q_count)
        for i, cq in enumerate(career_qs):
            pos = CAREER_RATIO * (i + 1)
            if pos <= len(result):
                result.insert(pos, cq)
            else:
                result.append(cq)

    limit = (jd_q_count + coding_q_count) if weekly_career_day > 0 else TOTAL_QUESTIONS
    return result[:limit]


def _build_career_questions(career_topics: list, count: int) -> list:
    qs = []
    for topic in career_topics[:count]:
        qs.append({
            "question": (
                f"You've been studying **{topic}** recently. "
                f"Explain the core concept and describe a real-world use case "
                f"where you would apply it."
            ),
            "type": "career",
            "hint": f"Tests understanding of {topic} from daily study",
        })
    return qs


def _fallback_questions(role: str, company: str, count: int) -> list:
    bank = [
        {"question": f"Why do you want to work at {company} as a {role}?",
         "type": "company", "hint": "Company research, cultural fit, motivation"},
        {"question": "Walk me through a challenging project you owned. What was your impact?",
         "type": "resume", "hint": "STAR format, technical depth, measurable outcome"},
        {"question": "Explain the most complex system you've designed or significantly contributed to.",
         "type": "jd", "hint": "Architecture, scalability, trade-offs"},
        {"question": "How do you handle disagreements with your team or manager?",
         "type": "company", "hint": "Communication, empathy, constructive resolution"},
        {"question": "Describe a time you had to learn a new technology quickly. How did you approach it?",
         "type": "resume", "hint": "Learning strategy, adaptability, outcome"},
        {"question": "What's your approach to code reviews — both giving and receiving feedback?",
         "type": "jd", "hint": "Collaboration, quality mindset, specific practices"},
        {"question": f"Where do you see the role of {role} evolving in the next 3 years?",
         "type": "company", "hint": "Industry awareness, growth mindset"},
        {"question": "Tell me about a production incident you handled. What was your process?",
         "type": "jd", "hint": "Debugging, communication, post-mortem, prevention"},
        {"question": "How do you prioritise when you have multiple competing deadlines?",
         "type": "company", "hint": "Time management, communication, trade-off thinking"},
        {"question": "What do you consider your biggest professional achievement so far?",
         "type": "resume", "hint": "Impact, ownership, quantified results"},
    ]
    return bank[:count]


# ── DB helpers ────────────────────────────────────────────────

def init_interview_db():
    """Create interview tables if not already present."""
    with get_connection() as conn:
        conn.executescript("""
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
        # Add columns if they do not exist
        for col, col_type in [("domain", "TEXT NOT NULL DEFAULT 'it'"),
                              ("round_type", "TEXT NOT NULL DEFAULT 'tech'"),
                              ("report_feedback", "TEXT NOT NULL DEFAULT ''"),
                              ("weekly_career_day", "INTEGER NOT NULL DEFAULT 0")]:
            try:
                conn.execute(f"ALTER TABLE interview_sessions ADD COLUMN {col} {col_type}")
            except Exception:
                pass


def _save_interview_session(chat_id: str, data: dict):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO interview_sessions
                (chat_id, role, company, jd_text, resume_text, status,
                 question_idx, total_q, question_bank, domain, round_type, report_feedback, weekly_career_day)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                role            = excluded.role,
                company         = excluded.company,
                jd_text         = excluded.jd_text,
                resume_text     = excluded.resume_text,
                status          = excluded.status,
                question_idx    = excluded.question_idx,
                total_q         = excluded.total_q,
                question_bank   = excluded.question_bank,
                domain          = excluded.domain,
                round_type      = excluded.round_type,
                report_feedback = excluded.report_feedback,
                weekly_career_day = excluded.weekly_career_day
        """, (
            chat_id,
            data["role"], data["company"],
            data["jd_text"], data["resume_text"],
            data["status"],
            int(data["question_idx"]),
            int(data["total_q"]),
            json.dumps(data["question_bank"]),
            data.get("domain", "it"),
            data.get("round_type", "tech"),
            data.get("report_feedback", ""),
            int(data.get("weekly_career_day", 0)),
        ))


def _load_interview_session(chat_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM interview_sessions WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    if not row:
        return None
    return {
        "role":            row["role"],
        "company":         row["company"],
        "jd_text":         row["jd_text"],
        "resume_text":     row["resume_text"],
        "status":          row["status"],
        "question_idx":    row["question_idx"],
        "total_q":         row["total_q"],
        "question_bank":   json.loads(row["question_bank"] or "[]"),
        "domain":          row["domain"] if "domain" in row.keys() else "it",
        "round_type":      row["round_type"] if "round_type" in row.keys() else "tech",
        "report_feedback": row["report_feedback"] if "report_feedback" in row.keys() else "",
        "weekly_career_day": row["weekly_career_day"] if "weekly_career_day" in row.keys() else 0,
    }


def _save_qa(chat_id: str, q_idx: int, question: str, q_type: str,
             answer: str, score: int, feedback: str,
             strengths: str, gaps: str, model_answer: str):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM interview_qa WHERE chat_id = ? AND q_index = ?",
            (chat_id, q_idx)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE interview_qa SET user_answer=?, score=?, feedback=?,
                   strengths=?, gaps=?, model_answer=? WHERE id=?""",
                (answer, score, feedback, strengths, gaps, model_answer, existing["id"])
            )
        else:
            conn.execute(
                """INSERT INTO interview_qa
                   (chat_id, q_index, question, q_type, user_answer, score, feedback, strengths, gaps, model_answer)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (chat_id, q_idx, question, q_type, answer,
                 score, feedback, strengths, gaps, model_answer)
            )


def _load_all_qa(chat_id: str) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM interview_qa WHERE chat_id = ? ORDER BY q_index", (chat_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def reset_interview_session(chat_id: str):
    with get_connection() as conn:
        conn.execute("DELETE FROM interview_sessions WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM interview_qa WHERE chat_id = ?", (chat_id,))


# ── Main API functions ────────────────────────────────────────

def start_interview(
    chat_id: str, role: str, company: str, jd_text: str, resume_text: str,
    domain: str = "it", round_type: str = "tech", weekly_career_day: int = 0
) -> dict:
    """Initialise a new interview session and return the first question."""

    # Pull career daily topics if a career session exists for this chat
    career_topics = []
    career_state  = load_session_state(chat_id)
    if career_state and career_state.get("day_plan") and career_state.get("started"):
        current_day = career_state.get("current_day", 1)
        plan        = career_state["day_plan"]
        start_idx   = max(0, current_day - 2)
        end_idx     = min(len(plan), current_day + 2)
        career_topics = [plan[i]["topic"] for i in range(start_idx, end_idx) if i < len(plan)]

    question_bank = _generate_question_bank(role, company, jd_text, resume_text, career_topics, domain, round_type, weekly_career_day)

    session = {
        "role":         role,
        "company":      company,
        "jd_text":      jd_text,
        "resume_text":  resume_text,
        "status":       "active",
        "question_idx": 0,
        "total_q":      len(question_bank),
        "question_bank": question_bank,
        "domain":       domain,
        "round_type":   round_type,
        "report_feedback": "",
        "weekly_career_day": weekly_career_day,
    }
    _save_interview_session(chat_id, session)
    push_notification(
        chat_id, "info", "Mock Interview Started! 🎯",
        f"{role} @ {company} — {len(question_bank)} questions ready."
    )

    first_q = question_bank[0]
    career_note = (
        f"\n\n> 📚 *{len([q for q in question_bank if q['type'] == 'career'])} question(s) "
        f"are drawn from your Career Accelerator daily topics.*"
        if career_topics else ""
    )

    return {
        "status":   "question",
        "question": first_q["question"],
        "q_type":   first_q["type"],
        "q_num":    1,
        "total":    len(question_bank),
        "message":  (
            f"## 🎯 Mock Interview: {role} @ {company}\n\n"
            f"I've prepared **{len(question_bank)} tailored questions** based on the JD and your resume. "
            f"Answer each as you would in a real interview — be specific and use examples.{career_note}\n\n---"
        ),
    }


def submit_answer(chat_id: str, answer: str) -> dict:
    """Evaluate the current answer; return feedback + next question or final report."""

    session = _load_interview_session(chat_id)
    if not session:
        return {"status": "error", "message": "No active interview session. Please start a new interview."}

    if session["status"] == "completed":
        return {"status": "completed", "message": "Interview already completed."}

    q_idx         = session["question_idx"]
    question_bank = session["question_bank"]

    if q_idx >= len(question_bank):
        return _build_report(chat_id, session)

    current_q = question_bank[q_idx]

    # Evaluate
    feedback_data = _evaluate_answer(
        role=session["role"],
        company=session["company"],
        question=current_q["question"],
        q_type=current_q["type"],
        answer=answer,
        hint=current_q.get("hint", ""),
    )

    # Persist Q&A
    _save_qa(
        chat_id, q_idx,
        current_q["question"], current_q["type"],
        answer,
        feedback_data["score"],
        feedback_data["raw"],
        feedback_data["strengths"],
        feedback_data["gaps"],
        feedback_data["model_answer"],
    )

    # Advance pointer
    next_idx = q_idx + 1
    session["question_idx"] = next_idx

    if next_idx >= len(question_bank):
        session["status"] = "completed"
        _save_interview_session(chat_id, session)
        report = _build_report(chat_id, session)
        return {
            "status":   "feedback_and_complete",
            "feedback": feedback_data,
            "q_num":    q_idx + 1,
            "total":    session["total_q"],
            "report":   report,
        }

    _save_interview_session(chat_id, session)
    next_q = question_bank[next_idx]

    return {
        "status":        "feedback_and_next",
        "feedback":      feedback_data,
        "q_num":         q_idx + 1,
        "total":         session["total_q"],
        "next_question": next_q["question"],
        "next_q_type":   next_q["type"],
        "next_q_num":    next_idx + 1,
    }


def get_report(chat_id: str) -> dict:
    session = _load_interview_session(chat_id)
    if not session:
        return {"status": "error", "message": "No interview session found."}
    return _build_report(chat_id, session)


# ── Answer evaluator ─────────────────────────────────────────

def _evaluate_answer(
    role: str, company: str,
    question: str, q_type: str,
    answer: str, hint: str,
) -> dict:
    type_ctx = {
        "company": f"This is a company/culture fit question for {company}.",
        "jd":      f"This tests technical requirements for the {role} role.",
        "resume":  "This dives into the candidate's past experience from their resume.",
        "career":  "This checks active knowledge on a topic the candidate has been studying.",
    }.get(q_type, "")

    prompt = f"""You are an expert technical interviewer at {company} evaluating a {role} candidate.

{type_ctx}

QUESTION: {question}
HINT (what a strong answer covers): {hint}

CANDIDATE'S ANSWER:
{answer or "(no answer provided)"}

Evaluate strictly. Respond in this EXACT format:
SCORE: X/10
STRENGTHS: <1-2 sentences on what was good>
GAPS: <1-2 sentences on what was missing or weak>
MODEL_ANSWER: <3-5 sentences showing an ideal answer>
OVERALL: <one-sentence verdict>"""

    try:
        raw = run_completion(
            [{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.15,
        )
    except Exception:
        logger.exception("Answer evaluation failed")
        return {
            "score": 0, "raw": "Evaluation unavailable.",
            "strengths": "", "gaps": "", "model_answer": "", "overall": "",
        }

    def _extract(label: str) -> str:
        m = re.search(rf"{label}:\s*(.+?)(?=\n[A-Z_]+:|$)", raw, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""

    score = 5
    sm = re.search(r"SCORE:\s*(\d+)\s*/\s*10", raw, re.IGNORECASE)
    if sm:
        score = min(10, max(0, int(sm.group(1))))

    return {
        "score":        score,
        "raw":          raw,
        "strengths":    _extract("STRENGTHS"),
        "gaps":         _extract("GAPS"),
        "model_answer": _extract("MODEL_ANSWER"),
        "overall":      _extract("OVERALL"),
    }


# ── Report builder ────────────────────────────────────────────

def _generate_overall_feedback(role: str, company: str, qa_rows: list) -> str:
    """Generate overall qualitative feedback and key improvement areas."""
    qa_summary = ""
    for r in qa_rows:
        qa_summary += f"Question: {r['question']}\nCandidate Answer: {r['user_answer'] or '(no answer)'}\nScore: {r['score']}/10\nStrengths: {r['strengths'] or ''}\nGaps: {r['gaps'] or ''}\n\n"

    prompt = f"""You are a senior hiring manager and technical director at {company} evaluating a candidate for the {role} role.
Based on the following transcript of their mock interview performance:

{qa_summary}

Provide a constructive overall performance review and specific areas where the candidate needs to focus/improve.
Respond in this EXACT format (copy the labels exactly):
OVERALL_FEEDBACK: <3-4 sentences summarizing their performance, strengths, and communication style>
IMPROVEMENT_AREAS:
- <First specific topic/skill they should update or study, with a brief sentence of guidance>
- <Second topic/skill they should update or study, with guidance>
- <Third topic/skill (optional), with guidance>"""

    try:
        raw = run_completion(
            [{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.3,
        )
        return raw.strip()
    except Exception:
        logger.exception("Failed to generate overall feedback report")
        return "OVERALL_FEEDBACK: Evaluation completed.\nIMPROVEMENT_AREAS:\n- Keep practicing core concepts.\n- Build on real-world projects."


def _build_report(chat_id: str, session: dict) -> dict:
    qa_rows = _load_all_qa(chat_id)
    if not qa_rows:
        return {"status": "report_empty", "message": "No answers recorded yet."}

    scores    = [r["score"] for r in qa_rows if r["score"] is not None]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    weak   = [r for r in qa_rows if (r["score"] or 0) < 6]
    strong = [r for r in qa_rows if (r["score"] or 0) >= 8]

    breakdown = [
        {
            "q_num":        r["q_index"] + 1,
            "question":     r["question"],
            "q_type":       r["q_type"],
            "score":        r["score"],
            "strengths":    r["strengths"] or "",
            "gaps":         r["gaps"] or "",
            "model_answer": r["model_answer"] or "",
        }
        for r in qa_rows
    ]

    type_scores: dict = {}
    for r in qa_rows:
        type_scores.setdefault(r["q_type"], []).append(r["score"] or 0)
    type_avgs = {t: round(sum(v) / len(v), 1) for t, v in type_scores.items()}

    # Generate overall qualitative report feedback if not already stored
    # Generate overall qualitative report feedback if not already stored
    feedback_str = session.get("report_feedback") or ""
    if not feedback_str and session.get("status") == "completed":
        feedback_str = _generate_overall_feedback(session["role"], session["company"], qa_rows)
        # Save it
        with get_connection() as conn:
            conn.execute(
                "UPDATE interview_sessions SET report_feedback = ? WHERE chat_id = ?",
                (feedback_str, chat_id)
            )
        session["report_feedback"] = feedback_str

    # Process weekly mock evaluation progression if complete!
    weekly_day = session.get("weekly_career_day", 0)
    if weekly_day > 0 and session.get("status") == "completed":
        w = (weekly_day + 6) // 7
        day_A = (w - 1) * 7 + 6
        day_B = w * 7
        
        from backend.db import log_day_completion, save_session_state
        from backend.career_assistant import _today
        
        # Log completion of both days (Day 6 & 7, or Day 13 & 14, etc.)
        log_day_completion(chat_id, day_A, "completed", _today(), score=10)
        log_day_completion(chat_id, day_B, "completed", _today(), score=10)
        
        career_state = load_session_state(chat_id)
        if career_state:
            if career_state.get("current_day") in (day_A, day_B):
                if day_B < career_state.get("duration_days", 30):
                    career_state["current_day"] = day_B + 1
                else:
                    career_state["current_day"] = career_state.get("duration_days", 30)
                career_state["started"] = True
                career_state["awaiting_answers"] = False
                save_session_state(chat_id, career_state)
                
        push_notification(
            chat_id, "success", f"Week {w} Milestone Achieved! 🏆",
            f"Mandatory mock interview complete. Days {day_A} & {day_B} marked as completed."
        )

    feedback_text = ""
    improvements = []
    if feedback_str:
        of_match = re.search(r"OVERALL_FEEDBACK:\s*(.+?)(?=\nIMPROVEMENT_AREAS:|$)", feedback_str, re.IGNORECASE | re.DOTALL)
        if of_match:
            feedback_text = of_match.group(1).strip()
        ia_match = re.search(r"IMPROVEMENT_AREAS:\s*(.+)$", feedback_str, re.IGNORECASE | re.DOTALL)
        if ia_match:
            lines = ia_match.group(1).strip().split("\n")
            for line in lines:
                line = line.strip().lstrip("-*• ").strip()
                if line:
                    improvements.append(line)

    push_notification(
        chat_id, "success", "Interview Complete! 🏆",
        f"Average score: {avg_score}/10 across {len(qa_rows)} questions."
    )

    return {
        "status":          "report",
        "avg_score":       avg_score,
        "total_questions": len(qa_rows),
        "strong_count":    len(strong),
        "weak_count":      len(weak),
        "type_averages":   type_avgs,
        "breakdown":       breakdown,
        "role":            session["role"],
        "company":         session["company"],
        "overall_feedback": feedback_text,
        "improvement_areas": improvements,
    }
