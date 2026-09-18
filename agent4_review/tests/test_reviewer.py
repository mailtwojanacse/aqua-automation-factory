from unittest import mock

import pytest

from src import reviewer
from src.reviewer import format_review_body, parse_verdict_json, review_pr


def test_parse_verdict_json_plain():
    assert parse_verdict_json('{"verdict": "approve"}') == {"verdict": "approve"}


def test_parse_verdict_json_strips_labeled_code_fence():
    text = '```json\n{"verdict": "approve"}\n```'
    assert parse_verdict_json(text) == {"verdict": "approve"}


def test_parse_verdict_json_strips_bare_code_fence():
    text = '```\n{"verdict": "request_changes"}\n```'
    assert parse_verdict_json(text) == {"verdict": "request_changes"}


def test_format_review_body_includes_findings_and_footer():
    body = format_review_body("Looks fine overall.", [
        {"concern": "security", "detail": "No secrets committed."},
    ])

    assert body.startswith("Looks fine overall.")
    assert "**Findings:**" in body
    assert "**security:** No secrets committed." in body
    assert "Posted automatically by Agent 4" in body


def test_format_review_body_without_comments_skips_findings_section():
    body = format_review_body("All good.", [])

    assert "**Findings:**" not in body
    assert "Posted automatically by Agent 4" in body


def test_format_review_body_defaults_missing_concern_and_detail():
    body = format_review_body("Summary", [{}])

    assert "**note:** " in body


def test_format_review_body_renders_a_plain_string_comment_instead_of_crashing():
    # Found during a bug-hunt review: the AI returning ["fix the timeout"]
    # instead of [{"concern": ..., "detail": ...}] used to raise
    # AttributeError - after the GitHub identity had already been switched
    # to the reviewer account.
    body = format_review_body("Summary", ["fix the timeout"])

    assert "**note:** fix the timeout" in body


# ---- _switch_account / review_pr's account-switch handling: found during a
# bug-hunt review - the switch's exit code used to be discarded entirely, so
# a failed switch (bad account, never `gh auth login`'d) looked identical to
# a successful one, silently leaving `gh` authenticated as the wrong
# identity for every subsequent agent run.

def test_switch_account_raises_when_gh_reports_failure():
    fake_result = mock.Mock(returncode=1, stderr="no such user")
    with mock.patch("src.reviewer.subprocess.run", return_value=fake_result):
        with pytest.raises(RuntimeError, match="gh auth switch"):
            reviewer._switch_account("nonexistent-user")


def test_switch_account_succeeds_silently_when_gh_succeeds():
    fake_result = mock.Mock(returncode=0, stderr="")
    with mock.patch("src.reviewer.subprocess.run", return_value=fake_result):
        reviewer._switch_account("some-user")  # does not raise


def test_review_pr_raises_and_logs_loudly_when_switching_back_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(reviewer, "GIT_PROVIDER", "github")
    switch_calls = []

    def fake_switch(username):
        switch_calls.append(username)
        if len(switch_calls) == 2:
            raise RuntimeError(f"gh auth switch --user {username} failed:\nboom")

    emitted = []

    with mock.patch("src.reviewer._switch_account", side_effect=fake_switch), \
         mock.patch("src.reviewer.get_pr", return_value=("title", "body", "diff")), \
         mock.patch("src.reviewer.prompt_builder.build_prompt", return_value=("sys", "user")), \
         mock.patch("src.reviewer.llm_client.generate",
                    return_value='{"verdict": "approve", "summary": "ok", "comments": []}'), \
         mock.patch("src.reviewer.post_review", return_value="posted"), \
         mock.patch("src.reviewer.events.emit", side_effect=lambda *a, **k: emitted.append(a)):
        with pytest.raises(RuntimeError, match="failed"):
            review_pr("/fake/repo", 42, str(tmp_path))

    assert switch_calls == [reviewer.REVIEWER_ACCOUNT, reviewer.PR_AUTHOR_ACCOUNT]
    assert any("left authenticated as" in str(call) for call in emitted)


# ---- GitLab support: glab has no `gh auth switch` equivalent, so the
# reviewer identity is applied per-call via a GITLAB_TOKEN env override
# instead of global CLI state - no switch/switch-back at all.

def test_get_pr_builds_glab_command_and_maps_description_to_body(monkeypatch):
    monkeypatch.setattr(reviewer, "GIT_PROVIDER", "gitlab")
    monkeypatch.setattr(reviewer, "GITLAB_REVIEWER_TOKEN", "reviewer-token")
    captured = []

    def fake_run(args, cwd, env_overrides=None):
        captured.append((args, env_overrides))
        if args[:3] == ["glab", "mr", "view"]:
            return '{"title": "My MR", "description": "MR body text"}'
        return "diff --git a/x b/x"

    with mock.patch.object(reviewer, "_run", side_effect=fake_run):
        title, body, diff = reviewer.get_pr("/repo", 7)

    assert title == "My MR"
    assert body == "MR body text"
    assert diff == "diff --git a/x b/x"
    assert captured[0][0][:3] == ["glab", "mr", "view"]
    assert captured[0][1] == {"GITLAB_TOKEN": "reviewer-token"}


def test_post_review_approve_posts_a_note_and_approves_on_gitlab(monkeypatch):
    monkeypatch.setattr(reviewer, "GIT_PROVIDER", "gitlab")
    monkeypatch.setattr(reviewer, "GITLAB_REVIEWER_TOKEN", "reviewer-token")
    captured_args = []

    def fake_run(args, cwd, env_overrides=None):
        captured_args.append(args)
        return "ok"

    with mock.patch.object(reviewer, "_run", side_effect=fake_run):
        reviewer.post_review("/repo", 7, "approve", "Looks good")

    assert len(captured_args) == 2
    assert captured_args[0][:3] == ["glab", "mr", "note"]
    assert captured_args[1][:3] == ["glab", "mr", "approve"]


def test_post_review_request_changes_only_posts_a_note_on_gitlab_not_approve(monkeypatch):
    # GitLab has no native "request changes" - a request_changes verdict
    # must never call glab mr approve.
    monkeypatch.setattr(reviewer, "GIT_PROVIDER", "gitlab")
    captured_args = []

    def fake_run(args, cwd, env_overrides=None):
        captured_args.append(args)
        return "ok"

    with mock.patch.object(reviewer, "_run", side_effect=fake_run):
        reviewer.post_review("/repo", 7, "request_changes", "Needs work")

    assert len(captured_args) == 1
    assert captured_args[0][:3] == ["glab", "mr", "note"]


def test_review_pr_never_switches_accounts_on_gitlab(tmp_path, monkeypatch):
    monkeypatch.setattr(reviewer, "GIT_PROVIDER", "gitlab")
    switch_calls = []

    with mock.patch("src.reviewer._switch_account", side_effect=lambda u: switch_calls.append(u)), \
         mock.patch("src.reviewer.get_pr", return_value=("title", "body", "diff")), \
         mock.patch("src.reviewer.prompt_builder.build_prompt", return_value=("sys", "user")), \
         mock.patch("src.reviewer.llm_client.generate",
                    return_value='{"verdict": "approve", "summary": "ok", "comments": []}'), \
         mock.patch("src.reviewer.post_review", return_value="posted"), \
         mock.patch("src.reviewer.events.emit"):
        result = review_pr("/fake/repo", 7, str(tmp_path))

    assert switch_calls == []
    assert result["verdict"] == "approve"
