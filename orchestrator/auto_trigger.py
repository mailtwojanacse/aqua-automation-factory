#!/usr/bin/env python3
"""Watches for new work and triggers the relevant agents automatically -
no manual CLI command or dashboard click needed. Three triggers, one loop:

1. A new/changed Baramundi job dropped into inbox/jobs/<job_name>/
   -> runs Agent 1 then Agent 2.
2. A new/changed requirement dropped into inbox/requirements/*.md
   -> runs Agent 3 (opens a PR), then Agent 4 (reviews it). Merging stays
   a human decision - this never merges anything.
3. Every --regression-interval seconds, runs Agent 5 against every test
   script in automation_target/tests/ - this is also what re-validates
   anything a human merged from trigger #2; there's no separate "watch for
   merge" logic, the next regression cycle just picks it up.

Every triggered agent is invoked as its own CLI (a subprocess), same as
orchestrator/run_pipeline.py already does, and each agent already emits
its own events regardless of who invoked it - so auto-triggered runs show
up live on the dashboard automatically, no dashboard changes needed.

Examples:
    python auto_trigger.py --once --dry-run     # single safe pass, no AI/git side effects
    python auto_trigger.py --once                # single real pass (needs an LLM backend + gh auth)
    python auto_trigger.py                        # loop forever, polling + regression on a timer
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import events

AGENT = "Orchestrator"
ROOT = Path(__file__).resolve().parent.parent
AGENT1_DIR = ROOT / "agent1_baramundi_doc"
AGENT2_DIR = ROOT / "agent2_requirement_to_test"
AGENT3_DIR = ROOT / "agent3_script_adaptation"
AGENT4_DIR = ROOT / "agent4_review"
AGENT5_DIR = ROOT / "agent5_execution_selfheal"
REPO_DIR = ROOT / "automation_target"

INBOX_DIR = Path(__file__).resolve().parent / "inbox"
JOBS_INBOX = INBOX_DIR / "jobs"
REQUIREMENTS_INBOX = INBOX_DIR / "requirements"
STATE_PATH = Path(__file__).resolve().parent / ".auto_trigger_state.json"

DEFAULT_SCRIPT = "tests/test_install_verification.py"


def log(message):
    print(f"[auto_trigger] {message}", flush=True)


def new_run_id():
    """A fresh run_id per triggered action - auto_trigger.py is one
    long-running process, so unlike a fresh CLI invocation it can't rely on
    events.py's module-level default (computed once at import) to separate
    one triggered action's history from the next."""
    return f"run-{int(time.time())}-{uuid.uuid4().hex[:6]}"


def run_cli(agent_dir, script_name, args):
    cmd = [sys.executable, script_name, *args]
    log(f"$ (cd {agent_dir.name} && {' '.join(cmd)})")
    result = subprocess.run(cmd, cwd=agent_dir, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"{script_name} failed (exit {result.returncode})")
    return result.stdout


def extract_field(stdout, field_name):
    match = re.search(rf"^\s*{re.escape(field_name)}:\s*(.+)$", stdout, re.MULTILINE)
    return match.group(1).strip() if match else None


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"processed_jobs": {}, "processed_requirements": {}, "last_regression_run": 0}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def find_job_files(job_dir):
    bds = next(iter(job_dir.glob("*.bds")), None)
    config = next((f for f in job_dir.glob("*") if "config" in f.name.lower() and f.suffix in (".xml", ".json")), None)
    job_config = next((f for f in job_dir.glob("*") if "job" in f.name.lower() and f.suffix == ".json"), None)
    if not (bds and config and job_config):
        raise ValueError(f"{job_dir.name}: expected a .bds file, a *config* file, and a *job*.json file")
    return bds, config, job_config


def process_jobs(state, dry_run):
    if not JOBS_INBOX.exists():
        return
    for job_dir in sorted(p for p in JOBS_INBOX.iterdir() if p.is_dir()):
        try:
            bds, config, job_config = find_job_files(job_dir)
        except ValueError as exc:
            log(f"{job_dir.name}: skipped - {exc}")
            continue

        # Signature from only the 3 input files - NOT job_dir's own output/
        # subfolder, whose mtime bumps forward every time we write into it
        # (which would make every job look "changed" on every single pass).
        signature = max(bds.stat().st_mtime, config.stat().st_mtime, job_config.stat().st_mtime)
        if state["processed_jobs"].get(job_dir.name) == signature:
            continue  # unchanged since last time we processed it

        log(f"New/changed job detected: {job_dir.name}")
        run_id = new_run_id()
        os.environ["AQUA_RUN_ID"] = run_id
        events.emit(AGENT, "start", f"Job inbox trigger: {job_dir.name}", {"job": job_dir.name}, run_id=run_id)

        output_dir = job_dir / "output"
        dry = ["--dry-run"] if dry_run else []
        try:
            run_cli(AGENT1_DIR, "run_agent1.py", [
                "--bds", str(bds), "--xml-config", str(config), "--job-config", str(job_config),
                "--output-dir", str(output_dir), "--job-name", job_dir.name, "--split", *dry,
            ])
            if not dry_run:
                run_cli(AGENT2_DIR, "run_agent2.py", [
                    "--requirements", str(output_dir / "requirements.md"),
                    "--output-dir", str(output_dir), *dry,
                ])
            state["processed_jobs"][job_dir.name] = signature
            save_state(state)
            log(f"  done: {job_dir.name}")
            events.emit(AGENT, "done", f"Job inbox trigger finished: {job_dir.name}", run_id=run_id)
        except Exception as exc:
            log(f"  FAILED: {job_dir.name} - {exc}")
            events.emit(AGENT, "error", f"Job inbox trigger failed: {job_dir.name} - {exc}", run_id=run_id)


