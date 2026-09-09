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


def test_apply_selector_fix_never_reached_for_a_payload_that_fails_validation():
    # End-to-end proof the fix actually closes the hole: heal() (not
    # exercised directly here, since it needs a live LLM call) is expected
    # to check is_safe_selector before calling apply_selector_fix at all -
    # this confirms the payload that used to produce injected code is
    # rejected by the gate that now sits in front of it.
    payload = '#x").click(); import os; os.system("id > /tmp/pwned'
    assert is_safe_selector(payload) is False
