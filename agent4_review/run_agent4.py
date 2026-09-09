#!/usr/bin/env python3
"""CLI entry point for Agent 4 - Automation Review Agent.

Example:
    python run_agent4.py --pr-number 1 --dry-run
    python run_agent4.py --pr-number 1    # real run: posts a real PR review
"""
import argparse
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")  # no-op if .env doesn't exist

from src.reviewer import review_pr

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Review a pull request raised by Agent 3.")
    parser.add_argument("--pr-number", required=True, type=int, help="GitHub PR number to review")
    parser.add_argument("--repo-path", default=str(ROOT.parent / "automation_target"),
                        help="Path to the local checkout of the automation_target repo")
    parser.add_argument("--output-dir", default=str(ROOT / "output"), help="Directory to write outputs into")
    parser.add_argument("--dry-run", action="store_true",
                        help="Assemble and write the prompt without calling the LLM or posting a review")
    args = parser.parse_args()

    result = review_pr(
        repo_path=args.repo_path,
        pr_number=args.pr_number,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
    )

    print("Result:")
    for label, value in result.items():
        print(f"  {label}: {value}")


if __name__ == "__main__":
    main()