def process_requirements(state, dry_run):
    if not REQUIREMENTS_INBOX.exists():
        return
    for req_path in sorted(REQUIREMENTS_INBOX.glob("*.md")):
        mtime = req_path.stat().st_mtime
        if state["processed_requirements"].get(req_path.name) == mtime:
            continue

        log(f"New/changed requirement detected: {req_path.name}")
        run_id = new_run_id()
        os.environ["AQUA_RUN_ID"] = run_id
        events.emit(AGENT, "start", f"Requirement inbox trigger: {req_path.name}",
                    {"requirement": req_path.name}, run_id=run_id)

        dry = ["--dry-run"] if dry_run else []
        try:
            stdout3 = run_cli(AGENT3_DIR, "run_agent3.py", [
                "--requirement", str(req_path), "--script", DEFAULT_SCRIPT, *dry,
            ])
            pr_url = extract_field(stdout3, "pr_url")
            if pr_url:
                pr_number = int(re.search(r"/pull/(\d+)", pr_url).group(1))
                run_cli(AGENT4_DIR, "run_agent4.py", ["--pr-number", str(pr_number), *dry])
                log(f"  opened + reviewed {pr_url} - merging is still a human decision")
            else:
                status = extract_field(stdout3, "status") or ("dry-run" if dry_run else "unknown")
                log(f"  no PR to review (status: {status})")
            state["processed_requirements"][req_path.name] = mtime
            save_state(state)
            log(f"  done: {req_path.name}")
            events.emit(AGENT, "done", f"Requirement inbox trigger finished: {req_path.name}", run_id=run_id)
        except Exception as exc:
            log(f"  FAILED: {req_path.name} - {exc}")
            events.emit(AGENT, "error", f"Requirement inbox trigger failed: {req_path.name} - {exc}", run_id=run_id)


def process_regression(state, dry_run, regression_interval):
    now = time.time()
    if now - state.get("last_regression_run", 0) < regression_interval:
        return
    test_dir = REPO_DIR / "tests"
    scripts = sorted(test_dir.glob("test_*.py")) if test_dir.exists() else []
    if not scripts:
        state["last_regression_run"] = now
        save_state(state)
        return

    log(f"Regression cycle: running {len(scripts)} test script(s) against main")
    run_id = new_run_id()
    os.environ["AQUA_RUN_ID"] = run_id
    events.emit(AGENT, "start", f"Regression cycle: {len(scripts)} script(s)",
                {"scripts": [s.name for s in scripts]}, run_id=run_id)

    dry = ["--dry-run"] if dry_run else []
    for script in scripts:
        relpath = f"tests/{script.name}"
        args = ["--script", relpath]
        # run_agent5.py's --target-page defaults to the Adobe sample page
        # regardless of which script is running - derive the right page for
        # this script from its name (test_<name>_verification.py ->
        # <name>_confirmation_v1.html, matching this project's naming
        # convention) instead of silently checking the wrong page.
        name_match = re.match(r"test_(.+)_verification\.py$", script.name)
        if name_match:
            candidate_page = f"{name_match.group(1)}_confirmation_v1.html"
            if (REPO_DIR / "sample_app" / candidate_page).exists():
                args += ["--target-page", candidate_page]
        try:
            run_cli(AGENT5_DIR, "run_agent5.py", [*args, *dry])
        except Exception as exc:
            log(f"  FAILED: {relpath} - {exc}")
    state["last_regression_run"] = now
    save_state(state)
    log("Regression cycle done")
    events.emit(AGENT, "done", "Regression cycle done", run_id=run_id)


def main():
    parser = argparse.ArgumentParser(description="Watch the inbox and a regression timer, trigger agents automatically.")
    parser.add_argument("--poll-interval", type=int, default=10, help="Seconds between inbox checks (default: 10)")
    parser.add_argument("--regression-interval", type=int, default=300,
                        help="Seconds between Agent 5 regression cycles (default: 300; use a real cadence like "
                             "86400 for once-daily in production)")
    parser.add_argument("--dry-run", action="store_true", help="Forward --dry-run to every triggered agent")
    parser.add_argument("--once", action="store_true", help="Run a single pass instead of looping forever")
    args = parser.parse_args()

    JOBS_INBOX.mkdir(parents=True, exist_ok=True)
    REQUIREMENTS_INBOX.mkdir(parents=True, exist_ok=True)
    state = load_state()

    log(f"Watching {JOBS_INBOX} and {REQUIREMENTS_INBOX} (poll every {args.poll_interval}s); "
        f"regression every {args.regression_interval}s" + (" [dry-run]" if args.dry_run else ""))

    while True:
        process_jobs(state, args.dry_run)
        process_requirements(state, args.dry_run)
        process_regression(state, args.dry_run, args.regression_interval)
        if args.once:
            break
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
