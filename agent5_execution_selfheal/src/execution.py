"""Orchestrates Agent 5: run the automation script -> capture evidence ->
on a broken-locator failure, self-heal (or write the heal prompt in
--dry-run) -> report the outcome."""
import importlib.util
from pathlib import Path

from src import events, git_ops, runner, self_healer

AGENT = "Agent 5"

# Fixed location (not the variable --output-dir) so the Allure report's
# history/ carries forward correctly across every invocation regardless of
# which --output-dir a given run used, and so the dashboard can serve it
# from one stable path.
AGENT5_DIR = Path(__file__).resolve().parents[1]
ALLURE_RESULTS_DIR = AGENT5_DIR / "allure-results"
ALLURE_REPORT_DIR = AGENT5_DIR / "allure-report"
TRACEABILITY_DIR = AGENT5_DIR.parent / "traceability"


def _refresh_traceability_report():
    """Rebuild the requirement -> test -> PR -> result report so it reflects
    this run. Loaded by file path (not a package import) since traceability/
    lives outside this agent's own src/ tree."""
    spec = importlib.util.spec_from_file_location(
        "traceability_build_report", str(TRACEABILITY_DIR / "build_report.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_report()


def execute(*args, **kwargs):
    try:
        return _execute(*args, **kwargs)
    except Exception as exc:
        events.emit(AGENT, "error", f"Failed: {exc}")
        raise


def _execute(repo_path, script_relpath, target_page, output_dir, dry_run=False):
    events.emit(AGENT, "start", f"Starting run against {target_page}",
                {"script": script_relpath, "target_page": target_page})

    runner.check_allowed(repo_path, script_relpath)
    runner.check_target_page_allowed(repo_path, target_page)
    events.emit(AGENT, "mechanical", f"Allow-list check passed - {script_relpath} is under tests/")

    repo_path = Path(repo_path).resolve()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Always start from a clean checkout of main - a prior agent run may
    # have left the repo on a feature branch.
    git_ops.checkout_main(repo_path)
    events.emit(AGENT, "mechanical", "Checked out a clean main branch")

    log_path = output_dir / "pytest.log"
    passed, log_text = runner.run_pytest(
        repo_path, script_relpath, target_page, log_path, allure_results_dir=ALLURE_RESULTS_DIR,
    )
    events.emit(AGENT, "mechanical", f"Ran pytest against {target_page}: {'PASSED' if passed else 'FAILED'}")

    report_dir = runner.generate_allure_report(ALLURE_RESULTS_DIR, ALLURE_REPORT_DIR)
    if report_dir:
        events.emit(AGENT, "mechanical", "Generated Allure test-results report",
                    {"report": str(report_dir / "index.html")})

    try:
        _refresh_traceability_report()
        events.emit(AGENT, "mechanical", "Refreshed the requirement traceability report",
                    {"report": str(TRACEABILITY_DIR / "index.html")})
    except Exception as exc:
        # Best-effort, same reasoning as the Allure step above - a stale
        # traceability report shouldn't block reporting the actual test run.
        events.emit(AGENT, "mechanical", f"Traceability report refresh skipped: {exc}")

    screenshot_path = output_dir / f"screenshot_{Path(target_page).stem}.png"
    try:
        runner.capture_screenshot(repo_path, target_page, screenshot_path)
        screenshot_result = str(screenshot_path)
        events.emit(AGENT, "mechanical", f"Captured evidence screenshot: {screenshot_path.name}")
    except Exception as exc:
        screenshot_result = f"screenshot capture failed: {exc}"
        events.emit(AGENT, "mechanical", f"Screenshot capture failed: {exc}")

    if passed:
        events.emit(AGENT, "done", "Finished - test passed, no self-heal needed", {"log": str(log_path)})
        return {"status": "passed", "log": str(log_path), "screenshot": screenshot_result}

    broken_selector = runner.detect_broken_locator(log_text)
    if not broken_selector:
        events.emit(AGENT, "error", "Test failed for a non-locator reason - reporting for human investigation")
        events.emit(AGENT, "done", "Finished with a failure")
        return {
            "status": "failed",
            "reason": "non-locator failure, see log",
            "log": str(log_path),
            "screenshot": screenshot_result,
        }

    events.emit(AGENT, "mechanical", f"Detected a broken locator: {broken_selector}", {"broken_selector": broken_selector})

    if dry_run:
        _, _, prompt_path = self_healer.build_heal_prompt(repo_path, target_page, broken_selector, output_dir)
        events.emit(AGENT, "ai_dry_run", "Dry-run: skipped the self-heal AI call, wrote the exact prompt instead",
                    {"path": str(prompt_path)})
        events.emit(AGENT, "done", "Finished (dry-run, self-heal not attempted)")
        return {
            "status": "failed_self_heal_dry_run",
            "broken_selector": broken_selector,
            "self_heal_prompt": str(prompt_path),
            "log": str(log_path),
            "screenshot": screenshot_result,
        }

    heal_result = self_healer.heal(repo_path, script_relpath, target_page, broken_selector, output_dir)
    heal_result["log"] = str(log_path)
    heal_result["screenshot"] = screenshot_result
    events.emit(AGENT, "done", f"Finished: {heal_result.get('status')}", heal_result)
    return heal_result
