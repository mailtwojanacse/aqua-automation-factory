"""Git/GitHub(or GitLab) operations for Agent 5's self-heal follow-up PR,
shelled out to the system `git` + `gh`/`glab` binaries - same approach as
Agent 3's git_ops, duplicated here rather than shared so each agent folder
stays self-contained.

GIT_PROVIDER selects which host's CLI opens the pull/merge request -
"github" (default, uses `gh`) or "gitlab" (uses `glab`).
"""
import os
import re
import subprocess

GIT_PROVIDER = os.environ.get("GIT_PROVIDER", "github").strip().lower()


def slugify(text, max_len=40):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "change"


def _run(args, cwd):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)}\n{result.stderr}")
    return result.stdout.strip()


def _branch_exists_locally(repo_path, branch_name):
    result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", branch_name],
                             cwd=repo_path, capture_output=True, text=True)
    return result.returncode == 0


def checkout_branch_from_main(repo_path, branch_name, base="main"):
    """Idempotent: if branch_name already exists locally - e.g. left over
    from a prior heal attempt that pushed but then failed to open a PR -
    delete it first so this always starts from a fresh, up-to-date base
    instead of failing with "branch already exists" on a routine retry.
    Same fix as agent3_script_adaptation/src/git_ops.py's identical
    function (duplicated rather than shared, see module docstring)."""
    _run(["git", "fetch", "origin", base], cwd=repo_path)
    _run(["git", "checkout", base], cwd=repo_path)
    _run(["git", "pull", "origin", base], cwd=repo_path)
    if _branch_exists_locally(repo_path, branch_name):
        _run(["git", "branch", "-D", branch_name], cwd=repo_path)
    _run(["git", "checkout", "-b", branch_name], cwd=repo_path)


def commit_and_push(repo_path, paths, message, branch_name):
    _run(["git", "add", *paths], cwd=repo_path)
    _run(["git", "commit", "-m", message], cwd=repo_path)
    _run(["git", "push", "-u", "origin", branch_name], cwd=repo_path)


def open_pr(repo_path, branch_name, title, body, base="main"):
    """Opens a GitHub pull request or a GitLab merge request, depending on
    GIT_PROVIDER. Same behavior as agent3_script_adaptation/src/git_ops.py's
    identical function."""
    if GIT_PROVIDER == "gitlab":
        return _run(
            ["glab", "mr", "create", "--title", title, "--description", body,
             "--source-branch", branch_name, "--target-branch", base, "--yes"],
            cwd=repo_path,
        )
    return _run(
        ["gh", "pr", "create", "--title", title, "--body", body, "--base", base, "--head", branch_name],
        cwd=repo_path,
    )


def checkout_main(repo_path, base="main"):
    _run(["git", "fetch", "origin", base], cwd=repo_path)
    _run(["git", "checkout", base], cwd=repo_path)
    _run(["git", "pull", "origin", base], cwd=repo_path)
