"""Git/GitHub(or GitLab) operations for Agent 3, shelled out to the system
`git` + `gh`/`glab` binaries rather than a Python git library - keeps the
only pip dependency at `anthropic`, same as Agents 1/2, and the CLI
already handles auth for us.

GIT_PROVIDER selects which host's CLI opens the pull/merge request -
"github" (default, uses `gh`) or "gitlab" (uses `glab`). The plain git
operations below (branch/commit/push) are identical either way; only
open_pr's actual command differs.
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
    from a prior run that pushed but then failed to open a PR - delete it
    first so this always starts from a fresh, up-to-date base instead of
    failing with "branch already exists" on a routine retry."""
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
    GIT_PROVIDER. --yes on the GitLab side skips glab's interactive
    submission confirmation, which would otherwise hang a non-interactive
    run."""
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
