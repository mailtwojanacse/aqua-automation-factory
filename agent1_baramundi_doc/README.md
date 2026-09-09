# Agent 1 — Baramundi Documentation Agent

First agent in the **Aqua Automation Factory** pipeline. It reads a Baramundi job's
artifacts (`.bds` deployment script, XML deployment configuration, and job configuration)
and produces the **single source of truth** markdown knowledge file that every downstream
agent (Requirement-to-Test, Script Adaptation, Review, Execution & Self-Healing) relies on.

## Pipeline position

```
[Agent 1] Baramundi Documentation  ->  Agent 2 Requirement-to-Test  ->  Agent 3 Script Adaptation
   (this repo)                          -> Agent 4 Review -> Agent 5 Execution & Self-Healing
```

## Output

By default Agent 1 writes one merged knowledge file per job (`<JobName>.md`), matching the
folder example on the client slide (`063 Aqua-Automation/Install_Adobe_Acrobat.md`). The
document follows this fixed template:

```
# Software Package (Name / Version)
## Purpose
## Preconditions
## Validation Rules
## Evidence
## Aqua Test Case Mapping   (TC-#### : description)
```

Pass `--split` to *also* emit the three separately-named files the Agent 1 box on the slide
lists — `README.md`, `requirements.md`, `testspec.md` — assembled from the merged document.
Keeping both paths lets the client decide between "one file per job" (folder example) and
"three files per job" (agent-box list) without a rewrite. **The section→file mapping in
`src/splitter.py` is an assumption pending client confirmation.**

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then add your ANTHROPIC_API_KEY
```

`.env` loads automatically (via `python-dotenv`, called at the top of `run_agentN.py`) - no need to `source` it or export vars by hand.

## Run (against the REAL client BDS)

```bash
python run_agent1.py \
  --bds sample_inputs/Adobe_Acrobat_Reader_DC/Install.bds \
  --xml-config sample_inputs/Adobe_Acrobat_Reader_DC/Install_config.xml \
  --job-config sample_inputs/Adobe_Acrobat_Reader_DC/Install_job.json \
  --output-dir output \
  --split
```

`Install.bds` is the real client export. `Install_config.xml` and `Install_job.json` are
**demo companions** created to test the 3-input flow (the client so far sent only the `.bds`);
their values mirror what's inside the real BDS. Replace them with real exports when available.

## Dry run (no API key needed)

Add `--dry-run` to assemble and write the exact prompt that *would* be sent to the LLM,
**without** calling the API. This needs neither `ANTHROPIC_API_KEY` nor the `anthropic`
package installed (the API import is lazy), so it's the way to demo the flow on the VM
before the key and network whitelisting are in place.

```bash
python run_agent1.py \
  --bds sample_inputs/Adobe_Acrobat_Reader_DC/Install.bds \
  --xml-config sample_inputs/Adobe_Acrobat_Reader_DC/Install_config.xml \
  --job-config sample_inputs/Adobe_Acrobat_Reader_DC/Install_job.json \
  --output-dir output --dry-run
# -> writes output/Install.prompt.txt (the full system + user prompt)
```

## How the real .bds is handled

A real `.bds` is a **procedural action script** (~80 `<ACTION type="...">` steps with embedded
PowerShell/batch), not a clean declarative document. `src/bds_extractor.py` distills it into a
compact, high-signal **digest** — variables (`SetVar`), metadata comments, external includes,
and the ordered action flow (conditions, return codes, nesting) — while collapsing large
embedded scripts to a one-line synopsis. On the real Adobe file this took the BDS content from
~33 KB to ~4 KB in the prompt (~85% smaller) with no loss of documentation-relevant signal.
Actions marked `comment="1"` are treated as **DISABLED** and flagged as such (assumption —
confirm with client). XML is parsed from bytes so the ISO-8859-1 declaration is honored
(German umlauts survive).

## Structure

```
run_agent1.py            CLI entry point
src/bds_extractor.py     Baramundi-aware distiller for real .bds action scripts (compact digest)
src/input_parser.py      Schema-tolerant XML/JSON/text loaders (byte-level, encoding-aware)
src/prompt_builder.py    Builds the system+user prompt from the BDS digest + configs + template
src/llm_client.py        Anthropic API wrapper (lazy import; --dry-run needs no key/package)
src/splitter.py          Splits the merged doc into README/requirements/testspec
src/doc_generator.py     Orchestration: extract -> generate -> write
templates/               The target markdown knowledge-file template
sample_inputs/Adobe_Acrobat_Reader_DC/   Real client Install.bds + demo config companions
sample_inputs/063_Aqua-Automation/        Original slide-reconstructed samples (superseded)
```

## Tests

Unit tests cover the pure mechanical logic - `.bds` parsing/digest rendering,
the doc-splitter, and the schema-tolerant XML/JSON/text loader - not the AI
call itself (no API key needed to run them):

```bash
pytest tests/ -v
```

## Known assumptions (validate with client)

1. **`.bds` is now handled against the REAL client schema** (see "How the real .bds is handled").
   The `disabled = comment="1"` interpretation and the demo XML/job companions still need client
   confirmation. Two things the BDS references but we do NOT have: (a) the 4 external
   `Include_Install_*.bds` files (their contents likely hold real preconditions / post-install
   validation), and (b) real XML Configuration + Job Configuration exports.
2. **One merged file vs. three files** — see Output above.
3. **`splitter.py` section mapping** — which template sections belong in requirements.md vs.
   testspec.md is a guess.
4. **`LLM_BACKEND` switch** (`.env`) — `anthropic_api` (default, needs `ANTHROPIC_API_KEY`),
   `openai_api` (ChatGPT, needs `OPENAI_API_KEY`), `azure_openai` (needs `AZURE_OPENAI_*`),
   or `claude_cli` (shells out to the already-logged-in `claude` CLI on this machine, no
   key needed - local dev/demoing only, not meant for the volume of an unattended
   production deployment). The VM must have whichever real endpoint is chosen whitelisted.
   GitHub Copilot and Cursor were considered but aren't wireable the same way - neither
   exposes a general-purpose completion API for a script like this to call.
```
