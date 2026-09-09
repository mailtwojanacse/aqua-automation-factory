"""Builds the prompt Agent 4 sends to the LLM to review a pull request
raised by Agent 3.

The model returns JSON (verdict + comments), not free text - reviewer.py
parses that JSON deterministically and turns it into a real `gh pr review`
call, same JSON-then-code pattern used in Agent 2.
"""
import json

OUTPUT_SCHEMA = {
    "verdict": "approve | request_changes",
    "summary": "string  (one or two sentences explaining the verdict)",
    "comments": [
        {"concern": "string  (e.g. 'code quality', 'security', 'traceability')",
         "detail": "string"}
    ],
}

SYSTEM_PROMPT = """You are the Automation Review Agent in the Aqua Automation \
Factory pipeline. You review a pull request raised by the Script Adaptation \
Agent against the automation test suite, before it is merged and executed.

Review for:
- Code quality and standards (clarity, consistency with the surrounding style).
- Security (no hardcoded secrets/credentials, no unsafe execution of external input).
- Traceability (does the change actually address the stated requirement, and \
only that requirement - no unrelated scope creep).

Rules:
- Base your verdict only on the diff and requirement text given. Don't assume \
context that isn't shown.
- "approve" only if you find no blocking issues. Otherwise "request_changes" \
and explain exactly what must change.
- Return ONLY a single JSON object matching the given schema. No markdown, no \
code fences, no commentary before or after the JSON.
"""


def build_prompt(pr_title, pr_body, diff_text):
    schema_str = json.dumps(OUTPUT_SCHEMA, indent=2)
    user_prompt = f"""## Output JSON schema (return exactly this shape)
{schema_str}

## Pull request title
{pr_title}

## Pull request description
{pr_body}

## Diff to review
```diff
{diff_text}
```

Return the JSON review verdict now.
"""
    return SYSTEM_PROMPT, user_prompt
