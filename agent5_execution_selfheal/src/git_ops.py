"""Git/GitHub operations for Agent 5's self-heal follow-up PR, shelled out
to the system `git` and `gh` binaries - same approach as Agent 3's git_ops,
duplicated here rather than shared so each agent folder stays self-contained.
"""
import re
import subprocess


def slugify(text, max_len=40):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "change"


def _run(args, cwd):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)}\n{result.stderr}")
    return result.stdout.strip()


def checkout_branch_from_main(repo_path, branch_name, base="main"):
    _run(["git", "fetch", "origin", base], cwd=repo_path)
    _run(["git", "checkout", base], cwd=repo_path)
    _run(["git", "pull", "origin", base], cwd=repo_path)
    _run(["git", "checkout", "-b", branch_name], cwd=repo_path)


def commit_and_push(repo_path, paths, message, branch_name):
    _run(["git", "add", *paths], cwd=repo_path)
    _run(["git", "commit", "-m", message], cwd=repo_path)
    _run(["git", "push", "-u", "origin", branch_name], cwd=repo_path)


def open_pr(repo_path, branch_name, title, body, base="main"):
    return _run(
        ["gh", "pr", "create", "--title", title, "--body", body, "--base", base, "--head", branch_name],
        cwd=repo_path,
    )


def checkout_main(repo_path, base="main"):
    _run(["git", "fetch", "origin", base], cwd=repo_path)
    _run(["git", "checkout", base], cwd=repo_path)
    _run(["git", "pull", "origin", base], cwd=repo_path)
