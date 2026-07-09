#!/usr/bin/env python3
"""review-loop native git pre-commit hook — the un-skippable layer.

Installed into a project's .git/hooks/pre-commit (via a shim install.sh writes).
Unlike the PreToolUse gate, this fires at the git layer for EVERY committer —
sub-agents, `git add && git commit` one-liners, a human at the terminal — closing
the paths a tool-level hook can't see. Shares check logic with the PreToolUse gate
via gatecore, so both enforce identically.

Only enforces when the project's config has native_git_hook = true. Exit 1 blocks
the commit; `git commit --no-verify` is the deliberate, visible bypass.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import gatecore


def main():
    root = gatecore.repo_root(os.getcwd())
    cfg = gatecore.resolve(root)
    if not cfg:
        sys.exit(0)  # unresolvable config -> fail open
    layers = cfg.get("layers", {})
    if not layers.get("native_git_hook"):
        sys.exit(0)  # this project didn't opt into the hard hook
    need_dev = bool(layers.get("dev_review"))
    need_vendor = bool(layers.get("cross_vendor_commit"))
    if not (need_dev or need_vendor):
        sys.exit(0)

    missing = gatecore.commit_missing(root, need_dev, need_vendor)
    if not missing:
        sys.exit(0)

    sys.stderr.write("\n✗ commit BLOCKED by review-loop (native git hook) — "
                     "required review(s) not done on the staged diff:\n\n")
    for m in missing:
        sys.stderr.write(f"  - {m}\n")
    sys.stderr.write(
        "\nRun the review(s) so the docs/dev-review sentinel(s) match `git diff --cached`, then "
        "retry. Deliberate one-off bypass: `git commit --no-verify`.\n\n"
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
