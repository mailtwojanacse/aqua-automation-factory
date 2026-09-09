#!/usr/bin/env python3
"""Builds the requirement -> test -> PR -> result traceability report.

Ties together three things that already exist separately in this pipeline
but were never joined into one view:
  - the requirement (an Agent 3 input .md, if one drove this test)
  - the GitHub PR that implemented it (live state via `gh pr view`)
  - the most recent real pass/fail result for that test (from Agent 5's
    accumulated Allure results)

manifest.json holds the one piece nothing else can derive automatically -
which requirement/PR a given test function traces back to. Everything else
here is looked up live so the report reflects current reality, not a
snapshot frozen at manifest-authoring time.

Run standalone (`python3 build_report.py`) or via Agent 5, which calls this
after every run so the report never goes stale.
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "manifest.json"
ALLURE_RESULTS_DIR = ROOT.parent / "agent5_execution_selfheal" / "allure-results"
ALLURE_HISTORY_PATH = ROOT.parent / "agent5_execution_selfheal" / "allure-report" / "history" / "history.json"
TREND_WINDOW = 10


def _latest_test_results(results_dir):
    """fullName -> {status, stop, history_id} for the most recent result per
    test.

    Multiple result files can exist per test now that Agent 5 no longer
    clears allure-results/ between runs (needed so the report covers both
    suites) - keep only the one with the latest 'stop' timestamp. historyId
    is stable across runs (that's the whole point of it - it's how Allure
    itself tracks a test's identity over time), so it's the same regardless
    of which result file we pull it from.
    """
    latest = {}
    if not results_dir.exists():
        return latest
    for path in results_dir.glob("*-result.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        full_name = data.get("fullName")
        if not full_name:
            continue
        stop = data.get("stop", 0)
        if full_name not in latest or stop > latest[full_name]["stop"]:
            latest[full_name] = {
                "status": data.get("status", "unknown"),
                "stop": stop,
                "history_id": data.get("historyId"),
            }
    return latest


def _load_history():
    """Allure's own per-test run history (historyId -> {statistic, items}),
    carried forward across every generate_allure_report call since it was
    built - reused here instead of tracking our own, since Allure already
    keeps exactly the per-run status/timestamp sequence a trend needs."""
    if not ALLURE_HISTORY_PATH.exists():
        return {}
    try:
        return json.loads(ALLURE_HISTORY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _trend_for(history_id, history_data, limit=TREND_WINDOW):
    """Last `limit` runs for one test, oldest first. Allure's history.json
    lists items most-recent-first, so slice before reversing."""
    if not history_id or history_id not in history_data:
        return []
    items = history_data[history_id].get("items", [])
    recent = items[:limit]
    recent.reverse()
    return [{"status": item.get("status", "unknown"), "start": item.get("time", {}).get("start")}
            for item in recent]


def _pr_state(repo, pr_number):
    if pr_number is None:
        return None
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--repo", repo,
             "--json", "number,state,mergedAt,url,title"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {"number": pr_number, "error": result.stderr.strip()}
        return json.loads(result.stdout)
    except Exception as exc:
        return {"number": pr_number, "error": str(exc)}


def build_report():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    repo = manifest["repo"]
    results = _latest_test_results(ALLURE_RESULTS_DIR)
    history_data = _load_history()

    rows = []
    for entry in manifest["entries"]:
        script_module = Path(entry["script"]).stem
        full_name = f"tests.{script_module}#{entry['test_function']}"
        result = results.get(full_name)
        trend = _trend_for(result["history_id"], history_data) if result else []

        rows.append({
            **entry,
            "full_name": full_name,
            "pr": _pr_state(repo, entry.get("pr_number")),
            "last_result": result,
            "trend": trend,
            "trend_pass_rate": f"{sum(1 for t in trend if t['status'] == 'passed')}/{len(trend)}" if trend else None,
        })

    covered = sum(1 for r in rows if r["pr"] is not None)
    passing = sum(1 for r in rows if r["last_result"] and r["last_result"]["status"] == "passed")
    # "Flaky" here means both a pass and a non-pass appear somewhere in the
    # trend window - a test that's simply been failing consistently isn't
    # flaky, it's just broken, and shows up via `passing` instead.
    flaky = sum(1 for r in rows if r["trend"] and
                len({t["status"] == "passed" for t in r["trend"]}) > 1)

    report = {
        "repo": repo,
        "rows": rows,
        "summary": {
            "total": len(rows),
            "with_dedicated_pr": covered,
            "passing": passing,
            "flaky": flaky,
        },
    }

    (ROOT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (ROOT / "index.html").write_text(_render_html(report), encoding="utf-8")
    return report


def _status_pill(label, kind):
    return f'<span class="pill {kind}">{label}</span>'


def _pr_cell(pr):
    if pr is None:
        return _status_pill("no dedicated PR", "muted")
    if "error" in pr:
        return _status_pill(f"PR #{pr['number']} (lookup failed)", "muted")
    state = pr["state"]
    kind = "pass" if state == "MERGED" else ("fail" if state == "CLOSED" else "running")
    return f'<a href="{pr["url"]}" target="_blank">#{pr["number"]}</a> ' + _status_pill(state.title(), kind)


def _result_cell(result):
    if result is None:
        return _status_pill("no result yet", "muted")
    status = result["status"]
    kind = "pass" if status == "passed" else "fail"
    return _status_pill(status, kind)


def _trend_cell(trend, pass_rate):
    if not trend:
        return '<span class="dim">not enough history yet</span>'
    dots = "".join(
        f'<span class="dot {"pass" if t["status"] == "passed" else "fail"}" '
        f'title="{t["status"]}"></span>'
        for t in trend
    )
    return f'<div class="trend">{dots}</div><div class="dim">{pass_rate} last {len(trend)} runs</div>'


def _render_html(report):
    rows_html = []
    for r in report["rows"]:
        req_cell = r["requirement_title"]
        if r["requirement_file"]:
            req_cell += f'<div class="dim">{r["requirement_file"]}</div>'
        if r["note"]:
            req_cell += f'<div class="note">{r["note"]}</div>'
        rows_html.append(f"""
        <tr>
          <td>{req_cell}</td>
          <td><code>{r["script"]}</code><div class="dim">{r["test_function"]}</div></td>
          <td>{_pr_cell(r["pr"])}</td>
          <td>{_result_cell(r["last_result"])}</td>
          <td>{_trend_cell(r["trend"], r["trend_pass_rate"])}</td>
        </tr>""")

    summary = report["summary"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Requirement Traceability - Aqua Automation Factory</title>
<style>
  :root {{
    --bg: #0f1420; --panel: #171d2c; --border: #2a3247;
    --text: #e8ecf4; --dim: #8a92a6;
    --pass: #3fb98a; --fail: #e0556f; --running: #d9a441; --muted: #3a4258;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    padding: 28px;
  }}
  h1 {{ font-size: 18px; margin: 0 0 4px; font-weight: 600; }}
  .sub {{ color: var(--dim); font-size: 13px; margin-bottom: 20px; }}
  .summary {{ display: flex; gap: 12px; margin-bottom: 20px; }}
  .stat {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px 18px; min-width: 120px;
  }}
  .stat .n {{ font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }}
  .stat .l {{ font-size: 12px; color: var(--dim); margin-top: 2px; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--panel);
           border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
  th, td {{ text-align: left; padding: 10px 14px; border-bottom: 1px solid var(--border);
            font-size: 13px; vertical-align: top; }}
  th {{ color: var(--dim); font-weight: 600; font-size: 12px; text-transform: uppercase;
        letter-spacing: 0.03em; }}
  tr:last-child td {{ border-bottom: none; }}
  code {{ font-family: "SF Mono", Consolas, monospace; font-size: 12px; }}
  .dim {{ color: var(--dim); font-size: 12px; margin-top: 3px; }}
  .note {{ color: var(--dim); font-size: 12px; margin-top: 4px; font-style: italic; max-width: 42ch; }}
  a {{ color: #7fb0ff; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .pill {{
    display: inline-block; padding: 2px 8px; border-radius: 999px;
    font-size: 11px; font-weight: 600; text-transform: capitalize;
  }}
  .pill.pass {{ background: rgba(63,185,138,0.18); color: var(--pass); }}
  .pill.fail {{ background: rgba(224,85,111,0.18); color: var(--fail); }}
  .pill.running {{ background: rgba(217,164,65,0.18); color: var(--running); }}
  .pill.muted {{ background: rgba(58,66,88,0.4); color: var(--dim); }}
  .trend {{ display: flex; gap: 3px; align-items: center; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex: none; }}
  .dot.pass {{ background: var(--pass); }}
  .dot.fail {{ background: var(--fail); }}
</style>
</head>
<body>
  <h1>Requirement Traceability</h1>
  <div class="sub">Aqua Automation Factory - {report["repo"]}</div>
  <div class="summary">
    <div class="stat"><div class="n">{summary["total"]}</div><div class="l">test cases tracked</div></div>
    <div class="stat"><div class="n">{summary["with_dedicated_pr"]}</div><div class="l">with a dedicated PR</div></div>
    <div class="stat"><div class="n">{summary["passing"]}</div><div class="l">currently passing</div></div>
    <div class="stat"><div class="n">{summary["flaky"]}</div><div class="l">flaky (mixed pass/fail recently)</div></div>
  </div>
  <table>
    <thead>
      <tr><th>Requirement</th><th>Test</th><th>Pull Request</th><th>Last Result</th><th>Trend</th></tr>
    </thead>
    <tbody>{"".join(rows_html)}</tbody>
  </table>
</body>
</html>
"""


if __name__ == "__main__":
    report = build_report()
    print(f"Wrote report.json + index.html "
          f"({report['summary']['passing']}/{report['summary']['total']} passing, "
          f"{report['summary']['with_dedicated_pr']} with a dedicated PR)")
