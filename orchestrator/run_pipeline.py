#!/usr/bin/env python3
"""Runs the full Aqua Automation Factory demo pipeline end to end:

Agent 1 -> Agent 2 -> Agent 3 -> Agent 4 -> (human approval gate) -> merge -> Agent 5

Each agent is invoked as its own CLI (a subprocess), matching how they'd be
wired into a real CI/CD pipeline later - this script is glue, not a shared
library, so each agent folder stays independently runnable.

Example:
    python run_pipeline.py --dry-run                       # full mechanical pass, no AI/git side effects
    python run_pipeline.py                                  # real run: needs ANTHROPIC_API_KEY + gh auth
    python run_pipeline.py --target-page v2                # exercise Agent 5's self-heal at the end
    python run_pipeline.py --job 7zip --dry-run             # run the same pipeline against a different demo job

Which job to run is a registry, not hardcoded - see jobs.json for the full
list and what each one wires up (Agent 1's .bds/config inputs, the script
Agent 3 adapts and Agent 5 runs, and its v1/v2 target pages).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import events

# Export the run_id events.py picked (existing AQUA_RUN_ID from whatever
# launched us, or a freshly generated one) so every agent subprocess we
# spawn below inherits the same one and shows up grouped as one run in the
# audit trail.
os.environ["AQUA_RUN_ID"] = events.RUN_ID

ROOT = Path(__file__).resolve().parent.parent
AGENT = "Orchestrator"
AGENT1_DIR = ROOT / "agent1_baramundi_doc"
AGENT2_DIR = ROOT / "agent2_requirement_to_test"
AGENT3_DIR = ROOT / "agent3_script_adaptation"
AGENT4_DIR = ROOT / "agent4_review"
AGENT5_DIR = ROOT / "agent5_execution_selfheal"
REPO_DIR = ROOT / "automation_target"
JOBS_PATH = Path(__file__).resolve().parent / "jobs.json"


def load_jobs():
    return json.loads(JOBS_PATH.read_text(encoding="utf-8"))


def banner(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def run_cli(agent_dir, script_name, args):
    cmd = [sys.executable, script_name, *args]
    print(f"$ (cd {agent_dir.name} && {' '.join(cmd)})")
    result = subprocess.run(cmd, cwd=agent_dir, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"{script_name} failed (exit {result.returncode})")
    return result.stdout


def extract_field(stdout, field_name):
    match = re.search(rf"^\s*{re.escape(field_name)}:\s*(.+)$", stdout, re.MULTILINE)
    return match.group(1).strip() if match else None


def main():
    jobs = load_jobs()

    parser = argparse.ArgumentParser(description="Run Agents 1-5 end to end.")
    parser.add_argument("--job", choices=sorted(jobs), default="adobe_acrobat",
                        help="Which demo job to run the full pipeline against (see orchestrator/jobs.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run every agent in --dry-run mode: no AI calls, no git/GitHub side effects")
    parser.add_argument("--pr-number", type=int, default=None,
                        help="PR number for Agent 4 to review when Agent 3 ran in --dry-run (no new PR to point at)")
    parser.add_argument("--target-page", default=None,
                        help="Which sample_app page Agent 5 should run against - a raw filename, or 'v1'/'v2' "
                             "shorthand resolved against --job (default: that job's v1 page)")
    parser.add_argument("--skip-human-gate", action="store_true",
                        help="Skip the manual approve-and-merge pause between Agent 4 and Agent 5 (auto-merge)")
    args = parser.parse_args()
    dry = ["--dry-run"] if args.dry_run else []

    job = jobs[args.job]
    target_page = job["target_pages"].get(args.target_page, args.target_page) if args.target_page \
        else job["target_pages"]["v1"]

    events.emit(AGENT, "start",
                f"Starting full pipeline run ({'dry-run' if args.dry_run else 'real'} mode) - job: {job['label']}",
                {"job": args.job, "target_page": target_page})

    banner(f"Agent 1 - Baramundi Documentation Agent ({job['label']})")
    run_cli(AGENT1_DIR, "run_agent1.py", [
        "--bds", job["agent1"]["bds"],
        "--xml-config", job["agent1"]["xml_config"],
        "--job-config", job["agent1"]["job_config"],
        "--output-dir", "output", "--split", *dry,
    ])

    banner("Agent 2 - Requirement-to-Test Agent")
    # Agent 1's --dry-run never calls the LLM, so it never writes a real
    # requirements.md to chain from - fall back to Agent 2's own bundled
    # sample input so the dry-run pipeline still exercises Agent 2's prompt.
    if args.dry_run:
        requirements_path = str(AGENT2_DIR / "sample_inputs" / "requirements.md")
    else:
        requirements_path = str(AGENT1_DIR / "output" / "requirements.md")
    run_cli(AGENT2_DIR, "run_agent2.py", [
        "--requirements", requirements_path, "--output-dir", "output", *dry,
    ])

    banner("Agent 3 - Script Adaptation Agent")
    stdout3 = run_cli(AGENT3_DIR, "run_agent3.py", [
        "--requirement", job["requirement"], "--script", job["script"], *dry,
    ])
    pr_url = extract_field(stdout3, "pr_url")
    pr_number = int(re.search(r"/pull/(\d+)", pr_url).group(1)) if pr_url else args.pr_number

    banner("Agent 4 - Automation Review Agent")
    if pr_number is None:
        print("No PR to review (Agent 3 ran in --dry-run and no --pr-number was given) - skipping.")
    else:
        run_cli(AGENT4_DIR, "run_agent4.py", ["--pr-number", str(pr_number), *dry])

    banner("Human approval gate")
    if args.dry_run:
        print("Dry-run: skipping the merge gate - nothing real was opened to merge.")
        events.emit(AGENT, "mechanical", "Dry-run: skipped the merge gate")
    elif pr_number is None:
        print("No PR was opened - skipping the merge gate.")
        events.emit(AGENT, "mechanical", "No PR opened - skipped the merge gate")
    elif args.skip_human_gate:
        print(f"--skip-human-gate set: merging PR #{pr_number} without a manual pause.")
        events.emit(AGENT, "mechanical", f"Auto-merging PR #{pr_number} (--skip-human-gate)")
        subprocess.run(["gh", "pr", "merge", str(pr_number), "--merge", "--delete-branch"], cwd=REPO_DIR, check=True)
    else:
        events.emit(AGENT, "mechanical", f"Waiting for human approval to merge PR #{pr_number}...",
                    {"awaiting_approval": True, "pr_number": pr_number, "pr_url": pr_url})
        answer = input(f"Approve and merge PR #{pr_number} into main before execution? [y/N] ").strip().lower()
        if answer == "y":
            subprocess.run(["gh", "pr", "merge", str(pr_number), "--merge", "--delete-branch"], cwd=REPO_DIR, check=True)
            events.emit(AGENT, "handoff", f"PR #{pr_number} merged - approved script ready for Agent 5")
        else:
            events.emit(AGENT, "error", "Not merged - stopping before Agent 5")
            print("Not merged - stopping before Agent 5 (it must run against an approved, merged script).")
            return

    banner("Agent 5 - Execution & Self-Healing Agent")
    run_cli(AGENT5_DIR, "run_agent5.py", ["--script", job["script"], "--target-page", target_page, *dry])

    events.emit(AGENT, "done", "Pipeline finished")


if __name__ == "__main__":
    main()
