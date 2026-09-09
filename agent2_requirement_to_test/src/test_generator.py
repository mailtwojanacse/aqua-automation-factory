"""Orchestrates Agent 2: read requirements.md -> LLM -> Aqua Import CSV."""
import json
from pathlib import Path

from src import csv_writer, events, llm_client, prompt_builder

AGENT = "Agent 2"


def generate_test_cases(*args, **kwargs):
    try:
        return _generate_test_cases(*args, **kwargs)
    except Exception as exc:
        events.emit(AGENT, "error", f"Failed: {exc}")
        raise


def _generate_test_cases(requirements_path, output_dir, output_name="aqua_import", dry_run=False):
    events.emit(AGENT, "start", f"Starting from {Path(requirements_path).name}", {"requirements_path": requirements_path})

    requirements_markdown = Path(requirements_path).read_text(encoding="utf-8")
    events.emit(AGENT, "mechanical", f"Read requirements.md ({len(requirements_markdown)} chars)")

    system_prompt, user_prompt = prompt_builder.build_prompt(requirements_markdown)
    events.emit(AGENT, "mechanical", f"Assembled prompt with the JSON test-case schema ({len(system_prompt) + len(user_prompt)} chars)")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Dry run: write the prompt that WOULD be sent, without calling the API.
    if dry_run:
        prompt_path = output_dir / f"{output_name}.prompt.txt"
        prompt_path.write_text(
            f"===== SYSTEM PROMPT =====\n{system_prompt}\n"
            f"\n===== USER PROMPT =====\n{user_prompt}\n",
            encoding="utf-8",
        )
        events.emit(AGENT, "ai_dry_run", "Dry-run: skipped the AI call, wrote the exact prompt instead",
                    {"path": str(prompt_path)})
        events.emit(AGENT, "done", "Finished (dry-run)")
        return {"dry_run_prompt": str(prompt_path)}

    events.emit(AGENT, "ai_call", "Calling the AI to turn requirements into structured test cases")
    raw = llm_client.generate(system_prompt, user_prompt)
    data = csv_writer.parse_model_json(raw)
    test_cases = data.get("test_cases", [])
    events.emit(AGENT, "ai_call", f"AI returned {len(test_cases)} test cases as JSON")

    written = {}
    # Keep the intermediate JSON for traceability / debugging.
    json_path = output_dir / f"{output_name}.json"
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    written["json"] = str(json_path)

    csv_path = output_dir / f"{output_name}.csv"
    row_count = csv_writer.write_csv(test_cases, csv_path)
    written["csv"] = str(csv_path)
    written["test_cases"] = len(test_cases)
    written["csv_rows"] = row_count
    events.emit(AGENT, "mechanical", f"Wrote Aqua Import CSV: {csv_path.name} ({row_count} rows)")
    events.emit(AGENT, "handoff", f"{csv_path.name} ready to import into Aqua Test Center", {"path": str(csv_path)})
    events.emit(AGENT, "done", "Finished", {"test_cases": len(test_cases), "csv_rows": row_count})

    return written
