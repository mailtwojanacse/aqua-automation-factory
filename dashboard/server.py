#!/usr/bin/env python3
"""Local live-dashboard server for the Aqua Automation Factory pipeline.
Stdlib only - nothing extra to install.

Serves the dashboard page, reads the shared dashboard/events.db (SQLite)
that every agent's src/events.py writes to, and run-control endpoints that
launch the orchestrator as a background process so the "Run" buttons in
the browser can drive it directly.

Events are durable - unlike the old flat-file version, "Reset" only clears
the live view; the full history stays queryable via /history.

Run:
    python3 server.py
    # then open http://localhost:8787
"""
import json
import mimetypes
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import slack_notifier

ROOT = Path(__file__).resolve().parent
INDEX_PATH = ROOT / "index.html"
DB_PATH = ROOT / "events.db"
RUN_LOG_PATH = ROOT / "run.log"
ORCHESTRATOR_DIR = ROOT.parent / "orchestrator"
JOBS_PATH = ORCHESTRATOR_DIR / "jobs.json"
AGENT5_DIR = ROOT.parent / "agent5_execution_selfheal"
ALLURE_REPORT_DIR = AGENT5_DIR / "allure-report"
TRACEABILITY_DIR = ROOT.parent / "traceability"
PORT = 8787
DASHBOARD_URL = os.environ.get("AQUA_DASHBOARD_URL", f"http://localhost:{PORT}")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
SLACK_POLL_INTERVAL_SECONDS = 3

VALID_LLM_BACKENDS = {"anthropic_api", "openai_api", "azure_openai", "claude_cli"}


def _backend_readiness_error(mode, llm_backend):
    """None if a real run with this backend can proceed, else a
    human-readable reason it can't - shared between /run (the full
    pipeline) and /run_agent5 (Agent 5 alone), since both fail the same
    way if the backend isn't actually configured."""
    if mode != "real":
        return None
    if llm_backend == "anthropic_api" and not os.environ.get("ANTHROPIC_API_KEY"):
        return ("No ANTHROPIC_API_KEY is set in this server's environment - a real run "
                "would fail as soon as the AI is called. Switch the AI backend, use "
                "dry-run, or set the key and restart the dashboard server.")
    if llm_backend == "openai_api" and not os.environ.get("OPENAI_API_KEY"):
        return ("No OPENAI_API_KEY is set in this server's environment - a real run would "
                "fail as soon as the AI is called. Switch the AI backend, use dry-run, or "
                "set the key and restart the dashboard server.")
    if llm_backend == "azure_openai":
        missing = [v for v in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT")
                   if not os.environ.get(v)]
        if missing:
            return (f"Missing {', '.join(missing)} in this server's environment for "
                    "azure_openai - a real run would fail as soon as the AI is called. "
                    "Switch the AI backend, use dry-run, or set the missing variable(s) "
                    "and restart the dashboard server.")
    if llm_backend == "claude_cli" and shutil.which("claude") is None:
        return "llm_backend is 'claude_cli' but the `claude` CLI isn't on PATH for this server process."
    return None


def _load_jobs():
    """The same registry run_pipeline.py reads - single source of truth for
    which demo jobs exist and what each one's v1/v2 target pages are, so
    the dashboard never hardcodes a job-specific page list."""
    return json.loads(JOBS_PATH.read_text(encoding="utf-8"))

run_lock = threading.Lock()
RUN_STATE = {"proc": None, "mode": None, "llm_backend": None, "run_id": None, "job": None}


def _connect_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
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


def _query_events_since(since_id):
    """Standalone (non-Handler) version of the /events query - reused by
    both the HTTP handler and the Slack notifier's background poll thread,
    which has no request context to hang a method off of."""
    if not DB_PATH.exists():
        return [], since_id
    conn = _connect_db()
    try:
        rows = conn.execute(
            "SELECT id, ts, run_id, agent, kind, message, detail FROM events "
            "WHERE id > ? ORDER BY id", (since_id,),
        ).fetchall()
    finally:
        conn.close()
    events = [
        {"id": r[0], "ts": r[1], "run_id": r[2], "agent": r[3], "kind": r[4],
         "message": r[5], "detail": json.loads(r[6])}
        for r in rows
    ]
    next_id = events[-1]["id"] if events else since_id
    return events, next_id


