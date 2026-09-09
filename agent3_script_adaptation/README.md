# Agent 3 — Script Adaptation Agent (AI Copilot)

Third agent in the **Aqua Automation Factory** pipeline. When a requirement
changes, it updates the Python automation script that Agent 5 will run, and
raises a **real GitHub pull request** for Agent 4 to review.

## Pipeline position

```
Agent 1 -> Agent 2 -> [Agent 3] Script Adaptation -> Agent 4 Review -> Agent 5 Execution & Self-Healing
                          (this repo)
```

## How it works

1. Read the new/changed requirement and the current script from
   `automation_target` (a real local Git checkout, pushed to GitHub).
2. Ask the LLM to return the **full updated file content** in a fenced
   Python code block (not a diff - simpler and more reliable to apply than
   asking the model for a correct unified diff).
3. Create a branch (`agent3/<slug-of-requirement>`), write the updated
   file, commit, push, and open a PR via `gh pr create`.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then add your ANTHROPIC_API_KEY
```

`.env` loads automatically (via `python-dotenv`, called at the top of `run_agentN.py`) - no need to `source` it or export vars by hand.

Requires `git` and an authenticated `gh` CLI (`gh auth status`) with push
access to the `automation_target` repo - no extra Python git library needed.

## Run

```bash
python run_agent3.py
# -> creates a branch, commits the adapted script, opens a real PR
```

## Dry run (no API key needed)

```bash
python run_agent3.py --dry-run
# -> writes output/adapt.prompt.txt, touches no git/GitHub state at all
```
Dry-run stops before the LLM call, since without real AI output there is
nothing legitimate to commit or open a PR for.

## Structure

```
run_agent3.py            CLI entry point
src/prompt_builder.py    Builds the "adapt this script for this requirement" prompt
src/llm_client.py        Anthropic API wrapper (lazy import; --dry-run needs no key/package)
src/git_ops.py           Branch/commit/push + `gh pr create`, shelled out to git/gh
src/adapter.py           Orchestration: read -> generate -> extract code -> commit -> PR
sample_inputs/           Example new_requirement.md
```

## Tests

Unit tests cover the pure mechanical logic - extracting code from the
model's fenced response, and the git/gh command sequences (mocked, no real
git/gh calls) - not the AI call itself (no API key needed to run them):

```bash
pytest tests/ -v
```

## Known assumptions (validate with client)

1. **Full-file replacement, not a diff.** The model returns the whole
   updated script; we don't ask it to produce a patch. Fine for one script
   file at this size - would need diff-based editing for larger files.
2. **Branch/PR naming and target repo.** Wired to the local `automation_target`
   demo repo pointed to by `--repo-path`. Swap to the client's real repo path
   once they confirm the Git access described in `PROJECT_OVERVIEW.md`.
3. **`LLM_BACKEND` switch** (`.env`) — `anthropic_api` (default, needs `ANTHROPIC_API_KEY`),
   `openai_api` (ChatGPT, needs `OPENAI_API_KEY`), `azure_openai` (needs `AZURE_OPENAI_*`),
   or `claude_cli` (shells out to the already-logged-in `claude` CLI on this machine, no
   key needed - local dev/demoing only, not meant for the volume of an unattended
   production deployment). GitHub Copilot and Cursor aren't wireable the same way - neither
   exposes a general-purpose completion API for a script like this to call.
