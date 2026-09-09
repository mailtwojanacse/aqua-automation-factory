#!/usr/bin/env python3
"""CLI entry point for Agent 1 - Baramundi Documentation Agent.

Example:
    python run_agent1.py \\
        --bds sample_inputs/063_Aqua-Automation/Install_Adobe_Acrobat.bds \\
        --xml-config sample_inputs/063_Aqua-Automation/Install_Adobe_Acrobat_config.xml \\
        --job-config sample_inputs/063_Aqua-Automation/Install_Adobe_Acrobat_job.json \\
        --output-dir output \\
        --split
"""
import argparse
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")  # no-op if .env doesn't exist

from src.doc_generator import generate_job_docs

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Generate the Baramundi job knowledge file(s).")
    parser.add_argument("--bds", required=True, help="Path to the .bds deployment script")
    parser.add_argument("--xml-config", required=True, help="Path to the XML deployment configuration")
    parser.add_argument("--job-config", required=True, help="Path to the job configuration file")
    parser.add_argument("--output-dir", default=str(ROOT / "output"), help="Directory to write output markdown into")
    parser.add_argument("--job-name", default=None, help="Override the job name (defaults to the .bds filename)")
    parser.add_argument("--split", action="store_true", help="Also write README.md/requirements.md/testspec.md")
    parser.add_argument("--dry-run", action="store_true",
                        help="Assemble and write the prompt without calling the LLM (no API key needed)")
    args = parser.parse_args()

    written = generate_job_docs(
        bds_path=args.bds,
        xml_config_path=args.xml_config,
        job_config_path=args.job_config,
        output_dir=args.output_dir,
        job_name=args.job_name,
        split=args.split,
        dry_run=args.dry_run,
    )

    print("Wrote:")
    for label, path in written.items():
        print(f"  {label}: {path}")


if __name__ == "__main__":
    main()
