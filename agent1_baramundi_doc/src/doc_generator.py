"""Orchestrates Agent 1: parse Baramundi artifacts -> call the LLM -> write
the single-source-of-truth markdown knowledge file(s)."""
from pathlib import Path

from src import bds_extractor, events, input_parser, llm_client, prompt_builder, splitter

AGENT = "Agent 1"


def generate_job_docs(*args, **kwargs):
    try:
        return _generate_job_docs(*args, **kwargs)
    except Exception as exc:
        events.emit(AGENT, "error", f"Failed: {exc}")
        raise


def _generate_job_docs(bds_path, xml_config_path, job_config_path, output_dir, job_name=None, split=False, dry_run=False):
    job_name_hint = job_name or Path(bds_path).stem
    events.emit(AGENT, "start", f"Starting for job '{job_name_hint}'",
                {"bds": bds_path, "xml_config": xml_config_path, "job_config": job_config_path})

    bds_size = Path(bds_path).stat().st_size
    bds_digest = bds_extractor.extract_bds(bds_path)
    bds_digest_text = bds_extractor.render_digest(bds_digest)
    events.emit(AGENT, "mechanical", f"Distilled .bds into a compact digest ({bds_size} → {len(bds_digest_text)} chars)",
                {"raw_bytes": bds_size, "digest_chars": len(bds_digest_text)})

    xml_config = input_parser.load_any(xml_config_path)
    job_config = input_parser.load_any(job_config_path)

    job_name = job_name or Path(bds_path).stem

    system_prompt, user_prompt = prompt_builder.build_prompt(bds_digest_text, xml_config, job_config, job_name)
    events.emit(AGENT, "mechanical", f"Assembled prompt from BDS digest + XML config + job config + template ({len(system_prompt) + len(user_prompt)} chars)")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Dry run: write the exact prompt that WOULD be sent, without calling the API.
    # Lets the flow be demoed on the VM before the API key / whitelisting land.
    if dry_run:
        prompt_path = output_dir / f"{job_name}.prompt.txt"
        prompt_path.write_text(
            f"===== SYSTEM PROMPT =====\n{system_prompt}\n"
            f"\n===== USER PROMPT =====\n{user_prompt}\n",
            encoding="utf-8",
        )
        events.emit(AGENT, "ai_dry_run", "Dry-run: skipped the AI call, wrote the exact prompt instead",
                    {"path": str(prompt_path)})
        events.emit(AGENT, "done", "Finished (dry-run)")
        return {"dry_run_prompt": str(prompt_path)}

    events.emit(AGENT, "ai_call", "Calling the AI to write the knowledge document")
    merged_markdown = llm_client.generate(system_prompt, user_prompt)
    events.emit(AGENT, "ai_call", f"AI returned the knowledge document ({len(merged_markdown)} chars)")

    written = {}
    merged_path = output_dir / f"{job_name}.md"
    merged_path.write_text(merged_markdown, encoding="utf-8")
    written["merged"] = str(merged_path)
    events.emit(AGENT, "mechanical", f"Wrote merged knowledge file: {merged_path.name}")

    if split:
        parts = splitter.split_into_three(merged_markdown)
        for filename, content in parts.items():
            target = output_dir / f"{filename}.md"
            target.write_text(content, encoding="utf-8")
            written[filename] = str(target)
        events.emit(AGENT, "mechanical", "Split into readme/requirements/testspec files")
        if "requirements" in parts:
            events.emit(AGENT, "handoff", f"requirements.md ready for Agent 2 ({len(parts['requirements'])} chars)",
                        {"path": str(output_dir / "requirements.md")})

    events.emit(AGENT, "done", "Finished", {"written": list(written.keys())})
    return written
