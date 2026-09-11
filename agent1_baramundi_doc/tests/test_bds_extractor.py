import pytest

from src import bds_extractor

SAMPLE_BDS = """<?xml version="1.0" encoding="UTF-8"?>
<BDS Version="1.0" LastChange="2024-01-01">
  <META>
    <INFO Author="tester" Category="Software"/>
  </META>
  <ACTIONS>
    <ACTION type="SetVar" comment="0">
      <DATA>
        <VARNAME>APP_NAME</VARNAME>
        <VALUE>Adobe Acrobat Reader DC</VALUE>
      </DATA>
    </ACTION>
    <ACTION type="SetVar" comment="1">
      <DATA>
        <VARNAME>DISABLED_VAR</VARNAME>
        <VALUE>unused</VALUE>
      </DATA>
    </ACTION>
    <ACTION type="Comment" comment="0">
      <DATA>
        <VALUE>#Product Owner: Jane Doe</VALUE>
      </DATA>
    </ACTION>
    <ACTION type="Comment" comment="0">
      <DATA>
        <VALUE>   </VALUE>
      </DATA>
    </ACTION>
    <ACTION type="IncludeBDS" comment="0">
      <DATA>
        <FILENAME>common_include.bds</FILENAME>
      </DATA>
    </ACTION>
    <ACTION type="LaunchProcess" comment="0" level="1">
      <DATA>
        <COMMAND>setup.exe</COMMAND>
        <PARAM>/silent</PARAM>
        <RETURNCODES>0,3010</RETURNCODES>
      </DATA>
    </ACTION>
    <ACTION type="EndBDS" comment="0" level="0">
      <DATA>
        <RETURNMESSAGE>Installation complete</RETURNMESSAGE>
      </DATA>
    </ACTION>
  </ACTIONS>
</BDS>
"""


@pytest.fixture
def digest(tmp_path):
    bds_path = tmp_path / "sample.bds"
    bds_path.write_text(SAMPLE_BDS, encoding="utf-8")
    return bds_extractor.extract_bds(bds_path)


def test_extract_bds_parses_top_level_metadata(digest):
    assert digest["script_version"] == "1.0"
    assert digest["last_change"] == "2024-01-01"
    assert digest["info"] == {"Author": "tester", "Category": "Software"}


def test_extract_bds_captures_variables_with_disabled_flag(digest):
    assert {"name": "APP_NAME", "value": "Adobe Acrobat Reader DC", "disabled": False} in digest["variables"]
    assert {"name": "DISABLED_VAR", "value": "unused", "disabled": True} in digest["variables"]


def test_extract_bds_captures_annotations_and_skips_blank_comments(digest):
    # Only the non-blank comment should appear - the whitespace-only one is a
    # spacer and must be skipped, per extract_bds's explicit check.
    assert digest["annotations"] == [{"text": "#Product Owner: Jane Doe", "disabled": False}]


def test_extract_bds_captures_includes(digest):
    assert digest["includes"] == [
        {"filename": "common_include.bds", "condition": "", "disabled": False}
    ]


def test_extract_bds_flow_contains_launch_process_and_endbds(digest):
    summaries = [step["summary"] for step in digest["flow"]]
    assert any("LaunchProcess: setup.exe /silent" in s and "[rc: 0,3010]" in s for s in summaries)
    assert any('EndBDS: "Installation complete"' in s for s in summaries)


def test_extract_bds_flow_step_keeps_its_nesting_level_and_disabled_flag(digest):
    launch_step = next(s for s in digest["flow"] if s["summary"].startswith("LaunchProcess"))
    assert launch_step["level"] == "1"
    assert launch_step["disabled"] is False


def test_extract_bds_missing_actions_element_returns_empty_digest(tmp_path):
    bds_path = tmp_path / "no_actions.bds"
    bds_path.write_text('<BDS Version="1.0" LastChange="2024-01-01"></BDS>', encoding="utf-8")

    digest = bds_extractor.extract_bds(bds_path)

    assert digest["variables"] == []
    assert digest["flow"] == []


# ---- EvalVar / Wait actions with no <DATA> child: found during a bug-hunt
# review. Every other action type reads its fields through _child_text,
# which is None-safe, but these two called data.iter(...) directly - a
# schema variant or stub action with no <DATA> child crashed the whole
# agent run instead of degrading like the "unknown action type" fallback
# does for everything else.

def test_extract_bds_evalvar_action_with_no_data_child_does_not_crash(tmp_path):
    bds_path = tmp_path / "evalvar_no_data.bds"
    bds_path.write_text(
        '<BDS Version="1.0" LastChange="2024-01-01">'
        '<ACTIONS><ACTION type="EvalVar" comment="0"/></ACTIONS>'
        "</BDS>",
        encoding="utf-8",
    )

    digest = bds_extractor.extract_bds(bds_path)  # must not raise

    assert len(digest["flow"]) == 1
    assert "EvalVar" in digest["flow"][0]["summary"]


def test_extract_bds_wait_action_with_no_data_child_does_not_crash(tmp_path):
    bds_path = tmp_path / "wait_no_data.bds"
    bds_path.write_text(
        '<BDS Version="1.0" LastChange="2024-01-01">'
        '<ACTIONS><ACTION type="Wait" comment="0"/></ACTIONS>'
        "</BDS>",
        encoding="utf-8",
    )

    bds_extractor.extract_bds(bds_path)  # must not raise


def test_script_synopsis_extracts_declared_synopsis_line():
    script = (
        "<#\n"
        ".SYNOPSIS\n"
        "Installs the printer driver silently.\n"
        ".DESCRIPTION\n"
        "more stuff\n"
        "#>\n"
        'Write-Host "hi"\n'
    )
    assert bds_extractor._script_synopsis(script) == "Installs the printer driver silently."


def test_script_synopsis_falls_back_to_first_meaningful_code_line():
    # The fallback only skips known boilerplate prefixes (<#, #>, #, param,
    # $ErrorAction, .) - every preceding line here uses one of those, so the
    # first line that doesn't is the one that should come back.
    script = (
        "<#\n"
        "#>\n"
        "param($x)\n"
        "$ErrorActionPreference = 'Stop'\n"
        "# just a comment\n"
        'Write-Host "actual code line"\n'
    )
    assert bds_extractor._script_synopsis(script) == 'Write-Host "actual code line"'


def test_script_synopsis_truncates_long_fallback_line():
    long_line = "x" * 150
    result = bds_extractor._script_synopsis(long_line)
    assert result.endswith("...")
    assert len(result) == 120


def test_script_synopsis_returns_empty_string_when_nothing_matches():
    script = "<#\n#>\nparam($x)\n"
    assert bds_extractor._script_synopsis(script) == ""


def test_render_digest_marks_disabled_items_and_renders_conditions():
    digest = {
        "script_version": "1.0",
        "last_change": "2024-01-01",
        "info": {"Author": "tester"},
        "variables": [{"name": "APP_NAME", "value": "Foo", "disabled": False}],
        "annotations": [{"text": "note", "disabled": True}],
        "includes": [{"filename": "inc.bds", "condition": "X == Y", "disabled": False}],
        "flow": [{"level": "1", "summary": "LaunchProcess: foo.exe", "disabled": True}],
    }

    text = bds_extractor.render_digest(digest)

    assert "- Script format version: 1.0" in text
    assert "- APP_NAME = Foo" in text
    assert "- note  (DISABLED)" in text
    assert "- inc.bds  [when: X == Y]" in text
    assert "  - LaunchProcess: foo.exe  (DISABLED)" in text
