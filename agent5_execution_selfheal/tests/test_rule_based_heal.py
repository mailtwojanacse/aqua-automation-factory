from src import rule_based_heal as rbh


def _fp(tag="button", id="", classes=None, role="", text=""):
    return {"tag": tag, "id": id, "classes": classes or [], "role": role, "text": text}


# ---- score_match ----

def test_score_match_is_perfect_for_an_identical_fingerprint():
    fp = _fp(id="verify-btn", classes=["cta"], text="Verify Installation")
    assert rbh.score_match(fp, fp) == 1.0


def test_score_match_rewards_tag_match_even_with_nothing_else_shared():
    known = _fp(tag="button", classes=["cta"], text="Verify Installation")
    candidate = _fp(tag="button", classes=["other"], text="Completely Different")
    score = rbh.score_match(known, candidate)
    assert 0.0 < score < 0.6  # tag matches (0.3), role matches-by-both-empty (0.2), nothing else


def test_score_match_penalizes_a_different_tag():
    known = _fp(tag="button")
    candidate = _fp(tag="a")
    same_tag_score = rbh.score_match(known, _fp(tag="button"))
    diff_tag_score = rbh.score_match(known, candidate)
    assert diff_tag_score < same_tag_score


def test_score_match_rewards_partial_text_overlap():
    # This pipeline's own real self-heal case: the button's label changed
    # alongside its id ("Verify Installation" -> "Confirm Installation").
    known = _fp(text="Verify Installation")
    candidate = _fp(text="Confirm Installation")
    score = rbh.score_match(known, candidate)
    assert score > rbh.score_match(known, _fp(text="")) # "installation" overlaps, beats no text at all


def test_score_match_treats_both_empty_class_lists_as_matching():
    known = _fp(classes=[])
    candidate = _fp(classes=[])
    with_class_score = rbh.score_match(_fp(classes=["cta"]), _fp(classes=["cta"]))
    assert rbh.score_match(known, candidate) == with_class_score  # both "no distinguishing signal" cases score the same


# ---- best_candidate ----

def test_best_candidate_returns_none_with_no_candidates():
    assert rbh.best_candidate(_fp(), []) is None


def test_best_candidate_picks_the_clear_winner():
    known = _fp(tag="button", text="Verify Installation")
    good = _fp(id="confirm-install-btn", tag="button", text="Confirm Installation")
    bad = _fp(id="unrelated-link", tag="a", text="Terms of Service")
    winner = rbh.best_candidate(known, [bad, good])
    assert winner["id"] == "confirm-install-btn"


def test_best_candidate_returns_none_when_top_score_is_too_low():
    known = _fp(tag="button", classes=["cta"], text="Verify Installation")
    candidates = [_fp(id="x", tag="a", classes=["nav"], text="Home")]
    assert rbh.best_candidate(known, candidates) is None


def test_best_candidate_returns_none_when_top_two_are_too_close_to_call():
    known = _fp(tag="button", text="Verify Installation")
    candidate_a = _fp(id="a", tag="button", text="Verify Installation")
    candidate_b = _fp(id="b", tag="button", text="Verify Installation")
    assert rbh.best_candidate(known, [candidate_a, candidate_b]) is None


def test_best_candidate_accepts_the_only_candidate_with_no_runner_up_penalty():
    # A single candidate can't be "ambiguous" against a runner-up that
    # doesn't exist - this is exactly this pipeline's real demo case
    # (exactly one <button> on the page).
    known = _fp(tag="button", text="Verify Installation")
    only_candidate = _fp(id="confirm-install-btn", tag="button", text="Confirm Installation")
    winner = rbh.best_candidate(known, [only_candidate])
    assert winner is not None
    assert winner["id"] == "confirm-install-btn"


# ---- _known_good_page_for (imported from self_healer, tested here since
# it's the naming-convention half of the same feature) ----

def test_known_good_page_for_derives_v1_from_v2():
    from src import self_healer
    assert self_healer._known_good_page_for("install_confirmation_v2.html") == "install_confirmation_v1.html"
    assert self_healer._known_good_page_for("7zip_confirmation_v2.html") == "7zip_confirmation_v1.html"


def test_known_good_page_for_returns_none_when_not_a_v2_page():
    from src import self_healer
    assert self_healer._known_good_page_for("install_confirmation_v1.html") is None
    assert self_healer._known_good_page_for("something_else.html") is None
