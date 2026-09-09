import pytest

from src import runner


def test_check_allowed_passes_for_tests_prefixed_path(tmp_path):
    runner.check_allowed(tmp_path, "tests/test_install_verification.py")  # should not raise


def test_check_allowed_rejects_path_outside_tests(tmp_path):
    with pytest.raises(PermissionError):
        runner.check_allowed(tmp_path, "scripts/dangerous.py")


def test_check_allowed_normalizes_windows_style_separators(tmp_path):
    runner.check_allowed(tmp_path, "tests\\test_x.py")  # should not raise


def test_check_allowed_rejects_path_traversal_disguised_as_tests_prefix(tmp_path):
    """Regression guard: a plain startswith('tests/') check is bypassable
    with '../' segments - 'tests/../../../etc/passwd' passes that check
    but resolves well outside the allowed folder. Found during a security
    review; check_allowed must resolve the path and verify containment."""
    with pytest.raises(PermissionError):
        runner.check_allowed(tmp_path, "tests/../../../../etc/passwd")


def test_check_allowed_rejects_traversal_with_no_dotdot_left_over_in_string(tmp_path):
    # A sneakier variant: the '..' segments cancel out textually-adjacent
    # 'tests' components too, so this doesn't even superficially "look"
    # like it's escaping - only resolving the real path catches it.
    with pytest.raises(PermissionError):
        runner.check_allowed(tmp_path, "tests/../outside/evil.py")


def test_check_target_page_allowed_passes_for_sample_app_page(tmp_path):
    runner.check_target_page_allowed(tmp_path, "install_confirmation_v1.html")  # should not raise


def test_check_target_page_allowed_rejects_path_traversal(tmp_path):
    with pytest.raises(PermissionError):
        runner.check_target_page_allowed(tmp_path, "../../../../etc/passwd")


def test_python_for_prefers_repo_venv_when_present(tmp_path):
    venv_python = tmp_path / ".venv" / "bin" / "python3"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")

    assert runner._python_for(tmp_path) == str(venv_python)


def test_python_for_falls_back_to_system_python_without_venv(tmp_path):
    assert runner._python_for(tmp_path) == "python3"


def test_detect_broken_locator_extracts_selector_from_timeout_log():
    log = ('playwright._impl._errors.TimeoutError: Timeout 5000ms exceeded '
           'while waiting for locator("#verify-btn") to be visible')
    assert runner.detect_broken_locator(log) == "#verify-btn"


def test_detect_broken_locator_returns_none_without_timeout_error():
    log = "AssertionError: assert 'Verified' == 'Not Verified'"
    assert runner.detect_broken_locator(log) is None


def test_detect_broken_locator_returns_none_when_timeout_has_no_locator_pattern():
    log = "TimeoutError: some other kind of timeout with no locator mentioned"
    assert runner.detect_broken_locator(log) is None


def test_run_pytest_passes_through_pytest_returncode(tmp_path, monkeypatch):
    class FakeResult:
        returncode = 0
        stdout = "5 passed"
        stderr = ""

    monkeypatch.setattr(runner.subprocess, "run", lambda cmd, **kwargs: FakeResult())

    passed, log_text = runner.run_pytest(
        tmp_path, "tests/test_x.py", "v1.html", tmp_path / "pytest.log",
    )

    assert passed is True
    assert "5 passed" in log_text


def test_run_pytest_adds_alluredir_flag_when_results_dir_given(tmp_path, monkeypatch):
    captured = {}

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeResult()

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    results_dir = tmp_path / "allure-results"
    runner.run_pytest(
        tmp_path, "tests/test_x.py", "v1.html", tmp_path / "pytest.log",
        allure_results_dir=results_dir,
    )

    assert any(part.startswith("--alluredir=") and str(results_dir) in part for part in captured["cmd"])
    assert results_dir.exists()


def test_run_pytest_does_not_clear_preexisting_allure_results(tmp_path, monkeypatch):
    """Regression guard: Agent 5 runs one script at a time. Wiping
    allure-results/ on every invocation would make the report only ever
    reflect the most-recently-run script instead of accumulating results
    from both suites (the bug found and fixed while growing the test
    suite - see runner.run_pytest's docstring/comment)."""
    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(runner.subprocess, "run", lambda cmd, **kwargs: FakeResult())

    results_dir = tmp_path / "allure-results"
    results_dir.mkdir()
    preexisting = results_dir / "previous-run-result.json"
    preexisting.write_text("{}", encoding="utf-8")

    runner.run_pytest(
        tmp_path, "tests/test_x.py", "v1.html", tmp_path / "pytest.log",
        allure_results_dir=results_dir,
    )

    assert preexisting.exists()


def test_generate_allure_report_returns_none_when_allure_cli_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    assert runner.generate_allure_report(tmp_path / "results", tmp_path / "report") is None


def test_generate_allure_report_copies_forward_previous_history(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/allure")
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: None)

    results_dir = tmp_path / "allure-results"
    results_dir.mkdir()
    report_dir = tmp_path / "allure-report"
    old_history = report_dir / "history"
    old_history.mkdir(parents=True)
    (old_history / "history-trend.json").write_text("[]", encoding="utf-8")

    returned_dir = runner.generate_allure_report(results_dir, report_dir)

    assert returned_dir == report_dir
    assert (results_dir / "history" / "history-trend.json").exists()
