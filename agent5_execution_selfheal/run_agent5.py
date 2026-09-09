#!/usr/bin/env python3
"""CLI entry point for Agent 5 - Execution & Self-Healing Agent.

Example:
    python run_agent5.py                                                  # v1 page -> passes
    python run_agent5.py --target-page install_confirmation_v2.html --dry-run
    python run_agent5.py --target-page install_confirmation_v2.html       # real self-heal + follow-up PR
"""
import argparse
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")  # no-op if .env doesn't exist

from src.execution import execute

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Run the automation script and self-heal broken locators.")
    parser.add_argument("--repo-path", default=str(ROOT.parent / "automation_target"),
                        help="Path to the local checkout of the automation_target repo")
    parser.add_argument("--script", default="tests/test_install_verification.py",
                        help="Path (relative to --repo-path) of the script to run - must be under tests/")
    parser.add_argument("--target-page", default="install_confirmation_v1.html",
                        help="Which sample_app page to point the test at")
    parser.add_argument("--output-dir", default=str(ROOT / "output"), help="Directory to write logs/screenshots into")
    parser.add_argument("--dry-run", action="store_true",
                        help="On a broken-locator failure, write the self-heal prompt instead of calling the LLM/git")
    args = parser.parse_args()

    result = execute(
        repo_path=args.repo_path,
        script_relpath=args.script,
        target_page=args.target_page,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
    )

    print("Result:")
    for label, value in result.items():
        print(f"  {label}: {value}")


if __name__ == "__main__":
    main()
