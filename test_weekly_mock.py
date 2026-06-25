#!/usr/bin/env python3
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.db import get_connection, save_session_state, load_session_state, get_unread_notifications, init_db
from backend.interview_assistant import start_interview, submit_answer, get_report

def main():
    init_db()
    chat_id = "weekly-test-chat-999"
    
    # 1. Clean up
    print("Cleaning up existing sessions...")
    with get_connection() as conn:
        conn.execute("DELETE FROM progress WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM course_sessions WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM interview_sessions WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM interview_qa WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM notifications WHERE chat_id = ?", (chat_id,))

    # 2. Setup mock Career Accelerator session for Day 6
    print("Setting up Career Accelerator session at Day 6...")
    day_plan = [{"day": d, "topic": f"Topic for Day {d}", "focus": "Focus"} for d in range(1, 31)]
    career_state = {
        "role": "Python Developer",
        "duration_days": 30,
        "hours_per_day": 2,
        "level": "beginner",
        "dsa_track": True,
        "started": True,
        "current_day": 6,
        "awaiting_answers": False,
        "day_plan": day_plan
    }
    save_session_state(chat_id, career_state)

    # 3. Start Weekly Mock Interview
    print("Starting weekly mock interview (weekly_career_day=6)...")
    res = start_interview(
        chat_id=chat_id,
        role="Python Developer",
        company="Weekly Evaluation (Career Accelerator)",
        jd_text="Mandatory Weekly Assessment to evaluate candidate learning progress.",
        resume_text="",
        domain="it",
        round_type="tech",
        weekly_career_day=6
    )
    
    total = res["total"]
    print(f"✓ Interview started. Total questions: {total}")
    assert total == 12, f"Expected 12 questions (10+2), got {total}"
    
    # Check question bank structure in DB
    with get_connection() as conn:
        row = conn.execute("SELECT question_bank FROM interview_sessions WHERE chat_id = ?", (chat_id,)).fetchone()
        qbank = json.loads(row["question_bank"])
        print(f"Question types in bank: {[q['type'] for q in qbank]}")
        coding_qs = [q for q in qbank if q["type"] == "coding"]
        assert len(coding_qs) == 2, f"Expected exactly 2 coding questions, got {len(coding_qs)}"
        print("✓ Question bank contains exactly 2 coding questions.")

    # 4. Answer all questions
    for i in range(1, total + 1):
        print(f"Answering question {i}/{total}...")
        ans_res = submit_answer(chat_id=chat_id, answer=f"This is my answer for question {i}")
        
        status = ans_res["status"]
        if i < total:
            assert status == "feedback_and_next", f"Expected feedback_and_next, got {status}"
            assert ans_res["next_q_num"] == i + 1, f"Expected next question number {i+1}, got {ans_res['next_q_num']}"
        else:
            assert status == "feedback_and_complete", f"Expected feedback_and_complete, got {status}"
            print("✓ Completed last question successfully!")

    # 5. Verify Career Accelerator Day 6 and Day 7 are completed, and day advanced to 8
    print("Verifying Career Accelerator state update...")
    new_career_state = load_session_state(chat_id)
    print(f"New Career current_day: {new_career_state['current_day']}")
    assert new_career_state["current_day"] == 8, f"Expected current_day to be advanced to 8, got {new_career_state['current_day']}"
    
    with get_connection() as conn:
        rows = conn.execute("SELECT day, status FROM progress WHERE chat_id = ? ORDER BY day", (chat_id,)).fetchall()
        days_status = {r["day"]: r["status"] for r in rows}
        print(f"Completed days status: {days_status}")
        assert days_status.get(6) == "completed", f"Day 6 status expected completed, got {days_status.get(6)}"
        assert days_status.get(7) == "completed", f"Day 7 status expected completed, got {days_status.get(7)}"
        print("✓ Day 6 and Day 7 successfully logged as completed in the database.")

    # 6. Verify notification was sent
    notifs = get_unread_notifications(chat_id)
    print("Unread notifications:")
    for n in notifs:
        print(f"  - [{n['type']}] {n['title']}: {n['body']}")
    
    assert any("Milestone Achieved" in n["title"] for n in notifs), "Expected a milestone achievement notification"
    print("✓ Notification sent successfully.")

    print("\n" + "="*40)
    print("✓ ALL WEEKLY MOCK INTERVIEW TESTS PASSED!")
    print("="*40)

if __name__ == "__main__":
    main()
