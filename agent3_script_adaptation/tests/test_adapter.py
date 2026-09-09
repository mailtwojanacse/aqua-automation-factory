from src.adapter import extract_code_block


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
