from unittest import mock

import pytest

from src import test_generator


# ---- Found during a bug-hunt review: data.get("test_cases", []) silently
# defaulted to an empty list whenever the AI's JSON didn't have exactly
# that key - producing a "successful" run with zero test cases,
# indistinguishable from a legitimately empty result. Now raises instead,
# so a caller checking only the exit code can tell the difference.

def _generate_with_mocked_ai(requirements_text, raw_ai_response, tmp_path):
    req_path = tmp_path / "requirements.md"
    req_path.write_text(requirements_text, encoding="utf-8")

    with mock.patch.object(test_generator, "llm_client") as mock_llm, \
         mock.patch.object(test_generator, "events"):
        mock_llm.generate.return_value = raw_ai_response
        return test_generator.generate_test_cases(str(req_path), str(tmp_path))


def test_generate_test_cases_works_normally_with_the_expected_shape(tmp_path):
    result = _generate_with_mocked_ai(
        "# Req\n", '{"test_cases": [{"id": "TC-001", "title": "T", "steps": []}]}', tmp_path,
    )
    assert result["test_cases"] == 1


def test_generate_test_cases_raises_when_ai_uses_a_different_top_level_key(tmp_path):
    # A plausible deviation from the documented schema (e.g. "testCases"
    # instead of "test_cases") used to silently produce zero rows instead
    # of surfacing the mismatch.
    with pytest.raises(ValueError, match="test_cases"):
        _generate_with_mocked_ai("# Req\n", '{"testCases": []}', tmp_path)


def test_generate_test_cases_raises_when_ai_response_is_not_an_object(tmp_path):
    with pytest.raises(ValueError, match="test_cases"):
        _generate_with_mocked_ai("# Req\n", "[]", tmp_path)


def test_generate_test_cases_accepts_a_genuinely_empty_test_cases_list(tmp_path):
    # The key IS present, just empty - this is a legitimate result, not an
    # error, and must not raise.
    result = _generate_with_mocked_ai("# Req\n", '{"test_cases": []}', tmp_path)
    assert result["test_cases"] == 0
