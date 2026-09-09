"""Builds the prompt Agent 1 sends to the LLM to turn raw Baramundi
artifacts into the single-source-of-truth markdown knowledge file.
"""
import json
from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "knowledge_doc_template.md"

SYSTEM_PROMPT = """You are the Baramundi Documentation Agent in the Aqua Automation \
Factory pipeline. You turn raw Baramundi job artifacts (a .bds deployment script, an \
XML deployment configuration, and a job configuration) into a single markdown \
knowledge file that other agents and Aqua Test Center rely on as the source of truth.

Rules:
- Only use information present in the provided artifacts. Never invent version numbers, \
preconditions, validation rules, or Aqua test case IDs that aren't supported by the input.
- If a template section has no corresponding data in the inputs, write exactly: \
"Not specified in source artifacts." for that section instead of guessing.
- Follow the target template's headings and structure exactly - do not add, remove, \
or rename sections.
- Output only the markdown document, no commentary before or after it.
"""


def _render(artifact):
    if artifact["format"] == "text":
        return artifact["data"]
    return json.dumps(artifact["data"], indent=2)


def build_prompt(bds_digest_text, xml_config, job_config, job_name):
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    user_prompt = f"""Job name: {job_name}

## Target template (follow this structure exactly)
```
{template}
```

## Source artifact 1 - BDS deployment script (distilled digest)
The .bds is a procedural action script; this is a compact digest of it. Note any
"(DISABLED)" markers mean that action is commented-out and does NOT run. Included
BDS files are external and their contents are not available here.
```
{bds_digest_text}
```

## Source artifact 2 - XML Configuration ({xml_config["format"]})
```
{_render(xml_config)}
```

## Source artifact 3 - Job Configuration ({job_config["format"]})
```
{_render(job_config)}
```

Produce the markdown knowledge file for this job now.
"""
    return SYSTEM_PROMPT, user_prompt
