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


def test_review_pr_raises_and_logs_loudly_when_switching_back_fails(tmp_path):
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
