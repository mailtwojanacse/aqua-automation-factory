import json

import pytest

import reset_demo


# ---- open_prs: GIT_PROVIDER support - GitLab MRs are normalized to the
# same {number, title, headRefName, url} shape as GitHub PRs, so every
# downstream caller stays provider-agnostic.

def test_open_prs_builds_gh_command_on_github(monkeypatch):
    monkeypatch.setattr(reset_demo, "GIT_PROVIDER", "github")
    captured = {}

    def fake_run(cmd, cwd=None, check=True):
        captured["cmd"] = cmd
        return json.dumps([{"number": 1, "title": "T", "headRefName": "agent3/x", "url": "https://x"}])

    monkeypatch.setattr(reset_demo, "run", fake_run)

    prs = reset_demo.open_prs("/repo")

    assert captured["cmd"][:3] == ["gh", "pr", "list"]
    assert prs == [{"number": 1, "title": "T", "headRefName": "agent3/x", "url": "https://x"}]


def test_open_prs_builds_glab_command_and_normalizes_fields_on_gitlab(monkeypatch):
    monkeypatch.setattr(reset_demo, "GIT_PROVIDER", "gitlab")
    captured = {}

    def fake_run(cmd, cwd=None, check=True):
        captured["cmd"] = cmd
        return json.dumps([{"iid": 5, "title": "T", "source_branch": "agent3/x", "web_url": "https://gitlab/x"}])

    monkeypatch.setattr(reset_demo, "run", fake_run)

    prs = reset_demo.open_prs("/repo")

    assert captured["cmd"][:3] == ["glab", "mr", "list"]
    assert prs == [{"number": 5, "title": "T", "headRefName": "agent3/x", "url": "https://gitlab/x"}]


# ---- parse_branch_list ----

def test_parse_branch_list_drops_main_and_head_markers():
    raw = "main\nagent3/some-change\nagent5-selfheal/verify-btn\n"
    assert reset_demo.parse_branch_list(raw) == ["agent3/some-change", "agent5-selfheal/verify-btn"]


def test_parse_branch_list_strips_origin_prefix_when_asked():
    raw = "origin/main\norigin/HEAD -> origin/main\norigin/agent3/some-change\n"
    assert reset_demo.parse_branch_list(raw, strip_origin_prefix=True) == ["agent3/some-change"]


def test_parse_branch_list_keeps_origin_prefix_when_not_asked():
    raw = "origin/agent3/some-change\n"
    assert reset_demo.parse_branch_list(raw) == ["origin/agent3/some-change"]


def test_parse_branch_list_ignores_blank_lines():
    raw = "main\n\nagent3/some-change\n\n"
    assert reset_demo.parse_branch_list(raw) == ["agent3/some-change"]


def test_parse_branch_list_empty_input_returns_empty_list():
    assert reset_demo.parse_branch_list("") == []


# ---- split_branches_by_pr_protection ----

def test_split_branches_by_pr_protection_separates_stale_from_pr_backed():
    remotes = ["agent3/old-change", "agent5-selfheal/verify-btn", "agent3/in-progress"]
    open_pr_names = {"agent3/in-progress"}

    stale, kept = reset_demo.split_branches_by_pr_protection(remotes, open_pr_names)

    assert stale == ["agent3/old-change", "agent5-selfheal/verify-btn"]
    assert kept == ["agent3/in-progress"]


def test_split_branches_by_pr_protection_all_stale_when_no_open_prs():
    remotes = ["agent3/old-change", "agent5-selfheal/verify-btn"]
    stale, kept = reset_demo.split_branches_by_pr_protection(remotes, set())
    assert stale == remotes
    assert kept == []


def test_split_branches_by_pr_protection_all_kept_when_every_branch_has_an_open_pr():
    remotes = ["agent3/change-a", "agent3/change-b"]
    open_pr_names = {"agent3/change-a", "agent3/change-b"}
    stale, kept = reset_demo.split_branches_by_pr_protection(remotes, open_pr_names)
    assert stale == []
    assert kept == remotes


