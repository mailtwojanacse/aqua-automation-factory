# Aqua Automation Factory — All 5 Agents
### A complete, plain-English guide to what we built, how it works, how to test it, and what comes next

*Last updated: 2026-08-12*

---

## 0. Read this first (the 30-second version)

We are building a **factory made of AI "workers" (agents)** that takes software-deployment
information from a tool called **Baramundi** and automatically turns it into **test
documentation, test cases, adapted automation scripts, code review, and self-healing test
execution** — with all changes tracked in Git and demonstrable via **real GitHub pull
requests**, not just simulated ones.

The full factory has **5 agents** in a line, and **all 5 now run locally**:

| Agent | Nickname | Takes in | Produces |
|-------|----------|----------|----------|
| **Agent 1** | Baramundi Documentation Agent | Baramundi job files (`.bds`, XML, job config) | A clean Markdown "knowledge file" (the single source of truth) |
| **Agent 2** | Requirement-to-Test Agent | The `requirements.md` from Agent 1 | An Aqua-ready **CSV of test cases** |
| **Agent 3** | Script Adaptation Agent (AI Copilot) | A changed requirement + the current automation script | An adapted script, committed on a branch, with a **real GitHub PR** opened |
| **Agent 4** | Automation Review Agent | The PR Agent 3 opened | A posted **approve / request-changes verdict** on that PR |
| **Agent 5** | Execution & Self-Healing Agent | The approved script | A real test run, screenshot + log evidence, and (on a broken selector) a **self-heal + follow-up PR** |

All five have a **safe "dry-run" mode** that works without any paid API key, and all five
have been **tested end-to-end** — including real branches, real PRs, and a real self-heal
cycle against a live (private) GitHub repo created for this demo.

**Why this order changed:** the original plan waited for the client's VM, API key, and Git
access before building Agents 3–5. We reversed that — build everything locally first, prove
the whole factory works end to end, then demo it to the client and get approval to move to
their VM. That's what this document now reflects.

---

## 1. The big picture — a real-world analogy

Imagine a **car factory assembly line**. A car body enters at one end, and at each station
a worker adds something — doors, engine, paint — until a finished car rolls out.

Our project is the same idea, but for **software testing paperwork and automation**:

```
Raw Baramundi files → [Agent 1] → knowledge doc → [Agent 2] → test-case CSV
   → [Agent 3] adapts the automation script → GitHub PR
   → [Agent 4] reviews the PR → approve/request changes
   → [Agent 5] runs the approved script → evidence, and self-heals broken selectors
```

- **Baramundi** is the client's tool that installs software on company computers.
- **Aqua Test Center** is the client's tool for managing tests.
- **GitHub** stands in for wherever the client's real Git server will be — the mechanics
  (branch, commit, PR, review, merge) are identical either way.
- **The agents** are small Python programs. Each one reads some files, asks an **AI model
  (Claude)** to do the "thinking" part, and writes out clean, structured files or performs a
  real Git/GitHub action for the next station.

**Why use AI at all?** The "thinking" steps — describing what a script does, turning rules
into test cases, adapting code to a new requirement, reviewing a diff, suggesting a fixed
selector — are language-and-judgment work. The mechanical parts (parsing files, writing
CSVs/branches/PRs, running pytest) stay in **plain code**, because code is 100% reliable and
AI is not. **This split — AI thinks, code acts — is the core design idea of the whole
project, and it now runs through all 5 agents, not just the first two.**

---

## 2. What each agent does (in plain English)

### Agent 1 — Baramundi Documentation Agent
**Job:** Be the *translator*. Reads Baramundi's technical files and writes a clean,
human-and-machine-friendly Markdown "single source of truth" document.

### Agent 2 — Requirement-to-Test Agent
**Job:** Be the *test author*. Reads `requirements.md` and writes actual test cases as an
Aqua-importable CSV. Uses the "AI returns JSON, code writes the CSV" trick to guarantee valid
output even when a test description contains commas or quotes.

