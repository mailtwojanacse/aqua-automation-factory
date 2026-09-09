import pytest

from src import git_ops


@pytest.mark.parametrize("text,expected", [
    ("Adobe Acrobat Reader DC", "adobe-acrobat-reader-dc"),
    ("Hello, World!! -- Test", "hello-world-test"),
])
def test_slugify_basic_cases(text, expected):
    assert git_ops.slugify(text) == expected


def test_slugify_empty_or_all_symbols_falls_back_to_change():
    assert git_ops.slugify("") == "change"
    assert git_ops.slugify("!!!???") == "change"


def test_slugify_truncates_to_max_len_without_trailing_dash():
    long_text = "word " * 20
    slug = git_ops.slugify(long_text, max_len=12)
    assert len(slug) <= 12
    assert not slug.endswith("-")


def test_run_returns_stripped_stdout_on_success(monkeypatch):
    class FakeResult:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    monkeypatch.setattr(git_ops.subprocess, "run", lambda *a, **k: FakeResult())
    assert git_ops._run(["git", "status"], cwd="/tmp") == "ok"


def test_run_raises_runtime_error_with_stderr_on_failure(monkeypatch):
    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "fatal: boom"

    monkeypatch.setattr(git_ops.subprocess, "run", lambda *a, **k: FakeResult())
    with pytest.raises(RuntimeError, match="boom"):
        git_ops._run(["git", "status"], cwd="/tmp")


def test_checkout_branch_from_main_runs_fetch_checkout_pull_then_new_branch(monkeypatch):
    calls = []
    monkeypatch.setattr(git_ops, "_run", lambda args, cwd: calls.append(args))

    git_ops.checkout_branch_from_main("/repo", "agent3/my-change")

    assert calls == [
        ["git", "fetch", "origin", "main"],
        ["git", "checkout", "main"],
        ["git", "pull", "origin", "main"],
        ["git", "checkout", "-b", "agent3/my-change"],
    ]


def test_commit_and_push_runs_add_commit_push_in_order(monkeypatch):
    calls = []
    monkeypatch.setattr(git_ops, "_run", lambda args, cwd: calls.append(args))

    git_ops.commit_and_push("/repo", ["tests/test_x.py"], "msg", "agent3/my-change")

    assert calls[0] == ["git", "add", "tests/test_x.py"]
    assert calls[1] == ["git", "commit", "-m", "msg"]
    assert calls[2] == ["git", "push", "-u", "origin", "agent3/my-change"]


def test_open_pr_builds_gh_command_with_title_body_branch_and_base(monkeypatch):
    captured = {}

    def fake_run(args, cwd):
        captured["args"] = args
        return "https://github.com/org/repo/pull/1"

    monkeypatch.setattr(git_ops, "_run", fake_run)

    url = git_ops.open_pr("/repo", "agent3/my-change", "Title", "Body")

    assert url == "https://github.com/org/repo/pull/1"
    assert captured["args"][:3] == ["gh", "pr", "create"]
    assert "agent3/my-change" in captured["args"]
    assert "main" in captured["args"]
