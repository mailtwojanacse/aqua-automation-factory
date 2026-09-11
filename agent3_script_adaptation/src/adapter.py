"""Orchestrates Agent 3: read requirement + current script -> LLM -> commit
the adapted script on a new branch -> open a GitHub pull request."""
import ast
import re
from pathlib import Path

from src import events, git_ops, llm_client, prompt_builder

AGENT = "Agent 3"


def extract_code_block(text):
    """Pull the code out of a fenced ```python ... ``` block, tolerating a
    missing language tag. Falls back to the raw text if no fence is found."""
    text = text.strip()
    match = re.search(r"```(?:python)?\n(.*?)\n```", text, re.DOTALL)
    return match.group(1) if match else text


def is_valid_python(script_text):
    """A truncated or empty AI response (e.g. hitting the token cap) has no
    closing fence for extract_code_block to match, so it falls back to
    returning raw/empty text - this catches that before it's ever written,
    committed, and opened as a real PR for a human to review."""
    if not script_text or not script_text.strip():
        return False
    try:
        ast.parse(script_text)
        return True
    except SyntaxError:
        return False


def adapt_script(*args, **kwargs):
    try:
        return _adapt_script(*args, **kwargs)
    except Exception as exc:
        events.emit(AGENT, "error", f"Failed: {exc}")
        raise


def _adapt_script(requirement_path, repo_path, script_relpath, output_dir, dry_run=False):
    events.emit(AGENT, "start", f"Starting for requirement {Path(requirement_path).name}",
                {"requirement_path": requirement_path, "script": script_relpath})

    requirement_text = Path(requirement_path).read_text(encoding="utf-8")
    repo_path = Path(repo_path)
    script_path = repo_path / script_relpath
    current_script = script_path.read_text(encoding="utf-8")
    events.emit(AGENT, "mechanical", f"Read requirement + current script ({len(current_script)} chars)")

    system_prompt, user_prompt = prompt_builder.build_prompt(requirement_text, current_script, script_relpath)
    events.emit(AGENT, "mechanical", f"Assembled prompt asking for the full updated file ({len(system_prompt) + len(user_prompt)} chars)")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Dry run: write the prompt that WOULD be sent, without calling the API
    # or touching git/GitHub - there's nothing real to commit without real AI output.
    if dry_run:
        prompt_path = output_dir / "adapt.prompt.txt"
        prompt_path.write_text(
            f"===== SYSTEM PROMPT =====\n{system_prompt}\n"
            f"\n===== USER PROMPT =====\n{user_prompt}\n",
            encoding="utf-8",
        )
        events.emit(AGENT, "ai_dry_run", "Dry-run: skipped the AI call and all git/GitHub actions, wrote the exact prompt instead",
                    {"path": str(prompt_path)})
        events.emit(AGENT, "done", "Finished (dry-run)")
        return {"dry_run_prompt": str(prompt_path)}

    events.emit(AGENT, "ai_call", "Calling the AI to adapt the script for the new requirement")
    raw = llm_client.generate(system_prompt, user_prompt)
    updated_script = extract_code_block(raw)
    events.emit(AGENT, "ai_call", f"AI returned the updated script ({len(updated_script)} chars)")

    if not is_valid_python(updated_script):
        events.emit(AGENT, "error",
                    "AI's returned script failed validation (empty, or not syntactically valid "
                    "Python) - refusing to write, commit, or open a PR with it")
        return {"status": "adapt_invalid_script", "script": str(script_path)}

    # The requirement may already be satisfied by the current script (e.g. it
    # was applied in an earlier run) - the AI then correctly returns the file
    # unchanged. Skip branch/commit/PR in that case rather than attempting a
    # git commit with nothing to commit, which would fail.
    if updated_script == current_script:
        events.emit(AGENT, "done", "No change needed - the script already satisfies this requirement")
        return {"status": "no_change_needed", "script": str(script_path)}

    requirement_title = requirement_text.strip().splitlines()[0].lstrip("# ").strip()
    branch_name = f"agent3/{git_ops.slugify(requirement_title)}"

    git_ops.checkout_branch_from_main(repo_path, branch_name)
    events.emit(AGENT, "mechanical", f"Created branch {branch_name} from main")

    script_path.write_text(updated_script, encoding="utf-8")

    commit_message = f"Agent 3: adapt {script_relpath}\n\n{requirement_title}"
    git_ops.commit_and_push(repo_path, [script_relpath], commit_message, branch_name)
    events.emit(AGENT, "mechanical", f"Committed and pushed {script_relpath} to {branch_name}")

    pr_title = f"Agent 3: {requirement_title}"
    pr_body = (
        "Automated script adaptation raised by Agent 3 (Script Adaptation Agent).\n\n"
        f"**Requirement:**\n{requirement_text}\n\n"
        f"**Changed file:** `{script_relpath}`\n\n"
        "_Awaiting Agent 4 (Automation Review) before merge._"
    )
    pr_url = git_ops.open_pr(repo_path, branch_name, pr_title, pr_body)
    events.emit(AGENT, "mechanical", f"Opened pull request: {pr_url}")
    events.emit(AGENT, "handoff", f"{pr_url} ready for Agent 4 to review", {"pr_url": pr_url})
    events.emit(AGENT, "done", "Finished", {"branch": branch_name, "pr_url": pr_url})

    return {"branch": branch_name, "pr_url": pr_url, "script": str(script_path)}
