"""Builds the prompt Agent 3 sends to the LLM to adapt the automation
script for a new/changed requirement.

The model returns the FULL updated file content in a single fenced code
block (not a diff) - simpler and more reliable to parse than asking the
model to produce a correct unified diff, same "make the model return
something code can apply deterministically" idea as Agent 2's JSON contract.
"""

SYSTEM_PROMPT = """You are the Script Adaptation Agent (AI Copilot) in the Aqua \
Automation Factory pipeline. You are given a new or changed testing requirement \
and the current Python Playwright/pytest automation script that it applies to. \
Your job is to update the script to satisfy the requirement.

Rules:
- Preserve the script's existing structure, style, and imports unless the \
requirement requires a change.
- Make the minimal change needed to satisfy the requirement. Do not refactor \
or "improve" unrelated code.
- Only use selectors/elements that already exist in the script or that the \
requirement explicitly describes. Never invent a UI element that isn't there.
- Return ONLY the full, updated file content in a single fenced Python code \
block. No commentary before or after the code block, no explanation.
"""


def build_prompt(requirement_text, current_script_text, script_relpath):
    user_prompt = f"""## New/changed requirement
{requirement_text}

## Current script ({script_relpath})
```python
{current_script_text}
```

Return the full updated content of {script_relpath} now, as a single \
fenced Python code block.
"""
    return SYSTEM_PROMPT, user_prompt
