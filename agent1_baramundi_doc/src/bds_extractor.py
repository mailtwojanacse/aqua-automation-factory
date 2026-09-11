"""Baramundi-aware extractor for real .bds deployment scripts.

A real .bds is a *procedural* action script (dozens of <ACTION type="..."> steps),
not a clean declarative document. The meaningful information for documentation is
scattered across:
  - SetVar actions            -> variables (APP_NAME, APP_VERSION, SWID, PATCHFILE, ...)
  - Comment actions           -> human annotations & metadata (#Product Owner, #OS-Type, ...)
  - IncludeBDS actions         -> external include files pulled in at runtime
  - RunEmbeddedScript actions  -> embedded PowerShell/VBScript (we keep only the synopsis)
  - LaunchProcess / EvalVar / Conditional / EndBDS / ... -> the install logic & flow

Dumping all of that raw would explode the prompt (big embedded scripts) and bury the
signal. This module distills the .bds into a compact digest that Agent 1 sends to the LLM.

ASSUMPTION (confirm with client): an ACTION with comment="1" is DISABLED (the Baramundi
"comment out" checkbox). Disabled actions are captured but clearly marked, so the
documentation can describe what actually runs.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def _t(el):
    """Stripped text of an element (or '')."""
    return (el.text or "").strip() if el is not None else ""


def _child_text(data, tag):
    return _t(data.find(tag)) if data is not None else ""


def _script_synopsis(script):
    """Pull a one-line summary from an embedded script's comment header."""
    lines = script.splitlines()
    for i, line in enumerate(lines):
        if line.strip().upper().startswith(".SYNOPSIS"):
            for follow in lines[i + 1:]:
                s = follow.strip()
                if s and not s.startswith((".", "#>")):
                    return s
            break
    # Fallback: first meaningful line of code/comment.
    for line in lines:
        s = line.strip()
        if s and not s.startswith(("<#", "#>", "#", "param", "$ErrorAction", ".")):
            return (s[:117] + "...") if len(s) > 120 else s
    return ""


def _condition_str(action):
    cond = action.find("CONDITION")
    if cond is None:
        return ""
    return f'{cond.get("op1", "")} {cond.get("op", "")} {cond.get("op2", "")}'.strip()


def _summarize_action(action):
    """Return (kind, summary) for a meaningful action, or None to skip it."""
    a_type = action.get("type", "")
    data = action.find("DATA")
    cond = _condition_str(action)
    cond_suffix = f"  [when: {cond}]" if cond else ""

    if a_type == "Comment":
        return None  # comments handled separately (annotations / metadata)

    if a_type == "SetVar":
        return None  # variables handled separately

    if a_type == "IncludeBDS":
        return None  # includes handled separately

    if a_type == "RunEmbeddedScript":
        lang = _child_text(data, "SCRIPTLANGUAGE")
        var = _child_text(data, "VARNAME")
        synopsis = _script_synopsis(_child_text(data, "SCRIPT"))
        return ("step", f"RunEmbeddedScript [{lang}] {var}: {synopsis}{cond_suffix}")

    if a_type == "RunEmbeddedCmd":
        script = _child_text(data, "SCRIPT")
        first = next((l.strip() for l in script.splitlines()
                      if l.strip() and not l.strip().startswith(("@echo", "set ", "rem"))), "")
        return ("step", f"RunEmbeddedCmd: {first[:100]}{cond_suffix}")

    if a_type == "LaunchProcess":
        command = _child_text(data, "COMMAND")
        param = _child_text(data, "PARAM")
        rcs = _child_text(data, "RETURNCODES")
        rc = f"  [rc: {rcs}]" if rcs else ""
        return ("step", f"LaunchProcess: {command} {param}".strip() + rc + cond_suffix)

    if a_type == "EvalVar":
        var = _child_text(data, "VARNAME")
        source = _child_text(data, "SOURCE")
        name = ""
        for pe in (data.iter("PropertyEntry") if data is not None else ()):
            if _t(pe.find("Param")) == "Name":
                name = _t(pe.find("Value"))
        return ("step", f"EvalVar {var} = {source}({name})")

    if a_type == "TerminateProcess":
        return ("step", f"TerminateProcess: {_child_text(data, 'NAME')}")

    if a_type == "CopyFiles":
        return ("step", f"CopyFiles: {_child_text(data, 'SOURCE')} -> {_child_text(data, 'DESTINATION')}")

    if a_type == "Conditional":
        return ("step", f"Conditional{cond_suffix}")

    if a_type == "EndBDS":
        msg = _child_text(data, "RETURNMESSAGE")
        return ("step", f"EndBDS: \"{msg}\"{cond_suffix}")

    if a_type == "Wait":
        dur = ""
        for pe in (data.iter("PropertyEntry") if data is not None else ()):
            if _t(pe.find("Param")) == "Duration":
                dur = _t(pe.find("Value"))
        return ("step", f"Wait: {dur}s")

    if a_type == "Label":
        return ("step", f"Label: {_child_text(data, 'NAME')}")

    if a_type == "SetX64Mode":
        return None  # low-level filesystem-redirection toggle, not doc-worthy

    # Unknown/other action types: keep the type so nothing is silently lost.
    return ("step", f"{a_type}{cond_suffix}")


