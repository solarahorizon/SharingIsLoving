#!/usr/bin/env python3
"""review-loop commit gate (PreToolUse) — fast in-session feedback.

Wired as a PreToolUse(Bash) hook by install.sh. On a `git commit`, it blocks until
the review sentinels required by the project's enabled layers match the EXACT
staged diff. Shares its check logic with the native git hook via gatecore, so the
two enforce identically. Fails OPEN on any error.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import gatecore

# Fallback ONLY: used when the command line won't shlex-tokenize. Primary detection
# is gatecore.git_subcommand (quote- and compound-command robust). In the `standard`
# profile this PreToolUse hook is the sole commit gate, so detection must not be
# bypassable by quoted/global-option forms like `git -c user.name='Build Bot' commit`.
RE_GIT_COMMIT = re.compile(r'\bgit\b.*\bcommit(?![\w-])')


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
    if not isinstance(command, str) or "git" not in command:
        sys.exit(0)  # no git invocation possible without the word (obfuscation -> native hook)

    # Each commit is judged against the directory Bash will actually run it in (cd-aware).
    entries = gatecore.commits_with_cwd(command, os.getcwd())
    if not entries:
        # parse fallback: if the line won't tokenize but looks like a commit, gate it
        # as a plain index commit in the current dir.
        if not gatecore.simple_commands(command) and RE_GIT_COMMIT.search(command):
            entries = [(None, os.getcwd())]
        else:
            sys.exit(0)

    for reason, cwd in entries:
        if cwd is None:
            # a `cd` to an unresolvable dir precedes this commit — can't tell which repo
            # it lands in, so the sentinel can't attest to it. Fail closed.
            deny("BLOCKED by review-loop commit gate — this commit follows a directory change "
                 "to a path the gate can't resolve, so it can't verify the target repo. Run the "
                 "commit from its own shell (no inline `cd` to a variable/dynamic path).")
        if reason:
            # content that isn't the reviewed index (-a/--all, pathspec, interactive, cross-repo)
            deny("BLOCKED by review-loop commit gate — this commit's content isn't the reviewed "
                 "staged index: " + reason + ". Stage explicitly with `git add` in that repo, then "
                 "run a plain `git commit`.")

    # Sentinel check per commit, resolved against ITS effective repo.
    for _, cwd in entries:
        root = gatecore.repo_root(cwd)
        cfg = gatecore.resolve(root)
        if not cfg:
            continue
        layers = cfg.get("layers", {})
        need_dev = bool(layers.get("dev_review"))
        need_vendor = bool(layers.get("cross_vendor_commit"))
        if not (need_dev or need_vendor):
            continue
        missing = gatecore.commit_missing(root, need_dev, need_vendor)
        if not missing:
            continue
        reason = ["BLOCKED by review-loop commit gate — required review(s) not done on THIS staged diff:", ""]
        reason += [f"  - {m}" for m in missing]
        reason += [
            "",
            "Run the missing review(s) so the sentinel(s) under docs/dev-review/ equal the sha256 of "
            "`git diff --cached`, then retry. Do NOT hand-write a sentinel — the reviewing agent / gate "
            "writes it on a genuine pass. Doc-only commits (all files *.md/*.txt or under docs/) are exempt.",
        ]
        deny("\n".join(reason))
    sys.exit(0)


if __name__ == "__main__":
    main()
