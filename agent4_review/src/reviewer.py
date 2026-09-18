"""Orchestrates Agent 4: fetch a PR/MR's diff -> LLM review -> post a real
review (or write the prompt only, in --dry-run).

GIT_PROVIDER selects "github" (default, uses `gh`) or "gitlab" (uses `glab`).

GitHub refuses to let an account approve/request-changes on its own pull
request, so on GitHub Agent 4 must run as a *different* identity than
whoever opened the PR (Agent 3). REVIEWER_ACCOUNT is that identity - it
must already be authenticated locally (`gh auth login`) and have at least
Write access to the repo. We switch the active `gh` account for the
duration of the review and always switch back to PR_AUTHOR_ACCOUNT
afterward, so Agents 1/3/5 keep running as the account that owns the
PRs/branches.

GitLab has no equivalent of `gh auth switch` - `glab` reads whichever
GITLAB_TOKEN environment variable is set for a given invocation, with no
persistent state to switch back afterward. So on GitLab, AGENT4_REVIEWER_TOKEN
(a personal access token for the reviewer identity) is passed as an env
override on just the calls that need it, instead of mutating global CLI
auth state - simpler, and it sidesteps the whole "switch back failed"
failure mode that exists on the GitHub side entirely.
"""
import json
import os
import re
import subprocess
from pathlib import Path

from src import events, llm_client, prompt_builder

GIT_PROVIDER = os.environ.get("GIT_PROVIDER", "github").strip().lower()
REVIEWER_ACCOUNT = os.environ.get("AGENT4_REVIEWER_ACCOUNT", "srjanakiraman23")  # GitHub username
PR_AUTHOR_ACCOUNT = os.environ.get("AGENT4_AUTHOR_ACCOUNT", "mailtwojanacse")  # GitHub username
GITLAB_REVIEWER_TOKEN = os.environ.get("AGENT4_REVIEWER_TOKEN", "")  # GitLab personal access token
AGENT = "Agent 4"


def _run(args, cwd, env_overrides=None):
    env = {**os.environ, **env_overrides} if env_overrides else None
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)}\n{result.stderr}")
    return result.stdout.strip()


