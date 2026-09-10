"""Rule-based (no-AI) locator healing, tried before falling back to the AI.

Inspired by a separate rule-based self-healing engine
(/home/janakiraman/Documents/TUV/Self_Healer) that classifies failures and
scores DOM-fingerprint matches instead of asking an AI. That engine keeps
a persistent "last known good" fingerprint cache since it has to handle
arbitrary pages; this pipeline doesn't need one - the job registry
already has a first-class "known good" page for every job (its v1 target
page), so healing here just compares the broken selector's element on v1
against candidate elements on the current (v2) page.

A match is only proposed when it's unambiguous: the top-scoring candidate
must clear a minimum score AND beat the runner-up by a margin. Ambiguous
or low-confidence cases return None so the caller falls back to the AI -
this is meant to catch the easy, common case (one thing renamed) cheaply,
not to replace the AI for anything murkier.
"""
CANDIDATE_SELECTOR = "button, a, input[type=button], input[type=submit], [role=button]"
MIN_SCORE = 0.5
MIN_MARGIN = 0.15

_FINGERPRINT_JS = """el => ({
    tag: el.tagName.toLowerCase(),
    id: el.id || '',
    classes: (el.className || '').toString().split(/\\s+/).filter(Boolean),
    role: el.getAttribute('role') || '',
    text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 80),
})"""


def _extract_fingerprint(page, selector):
    """Fingerprint of the element `selector` currently resolves to on
    `page`, or None if it doesn't resolve there at all."""
    locator = page.locator(selector)
    if locator.count() == 0:
        return None
    return locator.first.evaluate(_FINGERPRINT_JS)


def _candidate_fingerprints(page):
    """Fingerprint every plausible clickable element on the current page -
    these are what the broken selector's replacement could be."""
    candidates = page.locator(CANDIDATE_SELECTOR)
    return [candidates.nth(i).evaluate(_FINGERPRINT_JS) for i in range(candidates.count())]


def score_match(known_good_fp, candidate_fp):
    """How well `candidate_fp` matches `known_good_fp`, from 0 to 1. Pure
    function - no browser needed - so it's directly unit-testable.

    Weighted: tag (0.3), role (0.2), class overlap (0.25), text-word
    overlap (0.25). Two elements with no classes/role at all count as a
    match on that dimension (absence isn't a distinguishing signal), but
    two elements that both have no text in common score 0 on text - text
    changing alongside an id is common (see this repo's own self-heal
    demo: "Verify Installation" -> "Confirm Installation") so it can't be
    required, only rewarded when it does overlap.
    """
    score = 0.0

    if known_good_fp["tag"] == candidate_fp["tag"]:
        score += 0.3

    known_role, cand_role = known_good_fp["role"], candidate_fp["role"]
    if known_role == cand_role:
        score += 0.2

    known_classes, cand_classes = set(known_good_fp["classes"]), set(candidate_fp["classes"])
    if known_classes or cand_classes:
        score += 0.25 * (len(known_classes & cand_classes) / len(known_classes | cand_classes))
    else:
        score += 0.25

    known_words = set(known_good_fp["text"].lower().split())
    cand_words = set(candidate_fp["text"].lower().split())
    if known_words and cand_words:
        score += 0.25 * (len(known_words & cand_words) / len(known_words | cand_words))

    return score


def best_candidate(known_good_fp, candidate_fps):
    """Rank candidates against the known-good fingerprint; return the
    winning fingerprint, or None if there's no unambiguous winner (no
    candidates, best score too low, or top two too close to call). Pure
    function - the ambiguity rule itself is what's actually being tested,
    so keeping it separate from any Playwright call matters."""
    if not candidate_fps:
        return None
    scored = sorted(
        ((c, score_match(known_good_fp, c)) for c in candidate_fps),
        key=lambda item: item[1], reverse=True,
    )
    top_fp, top_score = scored[0]
    if top_score < MIN_SCORE:
        return None
    if len(scored) > 1 and (top_score - scored[1][1]) < MIN_MARGIN:
        return None
    return top_fp


def find_deterministic_replacement(known_good_page_path, current_page_path, broken_selector):
    """Try to find a confident, unambiguous replacement CSS selector for
    broken_selector by comparing its element's fingerprint on the job's
    known-good (v1) page against every plausible clickable element on the
    current (broken) page. Returns a "#id" selector string, or None if no
    confident match was found - callers should fall back to the AI in
    that case. Only proposes id-based selectors, since every interactive
    element in this pipeline's demo pages has one and it keeps the output
    shape simple to validate (same is_safe_selector gate as the AI path).
    """
    # Imported lazily, same reasoning as every other Playwright import in
    # this pipeline - this module can be loaded without playwright
    # installed (e.g. for --dry-run) as long as this function isn't called.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            known_good_page = browser.new_page()
            known_good_page.goto(known_good_page_path.as_uri())
            known_fp = _extract_fingerprint(known_good_page, broken_selector)
            known_good_page.close()
            if known_fp is None:
                return None

            current_page = browser.new_page()
            current_page.goto(current_page_path.as_uri())
            candidates = _candidate_fingerprints(current_page)
            current_page.close()
        finally:
            browser.close()

    winner = best_candidate(known_fp, candidates)
    if winner is None or not winner["id"]:
        return None
    return f"#{winner['id']}"
