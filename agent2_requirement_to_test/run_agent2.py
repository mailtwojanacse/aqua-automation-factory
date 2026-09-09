#!/usr/bin/env python3
"""CLI entry point for Agent 2 - Requirement-to-Test Agent.

Consumes the requirements.md that Agent 1 produces (via --split) and writes an
Aqua Test Center Import CSV.

Example:
    python run_agent2.py --requirements sample_inputs/requirements.md --output-dir output
    python run_agent2.py --requirements sample_inputs/requirements.md --output-dir output --dry-run
"""
import argparse
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")  # no-op if .env doesn't exist

from src.test_generator import generate_test_cases

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Generate Aqua Import CSV test cases from requirements.md.")
    parser.add_argument("--requirements", required=True, help="Path to requirements.md (from Agent 1)")
    parser.add_argument("--output-dir", default=str(ROOT / "output"), help="Directory to write outputs into")
    parser.add_argument("--output-name", default="aqua_import", help="Base name for output files")
    parser.add_argument("--dry-run", action="store_true",
                        help="Assemble and write the prompt without calling the LLM (no API key needed)")
    args = parser.parse_args()

    written = generate_test_cases(
        requirements_path=args.requirements,
        output_dir=args.output_dir,
        output_name=args.output_name,
        dry_run=args.dry_run,
    )

    print("Wrote:")
    for label, value in written.items():
        print(f"  {label}: {value}")


if __name__ == "__main__":
    main()
