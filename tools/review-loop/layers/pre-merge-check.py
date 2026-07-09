#!/usr/bin/env python3
"""review-loop merge gate (PreToolUse) — block `gh pr merge` until the PR HEAD has
passed a cross-model review, for the project's configured merge_base.

Unlike the commit gate (which reviews each staged diff), this reviews the whole
PR's final state and binds approval to the PR head SHA — so a rebase/force-push/
extra commit after the last review re-blocks the merge. Fails CLOSED: once a merge
is detected, an unverifiable state denies (a merge we can't check must not proceed).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import gatecore


def deny(msg):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": msg,
        }
    }))
    sys.exit(0)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        sys.exit(0)
    ti = payload.get("tool_input")
    if not isinstance(ti, dict):
        sys.exit(0)
    command = ti.get("command")
    if not isinstance(command, str):
        sys.exit(0)

    # gatecore.merges_with_cwd is the SOLE authority — command-word aware, handles flags
    # between pr/merge, quotes, compound commands, and tracks `cd` so each merge is judged
    # against the repo Bash will actually run it in. Returns EVERY merge in the line. There
    # is deliberately NO raw-substring prefilter: quoting like `gh pr m"erge"` carries no
    # literal 'merge' substring yet still runs a merge, so we always tokenize.
    merges = gatecore.merges_with_cwd(command, os.getcwd())
    if not merges:
        if gatecore.simple_commands(command) or "gh" not in command:
            sys.exit(0)  # parses cleanly (not a merge) or clearly unrelated -> allow
        # Mentions gh + merge but won't tokenize -> can't rule out a real merge.
        deny("BLOCKED by review-loop merge gate — a possible `gh pr merge` could not be "
             "parsed to verify it. A merge that can't be verified must not proceed. "
             "Simplify the command, or merge outside the gated flow.")

    # Verify EVERY merge in the command, each against ITS effective repo. The sentinel is
    # a single local head SHA, so two heads can never both be verified — batching denies.
    for m, cwd in merges:
        if cwd is None:
            deny("BLOCKED by review-loop merge gate — this merge follows a directory change to "
                 "a path the gate can't resolve, so it can't verify the target repo. Run the "
                 "merge from its own shell (no inline `cd` to a variable/dynamic path).")
        if m["repo"] is not None:
            # -R/--repo/--hostname or GH_REPO/GH_HOST targets a (possibly different)
            # repo/host; this repo's local review sentinel can't attest to a PR there.
            deny("BLOCKED by review-loop merge gate — a `gh pr merge` targets another "
                 f"repo/host ({m['repo']}). This repo's review-loop can't verify a PR "
                 "elsewhere (the review sentinel is local). Merge outside the gated flow.")
        if m.get("auto"):
            # --auto defers the merge to GitHub; the head can advance past the verified
            # sentinel before it fires. Can't be gated at command time -> fail CLOSED.
            deny("BLOCKED by review-loop merge gate — `gh pr merge --auto` defers the merge, "
                 "so the PR head could change after this review. Re-run the cross-model review "
                 "on the final head and merge without --auto.")
        if m.get("stale"):
            # a `git push` earlier in the SAME command line can update the PR head after the
            # gate reads it below, so the head we'd verify is stale. Fail CLOSED.
            deny("BLOCKED by review-loop merge gate — a `git push` precedes this merge in the same "
                 "command line, which can change the PR head after review. Push and merge as "
                 "separate commands, re-reviewing the final head before merging.")

        root = gatecore.repo_root(cwd)
        cfg = gatecore.resolve(root)
        if not cfg:
            # A real merge, but config is unresolvable (malformed review-loop.json, or
            # config.py unimportable). Fail CLOSED: a merge we can't verify must not proceed.
            deny("BLOCKED by review-loop merge gate — could not resolve the project's "
                 "review-loop config (malformed .claude/review-loop.json, or an unreadable "
                 "install). A merge that can't be verified must not proceed. Fix the config, "
                 "or merge deliberately outside the gated flow.")
        if not cfg.get("layers", {}).get("merge_gate"):
            continue  # this repo doesn't gate merges -> this merge is fine
        merge_base = cfg.get("merge_base", "main")
        vendor = cfg.get("vendor", "codex")

        pr_ref = m["ref"]
        view = ["gh", "pr", "view"] + ([pr_ref] if pr_ref else []) + ["--json", "headRefOid,baseRefName,state"]
        r = gatecore._sh(view, root)
        if r is None or r.returncode != 0:
            deny("BLOCKED by review-loop merge gate — could not resolve the PR via `gh pr view` "
                 "(gh missing/unauthed, or no PR for this ref). A merge that can't be verified must "
                 "not proceed. Fix gh/auth, or merge deliberately outside the gated flow.")
        try:
            info = json.loads(r.stdout)
        except Exception:
            deny("BLOCKED by review-loop merge gate — unparseable `gh pr view` output.")

        if info.get("baseRefName") != merge_base:
            continue  # merging into a base we don't gate -> this merge is fine
        head = info.get("headRefOid")
        if head and gatecore._sentinel(root, "last-merge-review-sha.txt") == head:
            continue  # cross-model review matches this exact PR head -> verified

        deny(f"BLOCKED by review-loop merge gate — the PR head ({head}) has not passed a cross-model "
             f"review. Run the {vendor} review on the PR head; on a no-[P1] pass it writes "
             f"docs/dev-review/last-merge-review-sha.txt = the head SHA. Then retry the merge.")

    sys.exit(0)  # every merge in the command verified


if __name__ == "__main__":
    main()
