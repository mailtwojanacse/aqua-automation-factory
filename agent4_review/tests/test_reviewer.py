from src.reviewer import format_review_body, parse_verdict_json


def test_parse_verdict_json_plain():
    assert parse_verdict_json('{"verdict": "approve"}') == {"verdict": "approve"}


def test_parse_verdict_json_strips_labeled_code_fence():
    text = '```json\n{"verdict": "approve"}\n```'
    assert parse_verdict_json(text) == {"verdict": "approve"}


def test_parse_verdict_json_strips_bare_code_fence():
    text = '```\n{"verdict": "request_changes"}\n```'
    assert parse_verdict_json(text) == {"verdict": "request_changes"}


def test_format_review_body_includes_findings_and_footer():
    body = format_review_body("Looks fine overall.", [
        {"concern": "security", "detail": "No secrets committed."},
    ])

    assert body.startswith("Looks fine overall.")
    assert "**Findings:**" in body
    assert "**security:** No secrets committed." in body
    assert "Posted automatically by Agent 4" in body


def test_format_review_body_without_comments_skips_findings_section():
    body = format_review_body("All good.", [])

    assert "**Findings:**" not in body
    assert "Posted automatically by Agent 4" in body


def test_format_review_body_defaults_missing_concern_and_detail():
    body = format_review_body("Summary", [{}])

    assert "**note:** " in body
