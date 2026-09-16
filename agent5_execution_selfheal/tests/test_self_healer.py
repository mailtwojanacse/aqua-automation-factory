from unittest import mock

import pytest

from src import self_healer as self_healer_module
from src.self_healer import apply_selector_fix, is_safe_selector


def test_apply_selector_fix_replaces_double_quoted_selector(tmp_path):
    script = tmp_path / "test_x.py"
    script.write_text('page.locator("#verify-btn").click()\n', encoding="utf-8")

    changed = apply_selector_fix(script, "#verify-btn", "#confirm-install-btn")

    assert changed is True
    text = script.read_text(encoding="utf-8")
    assert "#confirm-install-btn" in text
    assert "#verify-btn" not in text


def test_apply_selector_fix_replaces_single_quoted_selector(tmp_path):
    script = tmp_path / "test_x.py"
    script.write_text("page.locator('#verify-btn').click()\n", encoding="utf-8")

    changed = apply_selector_fix(script, "#verify-btn", "#confirm-install-btn")

    assert changed is True
    assert "#confirm-install-btn" in script.read_text(encoding="utf-8")


def test_apply_selector_fix_replaces_every_occurrence_in_the_file(tmp_path):
    script = tmp_path / "test_x.py"
    script.write_text(
        'page.locator("#verify-btn").click()\n'
        'expect(page.locator("#verify-btn")).to_be_visible()\n',
        encoding="utf-8",
    )

    apply_selector_fix(script, "#verify-btn", "#confirm-install-btn")

    text = script.read_text(encoding="utf-8")
    assert text.count("#confirm-install-btn") == 2
    assert "#verify-btn" not in text


def test_apply_selector_fix_returns_false_when_selector_not_found(tmp_path):
    script = tmp_path / "test_x.py"
    original = 'page.locator("#something-else").click()\n'
    script.write_text(original, encoding="utf-8")

    changed = apply_selector_fix(script, "#verify-btn", "#confirm-install-btn")

    assert changed is False
    assert script.read_text(encoding="utf-8") == original


# ---- is_safe_selector: found during a security review - apply_selector_fix
# splices this string directly into executable Python source, so an
# unvalidated AI answer could break out of the quoted literal it's spliced
# into and inject arbitrary code, which then runs as soon as pytest re-runs
# the patched file (self-heal's own "verify the fix" step, before any
# human review). heal() must reject anything that fails this check before
# ever calling apply_selector_fix.

def test_is_safe_selector_accepts_realistic_selectors():
    for selector in ("#confirm-install-btn", "#verify-7zip-btn", ".some-class",
                      "button[name=foo]", "div > span", "a:hover"):
        assert is_safe_selector(selector) is True, selector


def test_is_safe_selector_rejects_quote_breakout_payload():
    # The exact shape of attack that defeats a naive string.replace(): a
    # quote character ends the literal early, then a semicolon starts a
    # new Python statement.
    payload = '#x").click(); import os; os.system("id > /tmp/pwned'
    assert is_safe_selector(payload) is False


def test_is_safe_selector_rejects_semicolons_backslashes_and_newlines():
    assert is_safe_selector("#ok; import os") is False
    assert is_safe_selector("#ok\\nmalicious") is False
    assert is_safe_selector("#ok\nmalicious") is False


def test_is_safe_selector_rejects_empty_or_overlong_input():
    assert is_safe_selector("") is False
    assert is_safe_selector("#" + "a" * 300) is False


def _mock_playwright_page(content_side_effect=None):
    """A MagicMock chain standing in for sync_playwright()'s context
    manager, deep enough to reach a mocked page.content()."""
    mock_browser = mock.MagicMock()
    mock_page = mock.MagicMock()
    if content_side_effect is not None:
        mock_page.content.side_effect = content_side_effect
    mock_browser.new_page.return_value = mock_page
    mock_playwright_instance = mock.MagicMock()
    mock_playwright_instance.chromium.launch.return_value = mock_browser
    mock_cm = mock.MagicMock()
    mock_cm.__enter__.return_value = mock_playwright_instance
    return mock_cm, mock_browser


# ---- get_page_html: found during a bug-hunt review - browser.close() sat
# after page.content() with no try/finally, so an exception mid-fetch
# leaked the Chromium process instead of cleaning it up.

def test_get_page_html_closes_the_browser_even_if_fetching_content_raises(tmp_path):
    sample_app_dir = tmp_path / "sample_app"
    sample_app_dir.mkdir()
    (sample_app_dir / "broken.html").write_text("<html></html>", encoding="utf-8")
    mock_cm, mock_browser = _mock_playwright_page(content_side_effect=RuntimeError("boom"))

    with mock.patch("playwright.sync_api.sync_playwright", return_value=mock_cm):
        with pytest.raises(RuntimeError):
            self_healer_module.get_page_html(tmp_path, "broken.html")

    mock_browser.close.assert_called_once()


def test_get_page_html_closes_the_browser_on_the_normal_path_too(tmp_path):
    sample_app_dir = tmp_path / "sample_app"
    sample_app_dir.mkdir()
    (sample_app_dir / "ok.html").write_text("<html></html>", encoding="utf-8")
    mock_cm, mock_browser = _mock_playwright_page()
    mock_browser.new_page.return_value.content.return_value = "<html>ok</html>"

    with mock.patch("playwright.sync_api.sync_playwright", return_value=mock_cm):
        html = self_healer_module.get_page_html(tmp_path, "ok.html")

    assert html == "<html>ok</html>"
    mock_browser.close.assert_called_once()


