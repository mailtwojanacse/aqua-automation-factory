# Ops Runbook — Aqua Automation Factory

Operational reference for running this pipeline on a machine (this laptop
today, a VM later): fresh setup, health checks, and what to do when
something's broken. For what the pipeline *does* and why, see
`PROJECT_OVERVIEW.md`; for how a specific agent works, see that agent's
own `README.md`.

## Fresh-machine setup

1. **Clone this repo and the target repo.** `automation_target` is a real,
   separate GitHub repo (the demo's stand-in for the client's automation
   repo) - clone it as a sibling folder to this one, at `automation_target/`.

2. **Install the binaries every agent assumes are on PATH:** `git`, `gh`
   (authenticated - `gh auth login`), `node` + `npm` (needed to install the
   Allure CLI: `npm install -g allure-commandline`), `python3`.

3. **Set up each of the 5 agents' own venvs** (each agent folder is
   independently runnable, so each gets its own):
   ```bash
   cd agentN_.../
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env   # then fill in the real key/vars for whichever LLM_BACKEND you want
   ```
   `.env` loads automatically now (`python-dotenv`, wired into every
   `run_agentN.py`) - no need to `source` it or export vars by hand. If
   you only ever plan to demo with `--dry-run` or `LLM_BACKEND=claude_cli`,
   you can skip the `.env` step entirely - both need no API key.

4. **Set up `automation_target`'s own venv** (separate from the 5 agents'
   venvs above - this one runs the actual Playwright/pytest suite Agent 5
   executes):
   ```bash
   cd automation_target/
   python -m venv .venv && .venv/bin/pip install -r requirements.txt
   .venv/bin/playwright install chromium
   ```

5. **Start the dashboard as a persistent service**, not a one-off process
   (see `dashboard/README.md` for the full systemd setup):
   ```bash
   cp dashboard/aqua-dashboard.service ~/.config/systemd/user/
   # edit ExecStart/WorkingDirectory in that file first if this repo lives
   # somewhere other than where it was copied from
   systemctl --user daemon-reload
   systemctl --user enable --now aqua-dashboard.service
   ```

6. **Run the preflight check** (see below) to confirm all of the above
   actually took.

## Preflight check

```bash
python3 scripts/preflight_check.py
```

Checks, in order: required binaries present, `gh` authentication, each
agent's `.env` (present, and - if it sets a non-default `LLM_BACKEND` -
that backend's required vars aren't still placeholder values),
`automation_target`'s git checkout + venv, and the dashboard's `/health`
endpoint. Prints `OK` / `WARN` / `FAIL` per check; exits non-zero if
anything is a `FAIL` (safe to wire into a deploy script as a gate). Add
`--json` for machine-readable output.

`WARN` on an agent's `.env` just means it's not there - fine if that agent
only ever runs `--dry-run` or `LLM_BACKEND=claude_cli`, both of which need
no key. It only becomes a real problem (and preflight will say `FAIL`) once
you actually try a real run without the matching key set.

## Demo reset

```bash
python3 scripts/reset_demo.py                        # dry-run report - nothing deleted
python3 scripts/reset_demo.py --yes                  # actually clean up stale branches
python3 scripts/reset_demo.py --yes --clear-outputs   # also clear each agent's output/ folder
```

Cleans up the accumulated clutter from repeated demo/test runs of
`automation_target` before a fresh one: syncs `main`, deletes stale local
branches, and deletes stale *remote* branches - but only the ones that
don't back an open pull request. Open PRs are always left alone and just
reported, never auto-closed - a demo reset shouldn't silently discard
someone's in-progress review. Refuses to run at all if the working tree
has uncommitted changes, rather than risk discarding real work.

## Health check (dashboard already running)

```bash
curl http://localhost:8787/health
```

Returns `{"ok": true/false, "checks": {...}}` - `events_db_queryable` is
the one that actually gates `ok`; the rest (`allure_report_present`,
`traceability_report_present`, `slack_alerts_enabled`, `pipeline_running`)
are informational. Cheap enough to poll from an external monitor.

## Common failures and fixes

**Dashboard unreachable (`http://localhost:8787` refuses connections)**
The server is a plain process unless it's running under systemd - check
`systemctl --user status aqua-dashboard.service`. If it's not installed
as a service yet, see step 5 above; that's the actual fix, not just
restarting it by hand again.

**A real (non-dry-run) agent run fails immediately with an auth/API error**
Almost always a `.env` problem - run `scripts/preflight_check.py` first,
it will name the exact missing variable. Remember `.env` is per-agent,
not shared.

**`git branch already exists` / `non-fast-forward` when Agent 3 or 5 runs**
A stale branch from a previous run against the same requirement/selector.
`cd automation_target && git checkout main && git branch -D <branch>`
(and `git push origin --delete <branch>` if it was already pushed), then
re-run.