def _switch_account(username):
    """GitHub-only - see module docstring for why GitLab doesn't need this."""
    result = subprocess.run(["gh", "auth", "switch", "--user", username], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh auth switch --user {username} failed:\n{result.stderr.strip()}")


def _reviewer_env():
    return {"GITLAB_TOKEN": GITLAB_REVIEWER_TOKEN} if GITLAB_REVIEWER_TOKEN else None


def get_pr(repo_path, pr_number):
    if GIT_PROVIDER == "gitlab":
        meta = json.loads(_run(["glab", "mr", "view", str(pr_number), "--output", "json"],
                                cwd=repo_path, env_overrides=_reviewer_env()))
        diff = _run(["glab", "mr", "diff", str(pr_number)], cwd=repo_path, env_overrides=_reviewer_env())
        return meta["title"], meta.get("description", ""), diff
    meta = json.loads(_run(["gh", "pr", "view", str(pr_number), "--json", "title,body"], cwd=repo_path))
    diff = _run(["gh", "pr", "diff", str(pr_number)], cwd=repo_path)
    return meta["title"], meta["body"], diff


def parse_verdict_json(text):
    """Parse the model's response into a dict, tolerating stray code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    return json.loads(text)


def format_review_body(summary, comments):
    lines = [summary, ""]
    if comments:
        lines.append("**Findings:**")
        for c in comments:
            if isinstance(c, dict):
                lines.append(f"- **{c.get('concern', 'note')}:** {c.get('detail', '')}")
            else:
                # The AI returned a plain string instead of {concern, detail} -
                # render it rather than crashing the whole review over it.
                lines.append(f"- **note:** {c}")
    lines.append("")
    lines.append("_Posted automatically by Agent 4 (Automation Review Agent)._")
    return "\n".join(lines)


def post_review(repo_path, pr_number, verdict, body):
    if GIT_PROVIDER == "gitlab":
        # GitLab has no native "request changes" review state the way
        # GitHub does - the AI's explanation always goes on as a note, and
        # the MR is additionally approved only when the verdict says to.
        result = _run(["glab", "mr", "note", "create", str(pr_number), "--message", body],
                       cwd=repo_path, env_overrides=_reviewer_env())
        if verdict == "approve":
            _run(["glab", "mr", "approve", str(pr_number)], cwd=repo_path, env_overrides=_reviewer_env())
        return result
    flag = "--approve" if verdict == "approve" else "--request-changes"
    return _run(["gh", "pr", "review", str(pr_number), flag, "--body", body], cwd=repo_path)


def review_pr(repo_path, pr_number, output_dir, dry_run=False):
    events.emit(AGENT, "start", f"Starting review of PR #{pr_number}", {"pr_number": pr_number})

    if GIT_PROVIDER != "gitlab":
        _switch_account(REVIEWER_ACCOUNT)
        events.emit(AGENT, "mechanical", f"Switched active GitHub account to reviewer identity ({REVIEWER_ACCOUNT})")
    try:
        pr_title, pr_body, diff_text = get_pr(repo_path, pr_number)
        events.emit(AGENT, "mechanical", f"Fetched PR diff ({len(diff_text.splitlines())} lines)")

        system_prompt, user_prompt = prompt_builder.build_prompt(pr_title, pr_body, diff_text)
        events.emit(AGENT, "mechanical", f"Assembled review prompt with the verdict JSON schema ({len(system_prompt) + len(user_prompt)} chars)")

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Dry run: write the prompt that WOULD be sent, without calling the API
        # or posting a review - there's nothing real to post without real AI output.
        if dry_run:
            prompt_path = output_dir / f"review_{pr_number}.prompt.txt"
            prompt_path.write_text(
                f"===== SYSTEM PROMPT =====\n{system_prompt}\n"
                f"\n===== USER PROMPT =====\n{user_prompt}\n",
                encoding="utf-8",
            )
            events.emit(AGENT, "ai_dry_run", "Dry-run: skipped the AI call and posted no review, wrote the exact prompt instead",
                        {"path": str(prompt_path)})
            events.emit(AGENT, "done", "Finished (dry-run)")
            return {"dry_run_prompt": str(prompt_path)}

        events.emit(AGENT, "ai_call", "Calling the AI to review the diff for quality, security, and traceability")
        raw = llm_client.generate(system_prompt, user_prompt)
        verdict_data = parse_verdict_json(raw)
        events.emit(AGENT, "ai_call", f"AI returned a verdict: {verdict_data.get('verdict', 'unknown')}")

        # Keep the raw verdict for traceability, same idea as Agent 2's saved JSON.
        json_path = output_dir / f"review_{pr_number}.json"
        json_path.write_text(json.dumps(verdict_data, indent=2), encoding="utf-8")

        verdict = verdict_data.get("verdict", "request_changes")
        body = format_review_body(verdict_data.get("summary", ""), verdict_data.get("comments", []))
        post_review(repo_path, pr_number, verdict, body)
        events.emit(AGENT, "mechanical", f"Posted review: {verdict}")
        events.emit(AGENT, "handoff", f"PR #{pr_number} reviewed ({verdict}) - ready for Agent 5 once merged", {"verdict": verdict})
        events.emit(AGENT, "done", "Finished", {"verdict": verdict})

        return {"verdict": verdict, "review_json": str(json_path)}
    except Exception as exc:
        events.emit(AGENT, "error", f"Failed: {exc}")
        raise
    finally:
        if GIT_PROVIDER != "gitlab":
            try:
                _switch_account(PR_AUTHOR_ACCOUNT)
            except Exception as switch_back_exc:
                events.emit(AGENT, "error",
                            f"Failed to switch back to {PR_AUTHOR_ACCOUNT} after reviewing - gh is "
                            f"left authenticated as {REVIEWER_ACCOUNT}, which will affect any "
                            f"Agent 1/3/5 run until this is fixed manually: {switch_back_exc}")
                raise
