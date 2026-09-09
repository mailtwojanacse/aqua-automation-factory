# Agent 5 — Execution & Self-Healing Agent

Fifth and final agent in the **Aqua Automation Factory** pipeline. It runs
the approved automation script, captures evidence (screenshot + pytest
log), and if a test fails because a UI selector no longer exists, it
**self-heals**: asks the AI for a replacement selector, verifies the fix by
re-running the test, and (only on success) pushes the fix and opens a
follow-up PR so it stays traceable through Git.

## Pipeline position

```
Agent 1 -> Agent 2 -> Agent 3 -> Agent 4 Review -> [Agent 5] Execution & Self-Healing
                                                       (this repo)
```

## How it works

1. **Allow-list check** - only scripts under `tests/` in the target repo
   may run (mirrors the client's "only scripts inside `063 Aqua-Automation`
   may run" rule from the slide).
2. **Run** `pytest <script> -v` against the given `--target-page`, saving
   the full log to `output/pytest.log`.
3. **Capture evidence** - a screenshot of the target page's end state,
   independent of whether pytest passed, saved to `output/`.
4. If it **passed**, done.
5. If it **failed on a broken locator** (a Playwright `TimeoutError`
   waiting for a selector - detected from the log text):
   - **Dry-run / no key:** writes the exact "here's the broken selector and
     the current page HTML, suggest a fix" prompt to
     `output/self_heal.prompt.txt` and reports the failure honestly. No
     faked pass.
   - **Real run:** sends that same prompt to the AI, applies the suggested
     selector on a new branch, **re-runs the test to verify the fix
     actually works**, and only if it now passes does it push the branch
     and open a follow-up PR (`Self-heal: <old> -> <new>`). If the fix
     doesn't work, the attempt is discarded locally and reported as failed
     - nothing broken is ever pushed.
6. If it failed for any other reason, it's reported as a plain failure with
   the log for a human to investigate - self-heal only ever targets broken
   locators.

## Demo path

```bash
python run_agent5.py                                                        # v1 -> passes
python run_agent5.py --target-page install_confirmation_v2.html --dry-run   # v2 -> detects break, writes prompt
python run_agent5.py --target-page install_confirmation_v2.html             # v2 -> self-heals, opens a PR
```

`install_confirmation_v2.html` simulates a later app UI update (the Verify
button's id changed) without the script being updated - exactly the
scenario self-healing exists for.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env      # then add your ANTHROPIC_API_KEY
```

`.env` loads automatically (via `python-dotenv`, called at the top of `run_agentN.py`) - no need to `source` it or export vars by hand.

## Structure

```
run_agent5.py                  CLI entry point
src/execution.py                Orchestration: allow-list -> run -> evidence -> (self-heal)
src/runner.py                   pytest execution, screenshot capture, broken-locator detection
src/heal_prompt_builder.py      Builds the "fix this selector" prompt
src/llm_client.py                Anthropic API wrapper (lazy import; --dry-run needs no key/package)
src/self_healer.py               Branch -> patch -> re-verify -> commit/push/PR (only if the fix works)
src/git_ops.py                   Branch/commit/push + `gh pr create`, shelled out to git/gh
```

## Tests

Unit tests cover the pure mechanical logic - the allow-list check, broken-
locator detection, selector-fix patching, and the pytest/Allure command
building (subprocess calls mocked, so no real browser/`allure` CLI needed) -
not the AI call, real pytest run, or real git/gh operations:

```bash
pytest tests/ -v
```

## Known assumptions (validate with client)

1. **Self-heal only targets locator-timeout failures.** Any other failure
   (assertion mismatch, app error, etc.) is reported for a human to
   investigate - deliberately, since self-healing the wrong kind of failure
   could hide a real regression.
2. **One retry.** If the first suggested selector doesn't fix it, Agent 5
   reports `self_heal_failed` rather than looping indefinitely.
3. **Folder allow-list is hardcoded to `tests/`** for this demo; make it
   configurable (e.g. matching the client's real `063 Aqua-Automation`
   folder name) once wired to the client's actual repo.
4. **`LLM_BACKEND` switch** (`.env`) — `anthropic_api` (default, needs `ANTHROPIC_API_KEY`),
   `openai_api` (ChatGPT, needs `OPENAI_API_KEY`), `azure_openai` (needs `AZURE_OPENAI_*`),
   or `claude_cli` (shells out to the already-logged-in `claude` CLI on this machine, no
   key needed - local dev/demoing only, not meant for the volume of an unattended
   production deployment). GitHub Copilot and Cursor aren't wireable the same way - neither
   exposes a general-purpose completion API for a script like this to call.