### Agent 3 — Script Adaptation Agent (AI Copilot)
**Job:** Be the *developer*. When a requirement changes, it updates the Python
Playwright/pytest automation script to match — then does what a real developer would do
next: creates a branch, commits the change, pushes it, and **opens a real pull request** on
GitHub for someone (Agent 4, or a human) to review.

**Analogy:** Like a junior developer who reads a bug report, fixes the test, and opens a PR
instead of pushing straight to `main`.

**The clever bit:** the AI returns the *entire updated file* in one block (not a diff) — a
diff is harder for a model to get byte-perfect, and at this file size a full replacement is
just as easy to review on GitHub anyway.

### Agent 4 — Automation Review Agent
**Job:** Be the *reviewer*. Fetches the PR's diff, asks the AI to check it for code quality,
security, and whether it actually addresses the stated requirement (and only that
requirement), and posts a real, visible verdict on the PR.

**The clever bit (and a real constraint we hit):** GitHub will not let an account formally
"approve" or "request changes" on its own pull request. Since Agents 3 and 4 currently share
one GitHub identity for this local demo, Agent 4 posts its verdict as a clearly labelled PR
**comment** (`✅ APPROVE` / `❌ REQUEST CHANGES`) instead of using GitHub's native review
button. Once Agent 4 runs under its own bot identity in the client's real setup, this becomes
a one-line change back to a native review.

### Agent 5 — Execution & Self-Healing Agent
**Job:** Be the *test runner and firefighter*. Runs the approved script, saves a screenshot
and the pytest log as evidence, and — this is the "wow" feature — if the app's UI changed
enough that a button's id/class no longer matches, it doesn't just fail:

1. It notices the failure was specifically a "can't find this element" timeout (not some
   other kind of failure).
2. It shows the AI the broken selector plus the page's current HTML and asks for a
   replacement.
3. It **tries the fix and re-runs the test itself** before trusting it.
4. Only if the fix actually works does it commit it on a new branch and open a **follow-up
   PR** — so the fix is never silently applied to production code; it's always visible and
   reviewable, just like Agent 3's changes.

**Analogy:** Like a QA engineer who notices a test broke because a button got renamed,
figures out the new button, confirms the test passes with the fix, and opens a small PR
for the one-line change — rather than just marking the ticket "flaky" and moving on.

It also enforces the client's **folder allow-list rule** from the slide (only scripts inside
the approved test folder may run).

---

## 3. How we built it — the design decisions, explained

### 3.1 "AI thinks, code acts"
Now spans all 5 agents: AI writes docs, generates test-case JSON, adapts code, reviews diffs,
and suggests selector fixes. Code always does the part that must be exactly right — parsing,
CSV writing, git branching, PR creation, pytest execution, and *verifying* the AI's suggested
fix actually works before trusting it.

### 3.2 A safe "dry-run" mode, on every agent
Every agent has `--dry-run`. It does everything except the AI call and anything that depends
on real AI output (a commit, a PR, a posted review, an applied fix). This proves the entire
mechanical pipeline — parsing, prompt assembly, git operations up to the point that needs
real text, pytest execution, failure detection — works today, with zero cost and zero API key.

### 3.3 Full-file replacement instead of diffs (Agent 3)
Asking a model to produce a perfectly-formed unified diff is a common source of "almost
worked" failures. At the size of a single test script, having the model return the whole
updated file and letting `git diff` show the actual change on GitHub is simpler and more
reliable.

### 3.4 Verify before you commit (Agent 5's self-heal)
Agent 5 never trusts the AI's suggested selector blindly. It applies the fix on a *branch*,
re-runs the real test, and only pushes + opens a PR if the test actually passes afterward. A
failed self-heal attempt is discarded locally and reported honestly — nothing broken is ever
pushed.

