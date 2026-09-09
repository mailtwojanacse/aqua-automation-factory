# Requirement Traceability Report

Answers the question an Allure test report and a live pipeline dashboard
both stop short of: **for a given requirement, was it actually implemented,
reviewed, and does it currently pass?**

Ties together three things that already exist separately in this pipeline
but were never joined into one view:

- the **requirement** (an Agent 3 input `.md`, where one drove the test)
- the **GitHub PR** that implemented it (live state via `gh pr view` — not
  a frozen snapshot)
- the most recent real **pass/fail result** for that test (from Agent 5's
  accumulated Allure results)
- a **trend** of the last 10 runs per test, so a test that's currently
  passing but has been flaky doesn't look identical to one that's been
  solid every time

## Why a manifest

Nothing in the pipeline currently records "this test function traces back
to that requirement" — Agent 2's Aqua test cases (deployment-level: return
codes, EULA handling, process termination) and the actual Playwright test
functions Agent 3/5 operate on (UI-verification level, on the demo's
install-confirmation stand-in page) are two different granularities that
don't line up 1:1 yet. `manifest.json` is the one place that link is
recorded by hand; everything else (PR state, test result) is looked up
live so the report never goes stale.

`manifest.json` is honest about gaps: 4 of the 10 tracked test cases have
a dedicated PR from a real Agent-3 run; the other 6 were mirrored directly
during the test-suite-growth refactor (same behavior, same requirement,
but no individual PR for that specific suite) — each says so in its `note`.

## Where the trend data comes from

No separate history-tracking of our own - `runner.generate_allure_report`
already carries Allure's `history/` folder forward across every build (the
Trend-chart idiom from the original Allure integration). Its `history.json`
keeps the last N runs per test, keyed by a stable `historyId` that's also on
every raw result file. `build_report.py` just joins the two: current result
-> its `historyId` -> that test's run history -> a sparkline of the last 10.

## Regenerating

Runs automatically after every Agent 5 invocation (see
`agent5_execution_selfheal/src/execution.py`). To run it by hand:

```bash
python3 build_report.py
```

Writes `report.json` (raw data) and `index.html` (the rendered view, served
by the dashboard at `http://localhost:8787/traceability/index.html`, and
linked from the dashboard's "Requirement Traceability" button).
