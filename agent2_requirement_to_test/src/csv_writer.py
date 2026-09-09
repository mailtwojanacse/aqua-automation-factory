"""Turns the model's test-case JSON into an Aqua Test Center Import CSV.

IMPORTANT: the exact Aqua Import CSV column names/layout are an ASSUMPTION,
pending the client's Aqua Test Center import template. They're isolated in
AQUA_COLUMNS below so they can be swapped without touching logic. Layout is
one row per test step, with test-case-level fields repeated on each row
(the most import-tool-friendly layout).
"""
import csv
import json
import re

# Assumed Aqua Import CSV header. Replace with the client's real template.
AQUA_COLUMNS = [
    "Test Case ID",
    "Title",
    "Description",
    "Precondition",
    "Priority",
    "Step No",
    "Step Action",
    "Expected Result",
]


def parse_model_json(text):
    """Parse the model's response into a dict, tolerating stray code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    return json.loads(text)


def to_rows(test_cases):
    rows = []
    for tc in test_cases:
        tc_id = tc.get("id") or ""
        title = tc.get("title", "")
        description = tc.get("description", "")
        precondition = tc.get("precondition", "")
        priority = tc.get("priority", "")
        steps = tc.get("steps") or [{"action": "", "expected": ""}]
        for i, step in enumerate(steps, start=1):
            rows.append({
                "Test Case ID": tc_id,
                "Title": title,
                "Description": description,
                "Precondition": precondition,
                "Priority": priority,
                "Step No": i,
                "Step Action": step.get("action", ""),
                "Expected Result": step.get("expected", ""),
            })
    return rows


def write_csv(test_cases, path):
    rows = to_rows(test_cases)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=AQUA_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
