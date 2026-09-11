"""Self-heal: when a Playwright locator breaks, first try a cheap
deterministic fix (see rule_based_heal.py); only if that's not confident
enough, ask the LLM for a replacement selector. Either way: patch the
script on a new branch, verify the fix actually works, and (only if it
does) push + open a follow-up PR so the fix stays traceable through Git
rather than silently patching production code.
"""
import re
from pathlib import Path

from src import events, git_ops, heal_prompt_builder, llm_client, rule_based_heal, runner

AGENT = "Agent 5"

# apply_selector_fix splices the AI's answer directly into a Python source
# file as literal text inside a quoted string. An unvalidated answer could
# contain a quote character that closes that string early, followed by
# arbitrary Python - which would then get executed as soon as pytest runs
# the patched file (self-heal's own "verify the fix" step, before any
# human review). This allowlist keeps the accepted shape to what a real
# CSS selector for this pipeline's use case looks like (ids, classes,
# tags, attribute/combinator syntax) while excluding the characters that
# make that injection possible - quotes, semicolons, backslashes, newlines.
_SAFE_SELECTOR_RE = re.compile(r"^[A-Za-z0-9_\-\.#\[\]=:>~+*^$| ]{1,200}\Z")


def is_safe_selector(selector):
    return bool(selector) and _SAFE_SELECTOR_RE.match(selector) is not None


def get_page_html(repo_path, target_page):
    from playwright.sync_api import sync_playwright

    page_path = Path(repo_path) / "sample_app" / target_page
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(page_path.as_uri())
        html = page.content()
        browser.close()
    return html


def apply_selector_fix(script_path, old_selector, new_selector):
    text = Path(script_path).read_text(encoding="utf-8")
    updated = text.replace(f'"{old_selector}"', f'"{new_selector}"')
    updated = updated.replace(f"'{old_selector}'", f"'{new_selector}'")
    Path(script_path).write_text(updated, encoding="utf-8")
    return updated != text


def _known_good_page_for(target_page):
    """This pipeline's job registry always pairs a 'v2' (current, broken)
    target page with a 'v1' (known-good) sibling - derive it by naming
    convention rather than threading the job name all the way down here.
    Returns None if target_page doesn't look like a 'v2' page, i.e.
    there's no known-good sibling to compare against."""
    if "v2" not in target_page:
        return None
    return target_page.replace("v2", "v1")


def _try_deterministic_fix(repo_path, target_page, broken_selector):
    """Best-effort: any failure here (no known-good sibling, a Playwright
    hiccup, whatever) just means "no deterministic fix available", not a
    reason to abort self-heal - the AI fallback covers it either way."""
    known_good_page = _known_good_page_for(target_page)
    if known_good_page is None:
        return None
    sample_app_dir = Path(repo_path) / "sample_app"
    known_good_path = sample_app_dir / known_good_page
    if not known_good_path.is_file():
        return None
    try:
        return rule_based_heal.find_deterministic_replacement(
            known_good_path, sample_app_dir / target_page, broken_selector,
        )
    except Exception:
        return None


def build_heal_prompt(repo_path, target_page, broken_selector, output_dir):
    html = get_page_html(repo_path, target_page)
    system_prompt, user_prompt = heal_prompt_builder.build_prompt(broken_selector, html)
    prompt_path = Path(output_dir) / "self_heal.prompt.txt"
    prompt_path.write_text(
        f"===== SYSTEM PROMPT =====\n{system_prompt}\n"
        f"\n===== USER PROMPT =====\n{user_prompt}\n",
        encoding="utf-8",
    )
    return system_prompt, user_prompt, prompt_path


