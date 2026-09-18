import pytest

from src import git_ops


@pytest.mark.parametrize("text,expected", [
    ("Adobe Acrobat Reader DC", "adobe-acrobat-reader-dc"),
    ("#verify-btn -> #confirm-install-btn", "verify-btn-confirm-install-btn"),
])
def test_slugify_basic_cases(text, expected):
    assert git_ops.slugify(text) == expected


def test_slugify_empty_or_all_symbols_falls_back_to_change():
    assert git_ops.slugify("") == "change"
    assert git_ops.slugify("!!!???") == "change"


def test_run_raises_runtime_error_with_stderr_on_failure(monkeypatch):
    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "fatal: boom"

    monkeypatch.setattr(git_ops.subprocess, "run", lambda *a, **k: FakeResult())
    with pytest.raises(RuntimeError, match="boom"):
        git_ops._run(["git", "status"], cwd="/tmp")


def test_checkout_main_runs_fetch_checkout_pull(monkeypatch):
    calls = []
    monkeypatch.setattr(git_ops, "_run", lambda args, cwd: calls.append(args))

    git_ops.checkout_main("/repo")

    assert calls == [
        ["git", "fetch", "origin", "main"],
        ["git", "checkout", "main"],
        ["git", "pull", "origin", "main"],
    ]


def test_checkout_branch_from_main_creates_new_branch_last(monkeypatch):
    calls = []
    monkeypatch.setattr(git_ops, "_run", lambda args, cwd: calls.append(args))
    monkeypatch.setattr(git_ops, "_branch_exists_locally", lambda repo_path, branch_name: False)

    git_ops.checkout_branch_from_main("/repo", "agent5-selfheal/verify-btn")

    assert calls[-1] == ["git", "checkout", "-b", "agent5-selfheal/verify-btn"]


# ---- Idempotency: found during a bug-hunt review - a routine retry after
# a partial prior failure (push succeeded, PR creation didn't) used to
# fail outright with "branch already exists" instead of just working.

def test_checkout_branch_from_main_deletes_a_stale_local_branch_first(monkeypatch):
    calls = []
    monkeypatch.setattr(git_ops, "_run", lambda args, cwd: calls.append(args))
    monkeypatch.setattr(git_ops, "_branch_exists_locally", lambda repo_path, branch_name: True)

    git_ops.checkout_branch_from_main("/repo", "agent5-selfheal/verify-btn")

    assert calls[-2:] == [
        ["git", "branch", "-D", "agent5-selfheal/verify-btn"],
        ["git", "checkout", "-b", "agent5-selfheal/verify-btn"],
    ]


def test_open_pr_builds_gh_command_with_branch_as_head(monkeypatch):
    monkeypatch.setattr(git_ops, "GIT_PROVIDER", "github")
    captured = {}

    def fake_run(args, cwd):
        captured["args"] = args
        return "https://github.com/org/repo/pull/2"

    monkeypatch.setattr(git_ops, "_run", fake_run)

    url = git_ops.open_pr("/repo", "agent5-selfheal/verify-btn", "Title", "Body")

    assert url == "https://github.com/org/repo/pull/2"
    assert captured["args"][:3] == ["gh", "pr", "create"]
    assert "agent5-selfheal/verify-btn" in captured["args"]


def test_open_pr_builds_glab_command_when_provider_is_gitlab(monkeypatch):
    monkeypatch.setattr(git_ops, "GIT_PROVIDER", "gitlab")
    captured = {}

    def fake_run(args, cwd):
        captured["args"] = args
        return "https://gitlab.com/org/repo/-/merge_requests/2"

    monkeypatch.setattr(git_ops, "_run", fake_run)

    url = git_ops.open_pr("/repo", "agent5-selfheal/verify-btn", "Title", "Body")

    assert url == "https://gitlab.com/org/repo/-/merge_requests/2"
    assert captured["args"][:3] == ["glab", "mr", "create"]
    assert "--source-branch" in captured["args"] and "agent5-selfheal/verify-btn" in captured["args"]
