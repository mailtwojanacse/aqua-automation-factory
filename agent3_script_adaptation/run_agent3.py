#!/usr/bin/env python3
"""CLI entry point for Agent 3 - Script Adaptation Agent (AI Copilot).

Example:
    python run_agent3.py --dry-run
    python run_agent3.py    # real run: needs ANTHROPIC_API_KEY + gh auth
"""
import argparse
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")  # no-op if .env doesn't exist

from src.adapter import adapt_script

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Adapt the automation script for a new requirement and open a PR.")
    parser.add_argument("--requirement", default=str(ROOT / "sample_inputs" / "new_requirement.md"),
                        help="Path to the new/changed requirement markdown")
    parser.add_argument("--repo-path", default=str(ROOT.parent / "automation_target"),
                        help="Path to the local checkout of the automation_target repo")
    parser.add_argument("--script", default="tests/test_install_verification.py",
                        help="Path (relative to --repo-path) of the script to adapt")
    parser.add_argument("--output-dir", default=str(ROOT / "output"), help="Directory to write outputs into")
    parser.add_argument("--dry-run", action="store_true",
                        help="Assemble and write the prompt without calling the LLM or touching git/GitHub")
    args = parser.parse_args()

    result = adapt_script(
        requirement_path=args.requirement,
        repo_path=args.repo_path,
        script_relpath=args.script,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
    )

    print("Result:")
    for label, value in result.items():
        print(f"  {label}: {value}")


if __name__ == "__main__":
    main()
