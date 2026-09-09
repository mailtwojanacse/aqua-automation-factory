# Agent 2 — Requirement-to-Test Agent

Second agent in the **Aqua Automation Factory** pipeline. It reads the `requirements.md`
that Agent 1 produces and generates structured functional test cases as an **Aqua Test
Center Import CSV**.

## Pipeline position

```
Agent 1 Baramundi Documentation  --(requirements.md)-->  [Agent 2] Requirement-to-Test  --(Aqua Import CSV)-->  Aqua Test Center
   (this repo)
```

## How it works

1. Read `requirements.md` (the Preconditions + Validation Rules sections from Agent 1).
2. Ask the LLM to turn each validation rule into a test case with concrete steps and
   explicit expected results, returned as **JSON** (not raw CSV).
3. Convert that JSON to the Aqua Import CSV **in code** (`src/csv_writer.py`), so CSV
   escaping is always correct. The intermediate JSON is also saved for traceability.

Why JSON-then-CSV instead of asking the model for CSV directly: models are unreliable at
CSV quoting/escaping (commas, quotes, newlines inside fields). Generating structured JSON
and writing the CSV deterministically eliminates a whole class of malformed-import bugs.

## Output

- `aqua_import.csv` — one row per test **step**; test-case-level fields (ID, Title,
  Description, Precondition, Priority) repeat on each step row (import-tool-friendly layout).
- `aqua_import.json` — the raw structured test cases, kept for debugging/traceability.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then add your ANTHROPIC_API_KEY
```

`.env` loads automatically (via `python-dotenv`, called at the top of `run_agentN.py`) - no need to `source` it or export vars by hand.

## Run

```bash
python run_agent2.py --requirements sample_inputs/requirements.md --output-dir output
```

## Dry run (no API key needed)

```bash
python run_agent2.py --requirements sample_inputs/requirements.md --output-dir output --dry-run
# -> writes output/aqua_import.prompt.txt (the full system + user prompt)
```

## Structure

```
run_agent2.py            CLI entry point
src/prompt_builder.py    Builds the prompt; defines the test-case JSON contract
src/csv_writer.py        Parses model JSON, writes the Aqua Import CSV (schema in AQUA_COLUMNS)
src/llm_client.py        Anthropic API wrapper (lazy import; --dry-run needs no key/package)
src/test_generator.py    Orchestration: read -> generate -> write JSON + CSV
sample_inputs/           Example requirements.md (matches Agent 1's --split output)
```

## Tests

Unit tests cover the pure mechanical logic - parsing the model's JSON
(including stray code fences) and building the Aqua Import CSV rows - not
the AI call itself (no API key needed to run them):

```bash
pytest tests/ -v
```

## Known assumptions (validate with client)

1. **Aqua Import CSV schema** — the columns in `src/csv_writer.py` (`AQUA_COLUMNS`) and the
   one-row-per-step layout are a reasonable guess, **not** confirmed against a real Aqua Test
   Center import template. Get the client's import template and adjust `AQUA_COLUMNS` + the
   row mapping. This is the single most important thing to confirm before real use.
2. **Test-case ID reuse** — if `requirements.md` carries TC-#### ids they're reused; otherwise
   `id` is left blank for Aqua to assign on import. Confirm which behaviour the client wants.
3. **Granularity** — currently each Validation Rule becomes a test step within one test case
   per requirements file. The client may instead want one test *case* per validation rule.
   Easy to switch in the prompt if so.
4. **`LLM_BACKEND` switch** (`.env`) — `anthropic_api` (default, needs `ANTHROPIC_API_KEY`),
   `openai_api` (ChatGPT, needs `OPENAI_API_KEY`), `azure_openai` (needs `AZURE_OPENAI_*`),
   or `claude_cli` (shells out to the already-logged-in `claude` CLI on this machine, no
   key needed - local dev/demoing only, not meant for the volume of an unattended
   production deployment). GitHub Copilot and Cursor aren't wireable the same way - neither
   exposes a general-purpose completion API for a script like this to call.
```
