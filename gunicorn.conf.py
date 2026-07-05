# gunicorn.conf.py
# Run with:  gunicorn -c gunicorn.conf.py backend.main:app
#
# Why these settings:
# - LLM calls and HF inference requests are I/O-bound (waiting on network),
#   not CPU-bound. Threads handle this far more efficiently than spinning up
#   more processes, and let the in-memory PDF cache / rate limiter stay
#   shared and consistent within a process.
# - 1 worker process + many threads avoids the multi-process cache-splitting
#   problem noted in main.py. If you later need multi-core CPU parallelism
#   (e.g. heavy local PDF/OCR processing), bump workers and move _pdf_cache
#   and rate_limit state to Redis first — otherwise requests will randomly
#   land on a worker that doesn't have a user's cached state.

import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('PORT', '5000')}"

workers = int(os.getenv("GUNICORN_WORKERS", "1"))
threads = int(os.getenv("GUNICORN_THREADS", str(min(16, multiprocessing.cpu_count() * 4))))
worker_class = "gthread"

timeout = 300          # must exceed your longest LLM generation (career plans can run minutes)
graceful_timeout = 30
keepalive = 5

max_requests = 1000        # recycle workers periodically to avoid slow memory creep
max_requests_jitter = 100

accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()

preload_app = False  # False so init_db()/thread pools run per-worker, not before fork