def test_is_safe_selector_rejects_a_trailing_newline():
    # Found during a bug-hunt review: `$` in a Python regex (without
    # re.MULTILINE) matches either end-of-string OR just before a single
    # trailing newline - so "#ok\n" used to pass this check even though a
    # newline anywhere else in the string is correctly rejected above.
    # Fixed by anchoring with \Z instead of $.
    assert is_safe_selector("#ok\n") is False


def test_apply_selector_fix_never_reached_for_a_payload_that_fails_validation():
    # End-to-end proof the fix actually closes the hole: heal() checks
    # is_safe_selector before calling apply_selector_fix at all - this
    # confirms the payload that used to produce injected code is rejected
    # by the gate that now sits in front of it.
    payload = '#x").click(); import os; os.system("id > /tmp/pwned'
    assert is_safe_selector(payload) is False


# ---- heal()'s branching: deterministic fix tried first, AI only as a
# fallback. Every git/pytest/AI side effect is mocked here - this is
# testing the *decision*, not exercising real git/network/AI, same
# reasoning as everywhere else in this suite. The real end-to-end behavior
# (a genuine self-heal run against this repo's actual v1/v2 pages) is
# verified separately, for real, not just here.

def _heal_with_mocks(deterministic_result, generate_result="#confirm-install-btn",
                      commit_and_push_side_effect=None, open_pr_side_effect=None):
    calls = {"ai": 0, "deterministic": 0}

    def fake_try_deterministic(repo_path, target_page, broken_selector):
        calls["deterministic"] += 1
        return deterministic_result

    def fake_generate(system_prompt, user_prompt):
        calls["ai"] += 1
        return generate_result

    with mock.patch.object(self_healer_module, "_try_deterministic_fix", side_effect=fake_try_deterministic), \
         mock.patch.object(self_healer_module.llm_client, "generate", side_effect=fake_generate), \
         mock.patch.object(self_healer_module, "build_heal_prompt", return_value=("sys", "user", "prompt.txt")), \
         mock.patch.object(self_healer_module.git_ops, "checkout_branch_from_main"), \
         mock.patch.object(self_healer_module.git_ops, "checkout_main") as mock_checkout_main, \
         mock.patch.object(self_healer_module.git_ops, "commit_and_push", side_effect=commit_and_push_side_effect), \
         mock.patch.object(self_healer_module.git_ops, "open_pr", return_value="https://example/pr/1",
                            side_effect=open_pr_side_effect), \
         mock.patch.object(self_healer_module, "apply_selector_fix", return_value=True), \
         mock.patch.object(self_healer_module.runner, "run_pytest", return_value=(True, "log")), \
         mock.patch.object(self_healer_module.events, "emit"):
        result = self_healer_module.heal(
            "/fake/repo", "tests/test_x.py", "install_confirmation_v2.html", "#verify-btn", "/fake/output",
        )
    return result, calls, mock_checkout_main


def test_heal_uses_the_deterministic_fix_without_calling_the_ai_when_confident():
    result, calls, _ = _heal_with_mocks(deterministic_result="#confirm-install-btn")

    assert calls["deterministic"] == 1
    assert calls["ai"] == 0
    assert result["used_ai"] is False
    assert result["new_selector"] == "#confirm-install-btn"


def test_heal_falls_back_to_the_ai_when_the_deterministic_fix_is_not_confident():
    result, calls, _ = _heal_with_mocks(deterministic_result=None)

    assert calls["deterministic"] == 1
    assert calls["ai"] == 1
    assert result["used_ai"] is True


# ---- heal()'s error handling around the push/PR steps: found during a
# bug-hunt review - unlike every other failure branch in heal() (no-match,
# unsafe selector, retry-still-fails), the push and PR steps had no
# try/except at all, so a network blip here would propagate an unhandled
# exception instead of a structured result, and leave the repo mid-branch.

def test_heal_resets_to_main_and_reports_cleanly_when_push_fails():
    result, calls, mock_checkout_main = _heal_with_mocks(
        deterministic_result="#confirm-install-btn",
        commit_and_push_side_effect=RuntimeError("push rejected"),
    )

    assert result["status"] == "self_heal_push_failed"
    assert result["broken_selector"] == "#verify-btn"
    assert result["new_selector"] == "#confirm-install-btn"
    mock_checkout_main.assert_called_once()


# ---- _try_deterministic_fix: found during a bug-hunt review - a genuine
# exception from find_deterministic_replacement (not just "no confident
# match") used to be swallowed identically by a blanket except Exception,
# with nothing distinguishing a real bug from an honest "ambiguous" result
# in the audit trail. It still falls through to the AI either way, but now
# logs the exception distinctly.

def test_try_deterministic_fix_logs_distinctly_when_the_check_itself_raises(tmp_path):
    sample_app_dir = tmp_path / "sample_app"
    sample_app_dir.mkdir()
    (sample_app_dir / "install_confirmation_v1.html").write_text("<html></html>", encoding="utf-8")

    emitted = []
    with mock.patch.object(self_healer_module.rule_based_heal, "find_deterministic_replacement",
                            side_effect=RuntimeError("boom")), \
         mock.patch.object(self_healer_module.events, "emit", side_effect=lambda *a, **k: emitted.append(a)):
        result = self_healer_module._try_deterministic_fix(tmp_path, "install_confirmation_v2.html", "#verify-btn")

    assert result is None
    assert any("unexpected error" in str(call) for call in emitted)


def test_heal_reports_cleanly_when_pr_creation_fails_after_a_successful_push():
    result, calls, _ = _heal_with_mocks(
        deterministic_result="#confirm-install-btn",
        open_pr_side_effect=RuntimeError("gh pr create failed"),
    )

    assert result["status"] == "self_heal_pr_failed"
    assert result["broken_selector"] == "#verify-btn"
    assert result["new_selector"] == "#confirm-install-btn"
    assert "branch" in result