def test_split_branches_by_pr_protection_empty_remotes_returns_empty_lists():
    stale, kept = reset_demo.split_branches_by_pr_protection([], {"whatever"})
    assert stale == []
    assert kept == []


# ---- main()'s safety gates ----

def test_main_refuses_to_run_when_repo_dir_is_not_a_git_checkout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(reset_demo, "REPO_DIR", tmp_path)  # no .git here
    monkeypatch.setattr(reset_demo.sys, "argv", ["reset_demo.py"])

    with pytest.raises(SystemExit) as exc_info:
        reset_demo.main()

    assert exc_info.value.code == 1
    assert "not a git checkout" in capsys.readouterr().out


def test_main_refuses_to_run_with_uncommitted_changes(tmp_path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()  # just needs to exist for the first gate to pass
    monkeypatch.setattr(reset_demo, "REPO_DIR", tmp_path)
    monkeypatch.setattr(reset_demo, "working_tree_is_clean", lambda repo_dir: False)
    monkeypatch.setattr(reset_demo.sys, "argv", ["reset_demo.py"])

    with pytest.raises(SystemExit) as exc_info:
        reset_demo.main()

    assert exc_info.value.code == 1
    assert "uncommitted changes" in capsys.readouterr().out


# ---- Found during a bug-hunt review: the report at the top of main() used
# a single open_prs() snapshot to decide what's "stale," then deleted
# based on that same snapshot - a PR opened against a branch in between
# would get its head silently destroyed anyway. Fixed by re-checking right
# before the actual remote deletion.

def test_main_skips_a_remote_branch_that_gained_an_open_pr_since_the_report(tmp_path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(reset_demo, "REPO_DIR", tmp_path)
    monkeypatch.setattr(reset_demo, "working_tree_is_clean", lambda repo_dir: True)
    monkeypatch.setattr(reset_demo, "sync_main", lambda repo_dir: None)
    monkeypatch.setattr(reset_demo, "local_branches", lambda repo_dir: [])
    monkeypatch.setattr(reset_demo, "remote_branches", lambda repo_dir: ["agent3/stale-branch"])

    call_count = {"n": 0}

    def fake_open_prs(repo_dir):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return []  # report time: looked stale, no open PR yet
        return [{"number": 99, "title": "New PR", "headRefName": "agent3/stale-branch", "url": "https://x"}]

    monkeypatch.setattr(reset_demo, "open_prs", fake_open_prs)

    run_calls = []
    monkeypatch.setattr(reset_demo, "run", lambda cmd, cwd=None, check=True: run_calls.append(cmd) or "")
    monkeypatch.setattr(reset_demo.sys, "argv", ["reset_demo.py", "--yes"])

    reset_demo.main()

    assert call_count["n"] == 2  # report snapshot, then the pre-deletion re-check
    assert ["git", "push", "origin", "--delete", "agent3/stale-branch"] not in run_calls
    assert "skipped remote branch agent3/stale-branch" in capsys.readouterr().out


def test_main_still_deletes_a_remote_branch_that_stays_stale(tmp_path, monkeypatch, capsys):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(reset_demo, "REPO_DIR", tmp_path)
    monkeypatch.setattr(reset_demo, "working_tree_is_clean", lambda repo_dir: True)
    monkeypatch.setattr(reset_demo, "sync_main", lambda repo_dir: None)
    monkeypatch.setattr(reset_demo, "local_branches", lambda repo_dir: [])
    monkeypatch.setattr(reset_demo, "remote_branches", lambda repo_dir: ["agent3/stale-branch"])
    monkeypatch.setattr(reset_demo, "open_prs", lambda repo_dir: [])

    run_calls = []
    monkeypatch.setattr(reset_demo, "run", lambda cmd, cwd=None, check=True: run_calls.append(cmd) or "")
    monkeypatch.setattr(reset_demo.sys, "argv", ["reset_demo.py", "--yes"])

    reset_demo.main()

    assert ["git", "push", "origin", "--delete", "agent3/stale-branch"] in run_calls
