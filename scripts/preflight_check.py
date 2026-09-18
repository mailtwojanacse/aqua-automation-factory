#!/usr/bin/env python3
"""Preflight check for the Aqua Automation Factory pipeline.

Run this before a demo, and always right after deploying onto a new
machine (a VM, a colleague's laptop, wherever) - it catches the class of
"works on my machine" gaps that are easy to miss by hand: a missing
binary, an agent's .env not set up for whichever LLM_BACKEND it's
configured for, automation_target's venv missing a dependency, the
dashboard not running.

Read-only - doesn't install anything or change any config, just reports.

    python3 scripts/preflight_check.py
    python3 scripts/preflight_check.py --json   # for scripting/CI

Exit code 0 = everything checked out. 1 = at least one FAIL (see below).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIRS = [
    "agent1_baramundi_doc", "agent2_requirement_to_test", "agent3_script_adaptation",
    "agent4_review", "agent5_execution_selfheal",
]
GIT_PROVIDER = os.environ.get("GIT_PROVIDER", "github").strip().lower()
# Not "python3" in the binaries list below: every agent invokes Python via
# sys.executable or a resolved venv path, never a bare "python3" command -
# and "python3" isn't guaranteed to be on PATH on Windows (only python/py
# typically are). This script itself running is proof a working Python is
# available.


def _git_cli():
    """Computed from GIT_PROVIDER at call time (not a frozen constant) so
    tests can monkeypatch GIT_PROVIDER and see it take effect."""
    return "glab" if GIT_PROVIDER == "gitlab" else "gh"


def _required_binaries():
    return ["git", _git_cli(), "node", "npm", "allure"]
# Vars each LLM_BACKEND needs to actually work (mirrors src/llm_client.py in
# every agent - kept as plain data here so this script doesn't need to
# import any agent's code, and stays useful even if an agent's venv isn't
# set up yet).
BACKEND_REQUIRED_VARS = {
    "anthropic_api": ["ANTHROPIC_API_KEY"],
    "openai_api": ["OPENAI_API_KEY"],
    "azure_openai": ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"],
    "claude_cli": [],  # uses the local `claude` CLI's own session auth, no key
}

OK, WARN, FAIL = "OK", "WARN", "FAIL"


def check(name):
    """Decorator registering a check function under a human-readable name.
    Each check function returns (status, detail)."""
    def wrap(fn):
        CHECKS.append((name, fn))
        return fn
    return wrap


CHECKS = []


@check("Required binaries on PATH")
def _check_binaries():
    required = _required_binaries()
    missing = [b for b in required if shutil.which(b) is None]
    if missing:
        return FAIL, f"missing: {', '.join(missing)}"
    return OK, ", ".join(required)


@check("Git host CLI authentication")
def _check_git_cli_auth():
    git_cli = _git_cli()
    if shutil.which(git_cli) is None:
        return FAIL, f"{git_cli} not installed - see binaries check above"
    result = subprocess.run([git_cli, "auth", "status"], capture_output=True, text=True)
    if result.returncode != 0:
        return FAIL, f"not logged in - run `{git_cli} auth login`"
    # Which stream `gh`/`glab auth status` writes to has changed across
    # versions - check both rather than assuming one. Both CLIs use the
    # same "Logged in to" phrasing.
    combined = result.stdout + result.stderr
    accounts = [line.strip() for line in combined.splitlines() if "Logged in to" in line]
    return OK, f"{len(accounts)} account(s) authenticated"


def _parse_env_file(env_path):
    """Minimal KEY=VALUE parser - good enough to check which vars are
    *present* without needing python-dotenv installed to run this script."""
    values = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _agent_env_check(agent_dir):
    env_path = ROOT / agent_dir / ".env"
    if not env_path.exists():
        return WARN, "no .env (fine if this agent only ever runs --dry-run or claude_cli)"
    values = _parse_env_file(env_path)
    backend = values.get("LLM_BACKEND", "anthropic_api")
    if backend not in BACKEND_REQUIRED_VARS:
        return WARN, f"LLM_BACKEND={backend} is not a recognized backend"
    missing = [v for v in BACKEND_REQUIRED_VARS[backend]
               if not values.get(v) or values[v].startswith("sk-ant-...") or "..." in values.get(v, "")]
    if missing:
        return FAIL, f"LLM_BACKEND={backend} but missing/placeholder: {', '.join(missing)}"
    return OK, f"LLM_BACKEND={backend}, required vars present"


for _agent in AGENT_DIRS:
    def _make(agent):
        def _fn():
            return _agent_env_check(agent)
        return _fn
    CHECKS.append((f"{_agent}/.env", _make(_agent)))


def _venv_python(repo):
    """Same lookup as agent5_execution_selfheal/src/runner.py._python_for,
    duplicated rather than imported (this script deliberately avoids
    importing any agent's code - see module docstring). Checks both venv
    layouts (POSIX .venv/bin/python3, Windows .venv/Scripts/python.exe)
    since this pipeline is deployed on both."""
    for candidate in (repo / ".venv" / "bin" / "python3", repo / ".venv" / "Scripts" / "python.exe"):
        if candidate.exists():
            return candidate
    return None


@check("automation_target repo + venv")
def _check_automation_target():
    repo = ROOT / "automation_target"
    if not (repo / ".git").exists():
        return FAIL, "not a git checkout - clone the demo target repo here"
    venv_python = _venv_python(repo)
    if venv_python is None:
        return WARN, "no .venv - Agent 5 will fall back to this interpreter (no Allure output)"
    result = subprocess.run(
        [str(venv_python), "-c", "import playwright, pytest, allure_commons"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return FAIL, f"venv missing a required package: {result.stderr.strip().splitlines()[-1] if result.stderr else 'unknown error'}"
    return OK, "git checkout + venv with playwright/pytest/allure-pytest all present"


@check("Dashboard reachable")
def _check_dashboard():
    url = os.environ.get("AQUA_DASHBOARD_URL", "http://localhost:8787")
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
            ok = body.get("ok", False)
            return (OK if ok else WARN), f"{url} - {body}"
    except urllib.error.HTTPError as exc:
        return WARN, f"{url} responded but /health returned {exc.code} - is it running an older server.py?"
    except (urllib.error.URLError, OSError, TimeoutError):
        return WARN, f"{url} not reachable - dashboard isn't running (fine if you don't need it right now)"


def run_all():
    results = []
    for name, fn in CHECKS:
        try:
            status, detail = fn()
        except Exception as exc:
            status, detail = FAIL, f"check itself crashed: {exc}"
        results.append({"name": name, "status": status, "detail": detail})
    return results


def print_report(results):
    width = max(len(r["name"]) for r in results) + 2
    for r in results:
        print(f"[{r['status']:<4}] {r['name']:<{width}} {r['detail']}")
    counts = {OK: 0, WARN: 0, FAIL: 0}
    for r in results:
        counts[r["status"]] += 1
    print(f"\n{counts[OK]} OK, {counts[WARN]} warning(s), {counts[FAIL]} failure(s)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON instead of a report")
    args = parser.parse_args()

    results = run_all()
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_report(results)

    sys.exit(1 if any(r["status"] == FAIL for r in results) else 0)


if __name__ == "__main__":
    main()
