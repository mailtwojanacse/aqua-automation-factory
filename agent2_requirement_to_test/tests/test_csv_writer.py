from src import csv_writer


def test_parse_model_json_plain():
    assert csv_writer.parse_model_json('{"test_cases": []}') == {"test_cases": []}


def test_parse_model_json_strips_labeled_code_fence():
    text = '```json\n{"test_cases": []}\n```'
    assert csv_writer.parse_model_json(text) == {"test_cases": []}


def test_parse_model_json_strips_bare_code_fence():
    text = '```\n{"test_cases": []}\n```'
    assert csv_writer.parse_model_json(text) == {"test_cases": []}


def test_to_rows_expands_one_row_per_step_and_repeats_case_level_fields():
    test_cases = [{
        "id": "TC-001",
        "title": "Verify install",
        "description": "desc",
        "precondition": "pre",
        "priority": "High",
        "steps": [
            {"action": "Open app", "expected": "App opens"},
            {"action": "Click verify", "expected": "Shows verified"},
        ],
    }]

    rows = csv_writer.to_rows(test_cases)

    assert len(rows) == 2
    assert rows[0]["Step No"] == 1
    assert rows[0]["Step Action"] == "Open app"
    assert rows[1]["Step No"] == 2
    assert rows[1]["Test Case ID"] == "TC-001"
    assert rows[1]["Title"] == "Verify install"


def test_to_rows_falls_back_to_one_empty_step_when_steps_missing():
    test_cases = [{"id": "TC-002", "title": "No steps case"}]

    rows = csv_writer.to_rows(test_cases)

    assert len(rows) == 1
    assert rows[0]["Step No"] == 1
    assert rows[0]["Step Action"] == ""
    assert rows[0]["Expected Result"] == ""


def test_write_csv_writes_aqua_header_and_rows(tmp_path):
    test_cases = [{"id": "TC-001", "title": "T", "steps": [{"action": "a", "expected": "e"}]}]
    out_path = tmp_path / "out.csv"

    row_count = csv_writer.write_csv(test_cases, out_path)

    assert row_count == 1
    content = out_path.read_text(encoding="utf-8")
    header = content.splitlines()[0]
    assert header == ",".join(csv_writer.AQUA_COLUMNS)
    assert "TC-001" in content
