from src.adapter import extract_code_block, is_valid_python


def test_extract_code_block_with_python_tag():
    text = "Here you go:\n```python\nprint('hi')\n```\n"
    assert extract_code_block(text) == "print('hi')"


def test_extract_code_block_without_language_tag():
    text = "```\nprint('hi')\n```"
    assert extract_code_block(text) == "print('hi')"


def test_extract_code_block_falls_back_to_raw_text_when_no_fence():
    text = "print('hi')"
    assert extract_code_block(text) == "print('hi')"


def test_extract_code_block_preserves_multiline_content():
    text = "```python\ndef f():\n    return 1\n```"
    assert extract_code_block(text) == "def f():\n    return 1"


# ---- is_valid_python: found during a bug-hunt review - a truncated or
# empty AI response has no closing fence for extract_code_block to match,
# so it falls back to returning raw/empty text. Without this check that
# text gets written over the real script, committed, and opened as a real
# PR with no validation at all - this is the gate that now sits in front
# of that.

def test_is_valid_python_accepts_a_realistic_script():
    assert is_valid_python("def test_x():\n    assert True\n") is True


def test_is_valid_python_rejects_empty_string():
    assert is_valid_python("") is False


def test_is_valid_python_rejects_whitespace_only():
    assert is_valid_python("   \n\n  ") is False


def test_is_valid_python_rejects_a_truncated_response():
    # The exact failure mode this exists for: the AI's response got cut off
    # mid-file (hit the token cap), so extract_code_block's fallback
    # returns this raw, syntactically-broken text as-is.
    assert is_valid_python("def test_verify_install(page):\n    page.locator(") is False
