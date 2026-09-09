"""Schema-tolerant loaders for Baramundi artifacts.

The real .bds / XML config / job config schemas haven't been confirmed with
the client yet, so these loaders try structured parsing first and fall back
to raw text rather than assuming exact tag or field names.
"""
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def _element_to_dict(el):
    """Convert an XML element to a compact dict/scalar.

    Kept lean to save prompt tokens:
    - A leaf element with only text collapses to that text string.
    - Attributes become "@name" keys, present only when the element has them.
    - A child tag that occurs once is a scalar value; a tag that repeats
      becomes a list. Text alongside attributes/children is kept as "#text".
    """
    children = list(el)
    text = (el.text or "").strip()

    # Leaf with no attributes: just its text (or None if empty).
    if not children and not el.attrib:
        return text or None

    node = {}
    for name, value in el.attrib.items():
        node[f"@{name}"] = value
    if text:
        node["#text"] = text

    for child in children:
        child_obj = _element_to_dict(child)
        if child.tag in node:
            existing = node[child.tag]
            if isinstance(existing, list):
                existing.append(child_obj)
            else:
                node[child.tag] = [existing, child_obj]
        else:
            node[child.tag] = child_obj

    return node


def _decode(raw_bytes):
    """Decode bytes to str, honoring common Baramundi encodings.

    Real .bds exports are often ISO-8859-1 (Latin-1) with German text, so a
    naive UTF-8 read corrupts umlauts. Try UTF-8 first, fall back to Latin-1
    (which never fails, so it's a safe last resort).
    """
    for encoding in ("utf-8", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("latin-1", errors="replace")


def load_any(path):
    """Load a file as structured XML/JSON, or fall back to raw text.

    Returns {"format": "xml" | "json" | "text", "data": ..., "path": str}
    """
    path = Path(path)
    raw_bytes = path.read_bytes()

    # Parse XML from bytes so ElementTree honors the <?xml encoding=...?>
    # declaration (e.g. ISO-8859-1) instead of guessing.
    try:
        root = ET.fromstring(raw_bytes)
        return {"format": "xml", "data": {root.tag: _element_to_dict(root)}, "path": str(path)}
    except ET.ParseError:
        pass

    text = _decode(raw_bytes)
    try:
        return {"format": "json", "data": json.loads(text), "path": str(path)}
    except json.JSONDecodeError:
        pass

    return {"format": "text", "data": text, "path": str(path)}
