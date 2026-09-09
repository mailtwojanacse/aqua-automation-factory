"""Live-dashboard + durable audit-trail event emitter. Every event is
written to dashboard/events.db (SQLite) instead of a flat file, grouped by
a run_id so history can be browsed per-run later ("what did the factory do
last week"), not just as one long stream. Duplicated per agent folder,
same convention as llm_client.py, so each agent stays self-contained.

run_id comes from the AQUA_RUN_ID env var, set by whatever orchestrated
this run (orchestrator/run_pipeline.py, auto_trigger.py, or the dashboard
server) before spawning this agent's subprocess - or generated fresh here
if this agent is being run standalone with nothing wrapping it.
"""
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "dashboard" / "events.db"
RUN_ID = os.environ.get("AQUA_RUN_ID") or f"run-{int(time.time())}-{uuid.uuid4().hex[:6]}"


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")  # readers (dashboard) don't block writers (agents)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            run_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            kind TEXT NOT NULL,
            message TEXT NOT NULL,
            detail TEXT NOT NULL
        )
    """)
    return conn


def emit(agent, kind, message, detail=None, run_id=None):
    """kind: start | mechanical | ai_call | ai_dry_run | handoff | done | error.

    run_id overrides the module-level default - for a long-running process
    (auto_trigger.py) that handles several distinct triggered actions across
    its lifetime, each action gets its own run_id rather than being stuck
    with the one generated when the module was first imported."""
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO events (ts, run_id, agent, kind, message, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), run_id or RUN_ID, agent, kind, message, json.dumps(detail or {})),
        )
        conn.commit()
    finally:
        conn.close()
