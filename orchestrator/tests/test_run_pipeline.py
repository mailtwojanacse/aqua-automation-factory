from unittest import mock

import run_pipeline

# ---- extract_pr_number: works for both a GitHub PR URL and a GitLab MR
# URL - the URL's own shape disambiguates which one it is.


def test_extract_pr_number_from_a_github_pull_url():
    assert run_pipeline.extract_pr_number("https://github.com/org/repo/pull/42") == 42


def test_extract_pr_number_from_a_gitlab_merge_request_url():
    assert run_pipeline.extract_pr_number("https://gitlab.com/group/project/-/merge_requests/7") == 7


def test_extract_pr_number_returns_none_for_an_unrecognized_url():
    assert run_pipeline.extract_pr_number("https://example.com/not-a-pr") is None


# ---- merge_pr: GIT_PROVIDER selects gh vs glab, same pattern as
# git_ops.py's open_pr in each agent.

def test_merge_pr_uses_gh_by_default(monkeypatch):
    monkeypatch.setattr(run_pipeline, "GIT_PROVIDER", "github")
    with mock.patch.object(run_pipeline.subprocess, "run") as mock_run:
        run_pipeline.merge_pr(42)

    args = mock_run.call_args.args[0]
    assert args[:3] == ["gh", "pr", "merge"]
    assert "--delete-branch" in args


def test_merge_pr_uses_glab_when_provider_is_gitlab(monkeypatch):
    monkeypatch.setattr(run_pipeline, "GIT_PROVIDER", "gitlab")
    with mock.patch.object(run_pipeline.subprocess, "run") as mock_run:
        run_pipeline.merge_pr(7)

    args = mock_run.call_args.args[0]
    assert args[:3] == ["glab", "mr", "merge"]
    assert "--remove-source-branch" in args
    assert "--auto-merge=false" in args  # merge immediately, don't wait on a pipeline
