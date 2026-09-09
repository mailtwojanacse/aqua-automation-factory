"""Executes the automation script under pytest, captures evidence
(screenshot + log + a real Allure test-results report), and enforces the
folder allow-list rule from the client's slide: only scripts inside the
repo's `tests/` folder may run.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

ALLOWED_SUBDIR = "tests"


def check_allowed(repo_path, script_relpath):
    """Resolve script_relpath against repo_path and confirm it actually
    lands inside <repo_path>/tests/ - a plain string-prefix check (the
    original version of this function) is bypassable with '../' segments,
    e.g. 'tests/../../../etc/passwd' passes a startswith('tests/') test
    but resolves well outside the allowed folder."""
    normalized = str(script_relpath).replace("\\", "/")
    allowed_dir = (Path(repo_path) / ALLOWED_SUBDIR).resolve()
    candidate = (Path(repo_path) / normalized).resolve()
    try:
        candidate.relative_to(allowed_dir)
    except ValueError:
        raise PermissionError(
            f"Refusing to run '{script_relpath}': resolves to '{candidate}', which is "
            f"outside the allowed '{allowed_dir}' folder."
        )


def check_target_page_allowed(repo_path, target_page):
    """Same resolved-path containment check as check_allowed, for
    target_page - the dashboard's /run endpoint already validates this
    against a fixed allowlist, but the plain CLI (run_agent5.py) takes any
    string, and target_page flows straight into a file path for the
    screenshot/self-heal HTML fetch."""
    allowed_dir = (Path(repo_path) / "sample_app").resolve()
    candidate = (Path(repo_path) / "sample_app" / target_page).resolve()
    try:
        candidate.relative_to(allowed_dir)
    except ValueError:
        raise PermissionError(
            f"Refusing to use target_page '{target_page}': resolves to '{candidate}', "
            f"which is outside the allowed '{allowed_dir}' folder."
        )


def _python_for(repo_path):
    """Prefer the repo's own venv (has allure-pytest installed, per its
    requirements.txt) so Allure results get written; fall back to the bare
    system python otherwise - runs still work, just without Allure output
    for that run."""
    venv_python = Path(repo_path) / ".venv" / "bin" / "python3"
    return str(venv_python) if venv_python.exists() else "python3"


def run_pytest(repo_path, script_relpath, target_page, log_path, allure_results_dir=None):
    env = os.environ.copy()
    env["TARGET_PAGE"] = target_page
    cmd = [_python_for(repo_path), "-m", "pytest", script_relpath, "-v"]
    if allure_results_dir is not None:
        # Don't clear previous result files here: Agent 5 runs one script
        # at a time, so clearing on every invocation would make the report
        # only ever reflect the most-recently-run script instead of the
        # combined suite. Leaving old result files in place lets results
        # accumulate across both suites; Allure groups multiple result
        # files for the same test (matched by historyId) as retries and
        # counts only the latest toward pass/fail, so re-running the same
        # script repeatedly doesn't inflate totals either.
        allure_results_dir = Path(allure_results_dir)
        allure_results_dir.mkdir(parents=True, exist_ok=True)
        cmd.append(f"--alluredir={allure_results_dir}")
    result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, env=env)
    log_text = f"$ TARGET_PAGE={target_page} {' '.join(cmd)}\n\n{result.stdout}\n{result.stderr}"
    Path(log_path).write_text(log_text, encoding="utf-8")
    return result.returncode == 0, log_text


def generate_allure_report(results_dir, report_dir):
    """Regenerate the real Allure HTML report from the JSON results this
    run just wrote. Carries the previous report's history/ folder forward
    first - the standard Allure idiom for the Trend chart to show multiple
    runs instead of resetting every time. Returns the report directory, or
    None if the `allure` CLI isn't on PATH (report step is best-effort;
    pytest/screenshot/self-heal all already succeeded regardless)."""
    if shutil.which("allure") is None:
        return None

    results_dir = Path(results_dir)
    report_dir = Path(report_dir)
    old_history = report_dir / "history"
    if old_history.exists():
        shutil.copytree(old_history, results_dir / "history", dirs_exist_ok=True)

    subprocess.run(
        ["allure", "generate", str(results_dir), "-o", str(report_dir), "--clean"],
        capture_output=True, text=True,
    )
    return report_dir


def capture_screenshot(repo_path, target_page, screenshot_path):
    """Best-effort evidence screenshot of the target page's end state.
    Runs independently of the pytest process so a pytest failure doesn't
    prevent us from having visual evidence of what the page looked like.
    """
    from playwright.sync_api import sync_playwright

    page_path = Path(repo_path) / "sample_app" / target_page
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(page_path.as_uri())
        for selector in ("#verify-btn", "#confirm-install-btn"):
            try:
                page.locator(selector).click(timeout=2000)
                break
            except Exception:
                continue
        page.screenshot(path=str(screenshot_path))
        browser.close()


def detect_broken_locator(log_text):
    """If the failure is a Playwright locator timeout, return the broken
    selector string; otherwise None (some other kind of failure)."""
    if "TimeoutError" not in log_text:
        return None
    match = re.search(r'waiting for locator\("([^"]+)"\)', log_text)
    return match.group(1) if match else None
