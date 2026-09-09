# Agent 4 — Automation Review Agent

Fourth agent in the **Aqua Automation Factory** pipeline. It reviews the
pull request Agent 3 opened - for code quality, standards, security, and
requirement-traceability - and posts a **real GitHub PR review**
(approve or request changes).

## Pipeline position

```
Agent 1 -> Agent 2 -> Agent 3 Script Adaptation -> [Agent 4] Review -> Agent 5 Execution & Self-Healing
                                                       (this repo)
```

## How it works

1. Fetch the PR's title, description, and diff via `gh pr diff`.
2. Ask the LLM to review it and return **structured JSON**
   (`{"verdict": "approve"|"request_changes", "summary": "...", "comments": [...]}`)
   - not free text - so the code, not the model, decides which `gh pr review`
   flag to use. Same JSON-then-code pattern as Agent 2's CSV generation.
3. Post a **native** `gh pr review --approve`/`--request-changes` on the PR.
   The raw verdict JSON is also saved to `output/` for traceability.

   **Why Agent 4 needs its own GitHub identity:** GitHub refuses to let an
   account approve/request-changes on its own pull request. Agent 3 opens
   PRs as `mailtwojanacse`; Agent 4 reviews as a second account,
   `srjanakiraman23` (configurable via the `AGENT4_REVIEWER_ACCOUNT` env
   var), which was added as a collaborator on the repo and authenticated
   locally with `gh auth login`. `reviewer.py` switches the active `gh`
   account to the reviewer for the duration of the review and always
   switches back to the PR-author account (`AGENT4_AUTHOR_ACCOUNT`,
   default `mailtwojanacse`) afterward, so Agents 1/3/5 keep running as the
   account that owns the PRs/branches.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then add your ANTHROPIC_API_KEY
```

`.env` loads automatically (via `python-dotenv`, called at the top of `run_agentN.py`) - no need to `source` it or export vars by hand.

Requires `git` and an authenticated `gh` CLI with review access to the
`automation_target` repo.

## Run

```bash
python run_agent4.py --pr-number 1
# -> posts a real approve/request-changes review on PR #1
```

## Dry run (no API key needed)

```bash
python run_agent4.py --pr-number 1 --dry-run
# -> writes output/review_1.prompt.txt, posts no review
```

## Structure

```
run_agent4.py            CLI entry point
src/prompt_builder.py    Builds the review prompt + the verdict JSON contract
src/llm_client.py        Anthropic API wrapper (lazy import; --dry-run needs no key/package)
src/reviewer.py          gh pr diff -> prompt -> parse verdict JSON -> gh pr review
```

## Tests

Unit tests cover the pure mechanical logic - parsing the model's verdict
JSON (including stray code fences) and formatting the review body - not the
AI call or the real `gh pr review` itself (no API key needed to run them):

```bash
pytest tests/ -v
```

## Known assumptions (validate with client)

1. **Verdict is binary** (approve / request_changes) - matches the slide's
   "review or request changes" box. No "comment only" state yet.
2. **One review pass, no back-and-forth loop.** If changes are requested,
   a human (or a future Agent 3 re-run) addresses them and Agent 4 is run
   again manually - no automatic retry loop yet.
3. **`LLM_BACKEND` switch** (`.env`) — `anthropic_api` (default, needs `ANTHROPIC_API_KEY`),
   `openai_api` (ChatGPT, needs `OPENAI_API_KEY`), `azure_openai` (needs `AZURE_OPENAI_*`),
   or `claude_cli` (shells out to the already-logged-in `claude` CLI on this machine, no
   key needed - local dev/demoing only, not meant for the volume of an unattended
   production deployment). GitHub Copilot and Cursor aren't wireable the same way - neither
   exposes a general-purpose completion API for a script like this to call.
