import pytest

import server

REQUIRED_JOB_KEYS = {"label", "agent1", "script", "requirement", "target_pages"}
REQUIRED_AGENT1_KEYS = {"bds", "xml_config", "job_config"}


def test_load_jobs_returns_the_known_demo_jobs():
    jobs = server._load_jobs()
    assert set(jobs) == {"adobe_acrobat", "7zip"}


def test_every_job_has_the_required_shape():
    jobs = server._load_jobs()
    for name, job in jobs.items():
        assert REQUIRED_JOB_KEYS.issubset(job), name
        assert REQUIRED_AGENT1_KEYS.issubset(job["agent1"]), name
        assert set(job["target_pages"]) == {"v1", "v2"}, name


def test_every_job_references_agent_files_that_actually_exist():
    """Regression guard: jobs.json is hand-maintained data, not generated -
    a typo'd path here would silently break that job's dashboard run. Only
    checks paths inside this repo (agent1's inputs, agent3's requirement
    docs) - automation_target is a separate, gitignored repo that isn't
    guaranteed to be checked out here (e.g. in CI)."""
    agent1_dir = server.ROOT.parent / "agent1_baramundi_doc"
    agent3_dir = server.ROOT.parent / "agent3_script_adaptation"

    for name, job in server._load_jobs().items():
        for key in ("bds", "xml_config", "job_config"):
            assert (agent1_dir / job["agent1"][key]).is_file(), f"{name}.agent1.{key}"
        assert (agent3_dir / job["requirement"]).is_file(), f"{name}.requirement"


def test_every_job_references_automation_target_files_that_actually_exist():
    """Same regression guard, for the paths that live in automation_target -
    skipped when that sibling repo isn't checked out (it's independent and
    gitignored here), since there's nothing to verify against in that case."""
    repo_dir = server.ROOT.parent / "automation_target"
    if not repo_dir.is_dir():
        pytest.skip("automation_target isn't checked out here (expected in CI)")

    for name, job in server._load_jobs().items():
        assert (repo_dir / job["script"]).is_file(), f"{name}.script"
        for page_key, filename in job["target_pages"].items():
            assert (repo_dir / "sample_app" / filename).is_file(), f"{name}.target_pages.{page_key}"