def extract_bds(path):
    """Parse a real .bds and return a compact structured digest dict."""
    root = ET.fromstring(Path(path).read_bytes())

    digest = {
        "script_version": root.get("Version", ""),
        "last_change": root.get("LastChange", ""),
        "info": {},
        "variables": [],
        "annotations": [],
        "includes": [],
        "flow": [],
    }

    info = root.find("./META/INFO")
    if info is not None:
        digest["info"] = {k: v for k, v in info.attrib.items() if v}

    actions = root.find("ACTIONS")
    if actions is None:
        return digest

    for action in actions.findall("ACTION"):
        a_type = action.get("type", "")
        disabled = action.get("comment", "0") == "1"
        data = action.find("DATA")
        level = action.get("level", "0")

        if a_type == "SetVar":
            digest["variables"].append({
                "name": _child_text(data, "VARNAME"),
                "value": _child_text(data, "VALUE"),
                "disabled": disabled,
            })
        elif a_type == "Comment":
            text = _child_text(data, "VALUE")
            if text:  # skip pure-whitespace spacer comments
                digest["annotations"].append({"text": text, "disabled": disabled})
        elif a_type == "IncludeBDS":
            digest["includes"].append({
                "filename": _child_text(data, "FILENAME"),
                "condition": _condition_str(action),
                "disabled": disabled,
            })
        else:
            summary = _summarize_action(action)
            if summary:
                digest["flow"].append({
                    "level": level,
                    "summary": summary[1],
                    "disabled": disabled,
                })

    return digest


def render_digest(digest):
    """Render the digest as compact, high-signal text for the prompt."""
    lines = []

    lines.append("### BDS metadata")
    lines.append(f"- Script format version: {digest['script_version']}")
    lines.append(f"- Last change: {digest['last_change']}")
    for k, v in digest["info"].items():
        lines.append(f"- INFO.{k}: {v}")

    lines.append("\n### Variables (SetVar)")
    for v in digest["variables"]:
        flag = "  (DISABLED)" if v["disabled"] else ""
        lines.append(f"- {v['name']} = {v['value']}{flag}")

    if digest["annotations"]:
        lines.append("\n### Annotations / metadata comments")
        for a in digest["annotations"]:
            flag = "  (DISABLED)" if a["disabled"] else ""
            lines.append(f"- {a['text']}{flag}")

    if digest["includes"]:
        lines.append("\n### Included BDS files (external - contents NOT in this file)")
        for inc in digest["includes"]:
            cond = f"  [when: {inc['condition']}]" if inc["condition"] else ""
            flag = "  (DISABLED)" if inc["disabled"] else ""
            lines.append(f"- {inc['filename']}{cond}{flag}")

    lines.append("\n### Action flow (in order; indented by nesting level)")
    for step in digest["flow"]:
        indent = "  " * int(step["level"] or 0)
        flag = "  (DISABLED)" if step["disabled"] else ""
        lines.append(f"{indent}- {step['summary']}{flag}")

    return "\n".join(lines)