### 3.5 Real GitHub, not a simulation
Agents 3, 4, and 5 operate on a real (private) GitHub repo —
[`aqua-automation-factory-demo`](https://github.com/mailtwojanacse/aqua-automation-factory-demo)
— created specifically to stand in for the client's eventual repo. Branches, commits, PRs,
and review comments are real and visible, not mocked. This makes the client demo concrete:
"here's the actual pull request the AI opened," not "here's a screenshot of what it would
look like."

### 3.6 A real target to adapt and run against
Agents 3 and 5 need something real to operate on. We built a tiny stand-in web app (an Adobe
Acrobat Reader DC "installation verification" page, matching the same job used in Agents 1/2's
sample data) with two versions: `v1` (matches the current script) and `v2` (simulates a later
app UI update that breaks a selector) — this is what makes Agent 5's self-heal demo
repeatable on demand rather than a one-off.

### 3.7 Everything else from Agents 1/2 still applies
Compact BDS digesting, encoding-safe parsing, "JSON not raw CSV/diff," lazy-imported AI
clients so `--dry-run` needs no `anthropic` package installed, and per-agent `.env.example` +
`requirements.txt` — all carried through unchanged into Agents 3–5.

---

## 4. What's actually on disk — the file map

```
Sample_Agent/
├── PROJECT_OVERVIEW.md              ← THIS document
│
├── automation_target/                          ← the "client repo" stand-in (pushed to GitHub)
│   ├── sample_app/
│   │   ├── install_confirmation_v1.html        ← baseline UI
│   │   └── install_confirmation_v2.html        ← simulated app-UI update (self-heal demo)
│   └── tests/
│       └── test_install_verification.py        ← the script Agent 3 adapts, Agent 5 runs
│
├── agent1_baramundi_doc/                    ← AGENT 1 (unchanged - see its own README)
├── agent2_requirement_to_test/              ← AGENT 2 (unchanged - see its own README)
│
├── agent3_script_adaptation/                ← AGENT 3
│   ├── run_agent3.py
│   ├── sample_inputs/new_requirement.md
│   └── src/
│       ├── prompt_builder.py                ← "adapt this script for this requirement"
│       ├── llm_client.py
│       ├── git_ops.py                       ← branch / commit / push / `gh pr create`
│       └── adapter.py                       ← the conductor
│
├── agent4_review/                           ← AGENT 4
│   ├── run_agent4.py
│   └── src/
│       ├── prompt_builder.py                ← review prompt + verdict JSON contract
│       ├── llm_client.py
│       └── reviewer.py                      ← gh pr diff -> verdict -> gh pr comment
│
├── agent5_execution_selfheal/               ← AGENT 5
│   ├── run_agent5.py
│   └── src/
│       ├── execution.py                     ← the conductor: run -> evidence -> self-heal
│       ├── runner.py                        ← pytest execution, screenshot, allow-list, failure detection
│       ├── heal_prompt_builder.py           ← "here's the broken selector + current HTML, fix it"
│       ├── llm_client.py
│       ├── self_healer.py                   ← patch -> re-verify -> commit/push/PR
│       └── git_ops.py
│
└── orchestrator/
    └── run_pipeline.py                      ← runs Agents 1→2→3→4→(approve+merge)→5 as one script
```

**Plain-English glossary of the recurring file names** (same as before, plus):
- **`git_ops.py`** — branch/commit/push and opening PRs, shelled out to the real `git`/`gh`
  command-line tools (no extra Python git library needed).
- **`execution.py` / `adapter.py` / `reviewer.py`** — each agent's "conductor" that calls
  everything in the right order.

---

## 5. How we tested it (and what the tests proved)

Same two-track approach as before — dry-run for the parts that don't need AI, and a
**"mocked AI" run** (a fake but realistic AI reply fed into the real code path) for the parts
that do, since no live API key exists yet. The mocked-AI runs still perform **real** git/GitHub
actions — only the AI's text is substituted.

**What the tests confirmed:**
- ✅ Agents 1 & 2 — unchanged, still pass as documented in their own READMEs.
- ✅ Agent 3 (mocked AI) — created a real branch, committed the adapted script, pushed, and
  opened a real PR:
  [`#1`](https://github.com/mailtwojanacse/aqua-automation-factory-demo/pull/1).
- ✅ Agent 4 (mocked AI) — fetched that PR's real diff, and posted a real, visible
  `✅ APPROVE` verdict comment on it.
- ✅ Agent 5 against `v1` — pytest passes cleanly; screenshot + log evidence written.
- ✅ Agent 5 against `v2` (dry-run) — correctly detects the broken `#verify-btn` selector and
  writes the exact self-heal prompt, without touching git or calling the AI.
- ✅ Agent 5 against `v2` (mocked AI) — applied the suggested `#confirm-install-btn` fix on a
  new branch, **re-ran the real test to confirm it actually passed**, then pushed and opened
  a real follow-up PR:
  [`#2`](https://github.com/mailtwojanacse/aqua-automation-factory-demo/pull/2).
- ✅ `orchestrator/run_pipeline.py --dry-run` — runs all 5 agents back-to-back with no
  crashes, including the correct fallback when Agent 1's dry-run doesn't produce a real
  `requirements.md` for Agent 2 to chain from.

**What we have NOT yet tested:** a real, live AI call producing real generated wording/code
(needs an `ANTHROPIC_API_KEY` — see Section 7), and the real client's Baramundi/Aqua/Git
environment.

---

## 6. How to run and test it yourself — top to bottom

### The whole pipeline, one command
```bash
cd orchestrator
python run_pipeline.py --dry-run                                   # full mechanical smoke test, no AI/git side effects
python run_pipeline.py --dry-run --target-page install_confirmation_v2.html   # see the self-heal path get detected
```
Once you have an `ANTHROPIC_API_KEY` and `gh auth status` is green:
```bash
python run_pipeline.py                                             # real run: opens/merges real PRs
python run_pipeline.py --target-page install_confirmation_v2.html  # real run ending in a real self-heal + PR
```
It pauses for a manual `y/N` confirmation before merging Agent 3's PR — the "Human Approval"
gate from the client's slide.

### Agents 1 & 2
See their own READMEs — unchanged.

### Agent 3
```bash
cd agent3_script_adaptation
python run_agent3.py --dry-run     # writes output/adapt.prompt.txt
python run_agent3.py               # real run: opens a real PR against automation_target
```

### Agent 4
```bash
cd agent4_review
python run_agent4.py --pr-number <n> --dry-run
python run_agent4.py --pr-number <n>          # real run: posts a real verdict comment
```

### Agent 5
```bash
cd agent5_execution_selfheal
python run_agent5.py                                                       # v1 -> passes
python run_agent5.py --target-page install_confirmation_v2.html --dry-run  # v2 -> detects break
python run_agent5.py --target-page install_confirmation_v2.html            # v2 -> self-heals + opens a PR
```

### Dashboard
See `dashboard/README.md` - runs as a `systemd --user` service so it
survives terminal/session restarts instead of needing a manual relaunch
each time. `http://localhost:8787/` once running.

### One-time setup for the target repo
```bash
cd automation_target
pip install -r requirements.txt
playwright install chromium
```

---

## 7. What is needed to continue (the honest gap list)

*Section 7 last refreshed 2026-09-02 — everything above is unchanged since
Aug 12; this section is checked and corrected regularly as work continues.*

### 7.1 Things only the client can give us (still the highest priority)
| # | What we need | Why it matters | Affects |
|---|--------------|----------------|---------|
| 1 | **The real Aqua Import CSV template** (exact column names) | Our CSV columns are a sensible guess | Agent 2 |
| 2 | **Which AI provider is approved** (Anthropic, OpenAI, Azure OpenAI - all three are already wired in and ready) + VM network whitelisting | No agent can call the AI for real until this is settled | All 5 |
| 3 | **The AI API key** for whichever provider is approved | Needed for any real (non-dry-run) output | All 5 |
| 4 | **The 4 missing `Include_Install_*.bds` files** and real XML/Job Configuration exports | Sharpens Agent 1's output; currently handled gracefully as "not specified" | Agent 1 |
| 5 | **The client's real Git server** (GitHub/GitLab/Azure DevOps) and how our machine/the VM reaches it | Agents 3-5 currently point at our own demo repo | Agents 3, 4, 5 |
| 6 | **The client's actual VM details** (OS, access method, network egress rules) | We now have a tested, documented deployment process (see `RUNBOOK.md`) - this item is just plugging in the client's specifics, not figuring out how to deploy | Deployment |

Items 2 and 3 are the one blocking dependency everything else in this list
sits behind - every agent already supports Anthropic, OpenAI, and Azure
OpenAI (`LLM_BACKEND` in `.env`), fully built and unit-tested, but none has
been exercised against a live key in this environment. As of this update
it's been about three and a half weeks with no response on which provider
is approved.

### 7.2 Small decisions to confirm with the client
- Same open items from Agents 1/2 (one file vs three, splitter mapping, test granularity,
  test-case ID reuse) — unchanged, see each agent's README.
- **Agent 4's review identity** — a formal GitHub "approve/request changes" (rather than a
  comment) requires Agent 4 to run under its own bot/service account, distinct from whatever
  account raises the PR. Already proven with two personal GitHub accounts in the demo; worth
  deciding whether the client wants two real service accounts the same way.
- **Agent 5's folder allow-list name** — hardcoded to `tests/` for the demo; should match the
  client's real approved folder (`063 Aqua-Automation` per the slide).

### 7.3 The next things to build
**All 5 agents are now built, and so is the production glue that doesn't
depend on client input:**
- ✅ **Durable audit trail + governance reporting** — a SQLite-backed event
  log (every agent action, browsable by run), a real Allure test-results
  report, and a requirement -> PR -> test-result traceability report, all
  served from the live dashboard.
- ✅ **Automatic triggering** — a file-watch inbox plus scheduled
  regression cycles, so the pipeline runs itself instead of needing a
  manual CLI invocation per job/requirement.
- ✅ **Multi-provider AI support** — Anthropic, OpenAI, and Azure OpenAI are
  all wired in and unit-tested (plus a no-key `claude_cli` mode for
  demoing without any of the above).
- ✅ **Deployment readiness** — dependency versions pinned, `.env` loading
  fixed and verified, a preflight health-check script, a dashboard
  `/health` endpoint, and a written ops runbook (`RUNBOOK.md`).
- ✅ **Security review** — a dedicated pass found and fixed a path-traversal
  gap and an AI-output code-injection path in self-heal; both closed and
  regression-tested.

**What's left is genuinely blocked on the client, not more building:**
  - Point Agents 3-5 at the client's real repo instead of the demo `automation_target`.
  - Get the AI-provider decision + API key so a real (non-dry-run) run can happen at all.
  - Plug the client's real VM details into the deployment process that's already documented.

---

## 8. One-paragraph summary for a busy manager

> All five planned AI agents for the Aqua Automation Factory are now built and running
> locally, end to end: **Agent 1** turns raw Baramundi files into trustworthy documentation;
> **Agent 2** turns that into Aqua-ready test cases; **Agent 3** adapts the automation script
> for a changed requirement and opens a real GitHub pull request; **Agent 4** reviews that PR
> and posts a verdict; **Agent 5** runs the approved script, captures evidence, and — the
> standout capability — self-heals a broken UI selector by asking the AI for a fix, verifying
> it actually works, and opening its own traceable follow-up PR. Everything runs today with a
> zero-cost dry-run mode, and the riskier mechanics (git branching, PR creation, test
> execution, self-heal verification) have been proven with real GitHub actions against a
> demo repo, not just simulated. What's left before client deployment is not more agent
> logic — it's pointing these same agents at the client's real repo, AI provider, and VM once
> those are approved.