def heal(repo_path, script_relpath, target_page, broken_selector, output_dir):
    """Attempt a real self-heal: branch, patch, re-run, and (if fixed) open
    a follow-up PR. Returns a result dict; never raises on a failed heal."""
    repo_path = Path(repo_path)
    used_ai = False

    new_selector = _try_deterministic_fix(repo_path, target_page, broken_selector)
    if new_selector:
        events.emit(AGENT, "mechanical",
                     f"Found a deterministic replacement for {broken_selector} without "
                     f"calling the AI: {new_selector}")
    else:
        used_ai = True
        system_prompt, user_prompt, _ = build_heal_prompt(repo_path, target_page, broken_selector, output_dir)
        events.emit(AGENT, "ai_call", f"Calling the AI for a replacement selector for {broken_selector}")
        new_selector = llm_client.generate(system_prompt, user_prompt).strip()
        events.emit(AGENT, "ai_call", f"AI suggested: {new_selector}")

        if not new_selector or new_selector == "NO_MATCH":
            events.emit(AGENT, "error", "AI found no plausible replacement selector")
            return {"status": "self_heal_no_match", "broken_selector": broken_selector}

    if not is_safe_selector(new_selector):
        source = "AI-suggested" if used_ai else "deterministically-found"
        events.emit(AGENT, "error",
                     f"{source} selector failed safety validation, refusing to apply it: {new_selector!r}")
        return {
            "status": "self_heal_unsafe_selector",
            "broken_selector": broken_selector,
            "attempted_selector": new_selector,
        }

    script_path = repo_path / script_relpath
    branch_name = f"agent5-selfheal/{git_ops.slugify(broken_selector)}"

    git_ops.checkout_branch_from_main(repo_path, branch_name)
    events.emit(AGENT, "mechanical", f"Created branch {branch_name} to try the fix")

    changed = apply_selector_fix(script_path, broken_selector, new_selector)
    if not changed:
        git_ops.checkout_main(repo_path)
        events.emit(AGENT, "error", "Suggested selector didn't match anything to replace in the script")
        return {"status": "self_heal_no_match", "broken_selector": broken_selector, "attempted_selector": new_selector}

    events.emit(AGENT, "mechanical", f"Applied fix in the script: {broken_selector} -> {new_selector}")

    retry_log_path = Path(output_dir) / "pytest_after_heal.log"
    passed, _ = runner.run_pytest(repo_path, script_relpath, target_page, retry_log_path)
    events.emit(AGENT, "mechanical", f"Re-ran the test to verify the fix: {'PASSED' if passed else 'STILL FAILED'}")

    if not passed:
        git_ops.checkout_main(repo_path)  # discard the failed attempt locally; branch never pushed
        events.emit(AGENT, "error", "Fix did not work - discarded locally, nothing pushed")
        return {
            "status": "self_heal_failed",
            "broken_selector": broken_selector,
            "attempted_selector": new_selector,
            "retry_log": str(retry_log_path),
        }

    commit_message = f"Self-heal: replace broken locator {broken_selector} with {new_selector}"
    try:
        git_ops.commit_and_push(repo_path, [str(script_relpath)], commit_message, branch_name)
    except Exception as exc:
        git_ops.checkout_main(repo_path)
        events.emit(AGENT, "error",
                    f"Fix was verified but committing/pushing it to {branch_name} failed - "
                    f"discarded locally, nothing pushed: {exc}")
        return {
            "status": "self_heal_push_failed",
            "broken_selector": broken_selector,
            "new_selector": new_selector,
            "retry_log": str(retry_log_path),
        }
    events.emit(AGENT, "mechanical", f"Committed and pushed the verified fix to {branch_name}")

    pr_title = f"Self-heal: {broken_selector} -> {new_selector}"
    fix_source = ("asked the AI for a replacement selector" if used_ai
                  else "found deterministically, by comparing against the known-good page - no AI call needed")
    pr_body = (
        "Automated locator fix raised by Agent 5 (Execution & Self-Healing Agent) "
        "after a scheduled run detected a broken selector.\n\n"
        f"**Broken selector:** `{broken_selector}`\n"
        f"**Replacement selector:** `{new_selector}`\n"
        f"**How it was found:** {fix_source}.\n"
        f"**Verified by:** re-running `{script_relpath}` against `{target_page}` - now passes.\n\n"
        "_Please review before merging - this is a locator-only change, no test behaviour changed._"
    )
    try:
        pr_url = git_ops.open_pr(repo_path, branch_name, pr_title, pr_body)
    except Exception as exc:
        events.emit(AGENT, "error",
                    f"Fix was committed and pushed to {branch_name} but opening the pull "
                    f"request failed - the branch is on origin with no PR, needs manual "
                    f"follow-up: {exc}")
        return {
            "status": "self_heal_pr_failed",
            "broken_selector": broken_selector,
            "new_selector": new_selector,
            "branch": branch_name,
            "retry_log": str(retry_log_path),
        }
    events.emit(AGENT, "mechanical", f"Opened follow-up pull request: {pr_url}")
    events.emit(AGENT, "handoff", f"{pr_url} ready for human/Agent 4 review", {"pr_url": pr_url})

    return {
        "status": "self_healed",
        "broken_selector": broken_selector,
        "new_selector": new_selector,
        "used_ai": used_ai,
        "pr_url": pr_url,
        "retry_log": str(retry_log_path),
    }
