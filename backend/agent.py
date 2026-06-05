# backend/agent.py
# Thin alias kept for backwards compatibility.

from backend.career_assistant import generate_career_plan as run_agent

__all__ = ["run_agent"]