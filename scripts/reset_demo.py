#!/usr/bin/env python3
"""Resets the automation_target demo repo to a known-clean state before a
fresh demo - deletes stale branches (local always; remote only when they
don't back an open PR) and reports what's left.

Never touches open pull requests automatically - an open PR might be
someone's in-progress work, not clutter, so this always reports them and
leaves the decision to a human.

Read-only by default - nothing is deleted unless --yes is passed.

    python3 scripts/reset_demo.py                        # dry-run report
    python3 scripts/reset_demo.py --yes                  # actually clean up
    python3 scripts/reset_demo.py --yes --clear-outputs  # also clear each agent's output/ folder
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_DIR = ROOT / "automation_target"
REPO_SLUG = "mailtwojanacse/aqua-automation-factory-demo"
AGENT_OUTPUT_DIRS = [
    ROOT / "agent1_baramundi_doc" / "output",
    ROOT / "agent2_requirement_to_test" / "output",
    ROOT / "agent3_script_adaptation" / "output",
    ROOT / "agent4_review" / "output",
    ROOT / "agent5_execution_selfheal" / "output",
]


def run(cmd, cwd=None, check=True):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def working_tree_is_clean(repo_dir):
    return run(["git", "status", "--porcelain"], cwd=repo_dir) == ""


def sync_main(repo_dir):
    run(["git", "fetch", "origin", "main"], cwd=repo_dir)
    run(["git", "checkout", "main"], cwd=repo_dir)
    run(["git", "pull", "origin", "main"], cwd=repo_dir)


def parse_branch_list(raw, strip_origin_prefix=False):
    """Turn `git branch --format=%(refname:short)` output into a clean list,
    dropping main/HEAD markers. Pure/testable - no subprocess call here."""
    branches = []
    for line in raw.splitlines():
        b = line.strip()
        if not b or b in ("main", "origin/main", "origin/HEAD") or "HEAD ->" in b:
            continue
        if strip_origin_prefix and b.startswith("origin/"):
            b = b[len("origin/"):]
        branches.append(b)
    return branches


def split_branches_by_pr_protection(remote_branches, open_pr_branch_names):
    """Which remote branches are safe to delete (no open PR points at them)
    vs which must be kept. Pure/testable."""
    stale = [b for b in remote_branches if b not in open_pr_branch_names]
    kept = [b for b in remote_branches if b in open_pr_branch_names]
    return stale, kept


def local_branches(repo_dir):
    raw = run(["git", "branch", "--format=%(refname:short)"], cwd=repo_dir)
    return parse_branch_list(raw)


def remote_branches(repo_dir):
    raw = run(["git", "branch", "-r", "--format=%(refname:short)"], cwd=repo_dir)
    return parse_branch_list(raw, strip_origin_prefix=True)


def open_prs(repo_dir):
    raw = run(["gh", "pr", "list", "--repo", REPO_SLUG, "--state", "open",
               "--json", "number,title,headRefName,url"], cwd=repo_dir)
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="actually delete stale branches (default: report only)")
    parser.add_argument("--clear-outputs", action="store_true",
                         help="also clear each agent's output/ folder (prompts, logs, screenshots)")
    args = parser.parse_args()

    if not (REPO_DIR / ".git").exists():
        print(f"FAIL: {REPO_DIR} is not a git checkout.")
        sys.exit(1)

    if not working_tree_is_clean(REPO_DIR):
        print("FAIL: automation_target has uncommitted changes - resolve those first. "
              "A demo reset should never discard real work silently.")
        sys.exit(1)

    print("Syncing main...")
    sync_main(REPO_DIR)

    prs = open_prs(REPO_DIR)
    open_pr_branch_names = {pr["headRefName"] for pr in prs}

    remotes = remote_branches(REPO_DIR)
    remote_stale, remote_kept = split_branches_by_pr_protection(remotes, open_pr_branch_names)
    # Local branch deletion is PR-aware for the same reason as remote: a
    # branch backing an open PR might still be someone's local
    # work-in-progress, even though the remote copy is what matters for
    # the PR itself.
    local_stale, local_kept = split_branches_by_pr_protection(local_branches(REPO_DIR), open_pr_branch_names)

    print("\nmain: in sync with origin/main")
    print(f"Local branches other than main: {len(local_stale) + len(local_kept)} "
          f"({len(local_stale)} stale, {len(local_kept)} backing an open PR)")
    for b in local_stale:
        print(f"  - {b}  [stale - safe to delete]")
    for b in local_kept:
        print(f"  - {b}  [KEEP - backs an open PR]")
    print(f"Remote branches other than main: {len(remotes)} "
          f"({len(remote_stale)} stale, {len(remote_kept)} backing an open PR)")
    for b in remote_stale:
        print(f"  - {b}  [stale - safe to delete]")
    for b in remote_kept:
        print(f"  - {b}  [KEEP - backs an open PR]")

    if prs:
        print(f"\n{len(prs)} open pull request(s) - not touched, review these yourself:")
        for pr in prs:
            print(f"  #{pr['number']} {pr['title']}  {pr['url']}")
    else:
        print("\nNo open pull requests.")

    if not args.yes:
        print("\nDry-run - nothing deleted. Re-run with --yes to actually clean up.")
        return

    print("\nCleaning up...")
    for b in local_stale:
        run(["git", "branch", "-D", b], cwd=REPO_DIR, check=False)
        print(f"  deleted local branch {b}")
    for b in remote_stale:
        run(["git", "push", "origin", "--delete", b], cwd=REPO_DIR, check=False)
        print(f"  deleted remote branch {b}")

    if args.clear_outputs:
        for out_dir in AGENT_OUTPUT_DIRS:
            if not out_dir.exists():
                continue
            for item in out_dir.iterdir():
                if item.is_file():
                    item.unlink()
                else:
                    shutil.rmtree(item)
            print(f"  cleared {out_dir}")

    print("\nDone - automation_target is clean and ready for a fresh demo.")


if __name__ == "__main__":
    main()
