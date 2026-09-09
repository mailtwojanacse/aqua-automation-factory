"""Builds the prompt Agent 5 sends to the LLM when a test fails because a
CSS selector no longer matches anything on the page (a "broken locator").

The model returns ONLY the replacement selector string - not commentary,
not a code block - so self_healer.py can apply it with a plain string
substitution, no parsing needed.
"""

SYSTEM_PROMPT = """You are the self-healing component of the Execution & \
Self-Healing Agent in the Aqua Automation Factory pipeline. A Playwright \
test just timed out waiting for a CSS selector that used to work - most \
likely the target application's UI changed (an id/class renamed) while the \
underlying user action stayed the same.

You are given the broken selector and the current page's full HTML. Find \
the element that serves the same purpose the broken selector was clearly \
trying to reach, and return a new CSS selector for it.

Rules:
- Return ONLY the new CSS selector string (e.g. "#confirm-install-btn"). \
No commentary, no quotes around it, no explanation, nothing else.
- If you cannot find a plausible replacement in the given HTML, return \
exactly: NO_MATCH
"""


def build_prompt(broken_selector, page_html):
    user_prompt = f"""## Broken selector
{broken_selector}

## Current page HTML
```html
{page_html}
```

Return the replacement CSS selector now.
"""
    return SYSTEM_PROMPT, user_prompt
