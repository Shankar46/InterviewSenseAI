# backend/agent.py
#
# SECURITY FIX: this file used to expose POST /api/agent as a completely
# unauthenticated, unrate-limited entry point straight into
# generate_career_plan() — bypassing every login_required / rate_limit /
# chat-ownership check added to backend/main.py. Anyone who found this URL
# got free, unlimited LLM generations on your bill, with no session
# tracking and no abuse protection.
#
# vercel.json was routing "/api/agent" -> this file as a SEPARATE FastAPI
# app from the Flask app in main.py, which is also an architecture
# mismatch (config.js documents the backend as Flask; two frameworks were
# being deployed as two different serverless functions for overlapping
# concerns).
#
# Fix: route /api/agent through the same Flask app and decorators as every
# other endpoint, instead of shipping a second, unguarded framework.
# Update vercel.json to drop the separate agent.py build/route (see below).
#
# If you specifically need this for an external integration (e.g. a
# third-party agent platform that expects a bare POST /api/agent contract),
# keep this file but add the same auth + rate_limit decorators used in
# main.py before calling generate_career_plan, and never call it directly
# from generate_career_plan with raw user input again.

from backend.main import app  # re-use the hardened Flask app; do not define a second app here

__all__ = ["app"]