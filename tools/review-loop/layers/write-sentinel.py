#!/usr/bin/env python3
"""write-sentinel — write a review-loop sentinel = sha256(git diff --cached).

Used by the review RUNNERS to record a genuine pass in the ONE hash the gate
checks (never hand-write a sentinel; never hash the diff a second way).

  python3 write-sentinel.py last-dev-review-sha.txt      # after a Ready dev-review
  python3 write-sentinel.py last-vendor-review-sha.txt   # after a no-[P1] vendor pass

Writes docs/dev-review/<name> under the current repo. Exits non-zero (writes
nothing) if there is no staged diff.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import gatecore

# Only the two staged-diff sentinels. The merge sentinel (last-merge-review-sha.txt)
# is intentionally NOT here: it records the PR *head SHA*, not the staged-diff hash,
# so the merge runner writes it directly (e.g. `git rev-parse HEAD` on a clean
# cross-model pass) — writing a staged-diff hash there would never match the gate.
ALLOWED = {"last-dev-review-sha.txt", "last-vendor-review-sha.txt"}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ALLOWED:
        sys.exit(f"usage: write-sentinel.py <{'|'.join(sorted(ALLOWED))}>")
    name = sys.argv[1]
    root = gatecore.repo_root(os.getcwd())
    sha = gatecore.staged_sha(root)
    if not sha:
        sys.exit("write-sentinel: no staged diff — nothing to record.")
    d = os.path.join(root, "docs", "dev-review")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w") as f:
        f.write(sha + "\n")
    print(f"write-sentinel: {name} = {sha}")


if __name__ == "__main__":
    main()
