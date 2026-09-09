"""Builds the prompt Agent 2 sends to the LLM to turn a requirements.md
(produced by Agent 1) into structured test cases.

The model returns JSON only; csv_writer.py turns that JSON into the Aqua
Import CSV. Keeping the model on JSON (not raw CSV) avoids CSV-escaping bugs.
"""
import json

# The JSON contract the model must return. Shown to the model verbatim.
OUTPUT_SCHEMA = {
    "test_cases": [
        {
            "id": "string | null  (reuse a TC-#### id if the requirements mention one, else null)",
            "title": "string  (short, imperative, e.g. 'Verify Adobe Acrobat installs on Windows 11')",
            "description": "string  (one or two sentences)",
            "precondition": "string  (from the Preconditions section; '' if none apply)",
            "priority": "High | Medium | Low",
            "steps": [
                {"action": "string  (what the tester/automation does)",
                 "expected": "string  (the observable pass condition)"}
            ],
        }
    ]
}

SYSTEM_PROMPT = """You are the Requirement-to-Test Agent in the Aqua Automation \
Factory pipeline. You read a requirements markdown file (Preconditions and Validation \
Rules for a Baramundi software job) and produce structured functional test cases for \
Aqua Test Center.

Rules:
- Derive test cases ONLY from the provided requirements. Do not invent versions, \
preconditions, or behaviours that aren't stated or directly implied.
- Turn each Validation Rule into at least one test case with concrete steps and an \
explicit expected result. Preconditions become the test case's precondition field.
- If the requirements reference Aqua test case IDs (TC-####), reuse them in the "id" \
field; otherwise set "id" to null and let Aqua assign one on import.
- Return ONLY a single JSON object matching the given schema. No markdown, no code \
fences, no commentary before or after the JSON.
"""


def build_prompt(requirements_markdown):
    schema_str = json.dumps(OUTPUT_SCHEMA, indent=2)
    user_prompt = f"""## Output JSON schema (return exactly this shape)
{schema_str}

## Requirements (source)
```
{requirements_markdown}
```

Return the JSON object of test cases now.
"""
    return SYSTEM_PROMPT, user_prompt
