"""Splits the merged knowledge-file markdown into README/requirements/testspec,
for cases where the client wants Agent 1's three separate outputs (README.md,
requirements.md, testspec.md) instead of one merged per-job file.

Section-to-file mapping (assumption, pending client confirmation):
- README.md       <- Software Package + Purpose (what the job is)
- requirements.md <- Preconditions + Validation Rules (what Agent 2/3 consume)
- testspec.md     <- Evidence + Aqua Test Case Mapping (what Aqua/Agent 5 consume)
"""
import re

SECTION_MAP = {
    "readme": ["Software Package", "Purpose"],
    "requirements": ["Preconditions", "Validation Rules"],
    "testspec": ["Evidence", "Aqua Test Case Mapping"],
}

_HEADING_RE = re.compile(r"^(#{1,2})\s+(.*)$", re.MULTILINE)


def _parse_sections(markdown):
    matches = list(_HEADING_RE.finditer(markdown))
    sections = {}
    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        sections[heading] = markdown[start:end].rstrip() + "\n"
    return sections


def split_into_three(merged_markdown):
    sections = _parse_sections(merged_markdown)
    output = {}
    for filename, headings in SECTION_MAP.items():
        parts = [sections[h] for h in headings if h in sections]
        output[filename] = "\n".join(parts) if parts else "Not specified in source artifacts.\n"
    return output
