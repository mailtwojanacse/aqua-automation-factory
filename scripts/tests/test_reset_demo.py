import pytest

import reset_demo


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