def _run_slack_notifier(stop_event):
    """Background loop: poll for new events, notify Slack for the ones that
    qualify. Starts its cursor at the current latest event id so turning
    this on doesn't replay the entire history as a wall of Slack pings."""
    _, since_id = _query_events_since(0)
    print(f"Slack alerts enabled - polling every {SLACK_POLL_INTERVAL_SECONDS}s "
          f"(starting after event #{since_id})")
    while not stop_event.is_set():
        try:
            since_id, _ = slack_notifier.poll_once(
                _query_events_since, since_id, SLACK_WEBHOOK_URL, DASHBOARD_URL,
            )
        except Exception as exc:
            print(f"Slack notifier tick failed (will retry): {exc}")
        stop_event.wait(SLACK_POLL_INTERVAL_SECONDS)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # keep the terminal quiet - the dashboard itself is the log

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # ---- GET ----

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/":
            body = INDEX_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/events":
            since = int(parse_qs(parsed.query).get("since", ["0"])[0])
            events, next_id = self._read_new_events(since)
            self._send_json({"events": events, "next_offset": next_id})
            return

        if parsed.path == "/history":
            self._send_json({"runs": self._list_runs()})
            return

        if parsed.path.startswith("/history/"):
            run_id = parsed.path[len("/history/"):]
            events, _ = self._read_new_events(0, run_id=run_id)
            self._send_json({"events": events})
            return

        if parsed.path == "/health":
            self._send_json(self._health_check())
            return

        if parsed.path == "/jobs":
            self._send_json({"jobs": _load_jobs()})
            return

        if parsed.path == "/run_status":
            with run_lock:
                proc = RUN_STATE["proc"]
                running = proc is not None and proc.poll() is None
                mode = RUN_STATE["mode"] if running else None
                llm_backend = RUN_STATE["llm_backend"] if running else None
                run_id = RUN_STATE["run_id"] if running else None
                job = RUN_STATE["job"] if running else None
            self._send_json({"running": running, "mode": mode, "llm_backend": llm_backend, "run_id": run_id, "job": job})
            return

        if parsed.path == "/allure" or parsed.path.startswith("/allure/"):
            self._serve_static_dir(parsed.path[len("/allure"):] or "/", ALLURE_REPORT_DIR,
                                    b"No Allure report yet - run Agent 5 at least once.")
            return

        if parsed.path == "/traceability" or parsed.path.startswith("/traceability/"):
            self._serve_static_dir(parsed.path[len("/traceability"):] or "/", TRACEABILITY_DIR,
                                    b"No traceability report yet - run Agent 5 at least once.")
            return

        self.send_response(404)
        self.end_headers()

    def _serve_static_dir(self, subpath, base_dir, not_found_message):
        """Static file server for a generated report directory (the real
        Allure report, or the requirement traceability report). Both load
        their data via fetch/XHR, so they must be served over HTTP, not
        opened as file://."""
        if subpath == "/":
            subpath = "/index.html"
        # Resolve and confirm the requested file stays inside base_dir -
        # subpath comes from the URL, so guard against '..' escaping it.
        target = (base_dir / subpath.lstrip("/")).resolve()
        try:
            target.relative_to(base_dir.resolve())
        except ValueError:
            self.send_response(403)
            self.end_headers()
            return
        if not target.is_file():
            self.send_response(404)
            self.send_header("Content-Length", str(len(not_found_message)))
            self.end_headers()
            self.wfile.write(not_found_message)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_new_events(self, since_id, run_id=None):
        if run_id is None:
            return _query_events_since(since_id)
        if not DB_PATH.exists():
            return [], since_id
        conn = _connect_db()
        try:
            rows = conn.execute(
                "SELECT id, ts, run_id, agent, kind, message, detail FROM events "
                "WHERE run_id = ? ORDER BY id", (run_id,),
            ).fetchall()
        finally:
            conn.close()
        events = [
            {"id": r[0], "ts": r[1], "run_id": r[2], "agent": r[3], "kind": r[4],
             "message": r[5], "detail": json.loads(r[6])}
            for r in rows
        ]
        next_id = events[-1]["id"] if events else since_id
        return events, next_id

    def _list_runs(self):
        if not DB_PATH.exists():
            return []
        conn = _connect_db()
        try:
            rows = conn.execute("""
                SELECT run_id, MIN(ts) AS started, COUNT(*) AS n,
                       SUM(CASE WHEN kind = 'error' THEN 1 ELSE 0 END) AS n_errors,
                       GROUP_CONCAT(DISTINCT agent) AS agents
                FROM events
                GROUP BY run_id
                ORDER BY started DESC
                LIMIT 200
            """).fetchall()
        finally:
            conn.close()
        return [
            {"run_id": r[0], "started": r[1], "event_count": r[2],
             "had_error": bool(r[3]), "agents": r[4]}
            for r in rows
        ]

    def _health_check(self):
        """Cheap liveness/readiness check for an already-running dashboard -
        no subprocess calls, just "is the thing this server actually needs
        working." Used by scripts/preflight_check.py and safe to poll from
        an external monitor (e.g. `curl http://vm:8787/health`)."""
        checks = {"events_db_queryable": False}
        try:
            conn = _connect_db()
            conn.execute("SELECT 1")
            conn.close()
            checks["events_db_queryable"] = True
        except Exception as exc:
            checks["events_db_error"] = str(exc)

        checks["allure_report_present"] = (ALLURE_REPORT_DIR / "index.html").is_file()
        checks["traceability_report_present"] = (TRACEABILITY_DIR / "index.html").is_file()
        checks["slack_alerts_enabled"] = bool(SLACK_WEBHOOK_URL)

        with run_lock:
            proc = RUN_STATE["proc"]
            checks["pipeline_running"] = proc is not None and proc.poll() is None

        return {"ok": checks["events_db_queryable"], "checks": checks}

    # ---- POST ----

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/reset":
            # Durable history is the whole point now - Reset no longer
            # deletes anything, it just tells the caller where "now" is so
            # the live view can jump its cursor forward and show a clean
            # feed. Everything before this point stays in /history.
            conn = _connect_db()
            try:
                row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()
            finally:
                conn.close()
            self._send_json({"ok": True, "since": row[0]})
        elif path == "/run":
            self._handle_run()
        elif path == "/run_agent5":
            self._handle_run_agent5()
        elif path == "/approve":
            self._handle_gate_response("y\n")
        elif path == "/reject":
            self._handle_gate_response("n\n")
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_run(self):
        jobs = _load_jobs()

        body = self._read_json_body()
        mode = body.get("mode")
        job_name = body.get("job", "adobe_acrobat")
        llm_backend = body.get("llm_backend", "anthropic_api")

        if mode not in ("dry-run", "real"):
            self._send_json({"ok": False, "error": "mode must be 'dry-run' or 'real'"}, status=400)
            return
        if job_name not in jobs:
            self._send_json({"ok": False, "error": f"unknown job: {job_name}"}, status=400)
            return
        job = jobs[job_name]
        valid_target_pages = set(job["target_pages"].values())
        target_page = body.get("target_page", job["target_pages"]["v1"])
        if target_page not in valid_target_pages:
            self._send_json({
                "ok": False,
                "error": f"unknown target_page for job '{job_name}': {target_page} "
                         f"(expected one of {sorted(valid_target_pages)})",
            }, status=400)
            return
        if llm_backend not in VALID_LLM_BACKENDS:
            self._send_json({"ok": False, "error": f"unknown llm_backend: {llm_backend}"}, status=400)
            return

        with run_lock:
            proc = RUN_STATE["proc"]
            if proc is not None and proc.poll() is None:
                self._send_json({"ok": False, "error": "A run is already in progress."}, status=409)
                return

            error = _backend_readiness_error(mode, llm_backend)
            if error:
                self._send_json({"ok": False, "error": error}, status=400)
                return

            cmd = [sys.executable, "run_pipeline.py", "--job", job_name, "--target-page", target_page]
            if mode == "dry-run":
                cmd += ["--dry-run", "--pr-number", "1"]

            run_id = f"run-{int(time.time())}-{uuid.uuid4().hex[:6]}"
            env = os.environ.copy()
            env["LLM_BACKEND"] = llm_backend
            env["AQUA_RUN_ID"] = run_id

            log_file = open(RUN_LOG_PATH, "w", encoding="utf-8")
            proc = subprocess.Popen(
                cmd, cwd=ORCHESTRATOR_DIR, stdin=subprocess.PIPE,
                stdout=log_file, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env,
            )
            RUN_STATE["proc"] = proc
            RUN_STATE["mode"] = mode
            RUN_STATE["llm_backend"] = llm_backend
            RUN_STATE["run_id"] = run_id
            RUN_STATE["job"] = job_name

        self._send_json({"ok": True, "run_id": run_id})

    def _handle_run_agent5(self):
        """Same request shape as /run, but launches Agent 5 alone
        (run_agent5.py) instead of the full 5-agent pipeline. Used by the
        dashboard's Break Locators / Self-Heal demo buttons, which need a
        fast, direct path to Agent 5 without going through Agents 1-4 or
        the human-approval gate in between - those still exist and still
        matter for a real requirement change, they're just not what a
        "prove self-heal works" demo click is asking for."""
        jobs = _load_jobs()

        body = self._read_json_body()
        mode = body.get("mode")
        job_name = body.get("job", "adobe_acrobat")
        llm_backend = body.get("llm_backend", "anthropic_api")

        if mode not in ("dry-run", "real"):
            self._send_json({"ok": False, "error": "mode must be 'dry-run' or 'real'"}, status=400)
            return
        if job_name not in jobs:
            self._send_json({"ok": False, "error": f"unknown job: {job_name}"}, status=400)
            return
        job = jobs[job_name]
        valid_target_pages = set(job["target_pages"].values())
        target_page = body.get("target_page", job["target_pages"]["v2"])
        if target_page not in valid_target_pages:
            self._send_json({
                "ok": False,
                "error": f"unknown target_page for job '{job_name}': {target_page} "
                         f"(expected one of {sorted(valid_target_pages)})",
            }, status=400)
            return
        if llm_backend not in VALID_LLM_BACKENDS:
            self._send_json({"ok": False, "error": f"unknown llm_backend: {llm_backend}"}, status=400)
            return

        with run_lock:
            proc = RUN_STATE["proc"]
            if proc is not None and proc.poll() is None:
                self._send_json({"ok": False, "error": "A run is already in progress."}, status=409)
                return

            error = _backend_readiness_error(mode, llm_backend)
            if error:
                self._send_json({"ok": False, "error": error}, status=400)
                return

            cmd = [sys.executable, "run_agent5.py", "--script", job["script"], "--target-page", target_page]
            if mode == "dry-run":
                cmd.append("--dry-run")

            run_id = f"run-{int(time.time())}-{uuid.uuid4().hex[:6]}"
            env = os.environ.copy()
            env["LLM_BACKEND"] = llm_backend
            env["AQUA_RUN_ID"] = run_id

            log_file = open(RUN_LOG_PATH, "w", encoding="utf-8")
            proc = subprocess.Popen(
                cmd, cwd=AGENT5_DIR, stdin=subprocess.PIPE,
                stdout=log_file, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env,
            )
            RUN_STATE["proc"] = proc
            RUN_STATE["mode"] = mode
            RUN_STATE["llm_backend"] = llm_backend
            RUN_STATE["run_id"] = run_id
            RUN_STATE["job"] = job_name

        self._send_json({"ok": True, "run_id": run_id})

    def _handle_gate_response(self, line):
        with run_lock:
            proc = RUN_STATE["proc"]
            if proc is None or proc.poll() is not None:
                self._send_json({"ok": False, "error": "No run is currently waiting for approval."}, status=400)
                return
            try:
                proc.stdin.write(line)
                proc.stdin.flush()
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=500)
                return
        self._send_json({"ok": True})


def main():
    server = ThreadingHTTPServer(("localhost", PORT), Handler)
    print(f"Aqua Automation Factory dashboard: http://localhost:{PORT}")
    print("Use the Run buttons in the browser, or run any agent/the orchestrator in another terminal.")

    stop_notifier = threading.Event()
    if SLACK_WEBHOOK_URL:
        threading.Thread(target=_run_slack_notifier, args=(stop_notifier,), daemon=True).start()
    else:
        print("Slack alerts disabled - set SLACK_WEBHOOK_URL to enable (see dashboard/README.md).")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_notifier.set()


if __name__ == "__main__":
    main()
