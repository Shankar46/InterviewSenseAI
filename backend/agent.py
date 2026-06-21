# backend/agent.py
# Thin alias kept for backwards compatibility.

from backend.career_assistant import generate_career_plan as run_agent

# Assign the agent to a variable name Vercel expects
handler = run_agent

# Expose both so Vercel can find 'handler'
__all__ = ["run_agent", "handler"]