**Agent 4 tries to review its own PR and GitHub refuses**
`AGENT4_REVIEWER_ACCOUNT` must be a *different* authenticated `gh`
identity than whichever account opened the PR
(`AGENT4_AUTHOR_ACCOUNT`/Agent 3's account) - see `agent4_review/README.md`.
Confirm both are in `gh auth status`.

**No Allure report / traceability report despite Agent 5 running**
Both are best-effort: `runner.generate_allure_report` needs the `allure`
CLI on PATH, and the traceability report additionally needs `gh`. Check
`scripts/preflight_check.py`'s binaries check, and check the audit trail
(dashboard History tab, or `agent5_execution_selfheal/output/pytest.log`)
for a "skipped" message explaining why.

**Externally-managed-environment / PEP 668 error on `pip install`**
You're installing into the system Python. Every setup step above uses a
venv specifically to avoid this - if you see this error, you skipped the
`python -m venv .venv` step somewhere.

## Security review (2026-09-01)

A dedicated pass over the pipeline's attack surface (subprocess calls,
AI-controlled inputs, secret handling, file-path trust boundaries). Two
real, verified issues were found and fixed - both were pure hardening
fixes with no behavior change for legitimate use (confirmed by the full
test suite plus real end-to-end runs against both suites):

1. **Path-traversal bypass in Agent 5's folder allow-list**
   (`runner.check_allowed`) - it was a plain string-prefix check
   (`"tests/../../../etc/passwd".startswith("tests/")` is `True`), so a
   `../`-laden path sailed straight through. Fixed to resolve the path and
   check real containment inside `tests/`.
2. **Unsanitized AI output spliced into executable Python, then run**
   (`self_healer.apply_selector_fix`) - the LLM's suggested replacement
   selector was written into the test file's source with no validation. A
   crafted selector containing a quote + semicolon could break out of the
   string literal it's spliced into and inject an arbitrary Python
   statement - which then runs immediately via pytest as part of
   self-heal's own "verify the fix" step, before any human review or PR
   gate. In production the page HTML feeding that prompt comes from the
   client's real application, not our own trusted static files, so this
   was a real prompt-injection -> code-execution chain. Fixed with
   `self_healer.is_safe_selector()`, a strict allowlist gate that runs
   before anything is written to disk.

Also fixed as defense in depth: `target_page` had the same string-based
gap as (1) in the plain CLI path (the dashboard's `/run` endpoint already
validates it against a fixed allowlist) - lower severity since it needs
pre-existing shell access to exploit, and worst case is reading/rendering
an arbitrary local file rather than code execution.

No other issues found: every `subprocess` call already used list-form
arguments (no `shell=True`, no string-built commands - not injectable by
construction), all SQL uses parameterized queries, `.env`/`.venv` are
gitignored everywhere, and the audit trail never logs secret values.

## Logs and where things live

| What | Where |
|---|---|
| Dashboard process logs | `journalctl --user -u aqua-dashboard.service -f` |
| Full agent/pipeline audit trail | `dashboard/events.db` (browse via the dashboard's History tab, not by hand) |
| Per-run mechanical output (prompts, logs, screenshots) | `agentN_.../output/` |
| Allure test-results report | `agent5_execution_selfheal/allure-report/` (served at `/allure/`) |
| Requirement traceability report | `traceability/report.json` + `traceability/index.html` (served at `/traceability/`) |
| Auto-trigger inbox (file-watch mode) | `orchestrator/inbox/` |

## Version control & CI

This repo (the pipeline itself - agents, dashboard, orchestrator, scripts)
lives at `github.com/mailtwojanacse/aqua-automation-factory` (private) -
until 2026-09-08 it had never been under version control at all. Every
push/PR to `main` runs the full 160-test unit suite via GitHub Actions
(`.github/workflows/test.yml`), one job per module. `automation_target`
(the demo target repo) stays separate and independently version-controlled
- intentionally excluded here via `.gitignore`, not nested inside.

## Known gaps as of this writing

- `dashboard/aqua-dashboard.service` hardcodes this machine's absolute
  paths - update `ExecStart`/`WorkingDirectory` before copying it onto a
  new machine.
- `anthropic_api`/`openai_api`/`azure_openai` backends have never been
  exercised against the real APIs in this environment (demoing has used
  `claude_cli` and `--dry-run` throughout) - the SDKs are pinned to
  versions confirmed to install and import cleanly here, but a real
  end-to-end call with a live key should be tried at least once before
  relying on them for a client demo.
- Client input on which AI provider they'll actually use is still
  outstanding - see `PROJECT_OVERVIEW.md` section 7.1.
