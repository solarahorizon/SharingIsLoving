#!/usr/bin/env python3
"""
pre-bash-discipline.py — the "clean shell" hook.

A Claude Code PreToolUse hook that keeps the agent's Bash commands in a shape
that never stalls an unattended run. It blocks a handful of command patterns and
tells the agent the prompt-free equivalent that does the same thing.

Why this exists
---------------
During an autonomous block (Claude working a backlog unattended for hours), the
failure modes aren't capability — they're operational. The worst one is silent:
a command shape that triggers a permission prompt the allowlist *cannot* silence,
or that hangs long enough to hit a stream-idle timeout. Either one stalls the
whole block waiting on a human who isn't there. "Just remember not to" failed
under context-decay, so this became a hard hook: the habit only holds during a
block if it holds in every session.

Each blocked pattern has a prompt-free equivalent that achieves the SAME result,
named in the deny message — so this is not a loss of capability, just a nudge
onto the road that skips the tollbooth.

Behaviour
---------
  - Reads the PreToolUse JSON payload from stdin.
  - Inspects Bash commands only; every other tool passes through untouched.
  - On a match: emits permissionDecision=deny with the corrected form.
  - On a clean command: exits 0 silently and the tool proceeds.

Install (per project, in .claude/settings.json)
-----------------------------------------------
  {
    "hooks": {
      "PreToolUse": [
        { "matcher": "Bash",
          "hooks": [{ "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/pre-bash-discipline.py\"" }] }
      ]
    }
  }

Bypass: disable it for a one-off by editing your local .claude/settings.local.json.
There is no inline waiver token — the point is that the shape is always wrong.

MIT-licensed. Adapt the patterns to your own stack (the last block shows how to
add your own, e.g. a long-running test command specific to your toolchain).
"""

import json
import re
import sys


# ── HEREDOC stripping ─────────────────────────────────────────────────────────
# Commit messages embedded via `<<'EOF' ... EOF` routinely contain text that
# LOOKS like a forbidden pattern ("don't use 2>/dev/null", "avoid `$(...)`")
# without being actual shell. Strip HEREDOC bodies before matching so
# documentation-style commit messages don't trip a false positive.
RE_HEREDOC = re.compile(r"<<\s*-?\s*['\"]?(\w+)['\"]?\s*\n.*?\n\1\s*$", re.DOTALL | re.MULTILINE)


def strip_heredocs(command: str) -> str:
    return RE_HEREDOC.sub("<<HEREDOC\n", command)


# ── Patterns ──────────────────────────────────────────────────────────────────
# Each entry: (compiled regex, human rule, prompt-free fix). Order is cosmetic.

# 1. `cd <dir> && git/gh` — trips the "untrusted hooks from target directory" prompt.
RE_CD_GIT = re.compile(r'\bcd\s+\S+\s*&&\s*(?:git|gh)\b')

# 2. Pipe to an output-processing command — the output is invisible to the tool
#    result and often huge. `| tee <file>` is left allowed as the log-capture form.
RE_PIPE_PROCESS = re.compile(r'\|\s*(?:head|wc|grep|tail|sort|uniq|awk|sed|cut)\b')

# 3. Stderr suppression — hides the very errors you need to see.
RE_STDERR_DEVNULL = re.compile(r'2>\s*/dev/null')

# 4. Command substitution `$(...)` — nesting hides a command the tool can't audit.
#    `$(cat <<'EOF'` is allowed: that's the documented heredoc commit-message form.
RE_CMD_SUBST = re.compile(r'\$\((?!cat\s+<<)')

# 5. Backticks — same problem as `$(...)`, no exception.
RE_BACKTICK = re.compile(r'`[^`]*`')

# 6. Sleep-poll loop — burns tokens and can idle past the stream timeout.
RE_SLEEP_LOOP = re.compile(r'\b(?:until|while)\b[^;]*\bsleep\b')

# 7. Exit-code reference `$?` — the Bash tool result already carries the exit code.
RE_EXIT_CODE = re.compile(r'\$\?')


def evaluate(command: str):
    """Return a list of (rule, fix) violations. Empty list = clean."""
    # Inspect shell STRUCTURE only — strip heredoc bodies first.
    command = strip_heredocs(command)
    checks = [
        (RE_CD_GIT,
         "cd <dir> && git/gh  — triggers the untrusted-hooks prompt",
         "Use `git -C <abs-path> <cmd>` (or `gh -R owner/repo <cmd>`) in a single call."),
        (RE_PIPE_PROCESS,
         "pipe to head/wc/grep/tail/sort/uniq/awk/sed/cut",
         "Use the Grep tool (output_mode \"count\" for counts) or the Read tool "
         "(offset+limit for line ranges). `| tee <file>` for log capture stays allowed."),
        (RE_STDERR_DEVNULL,
         "stderr suppression `2>/dev/null`",
         "Drop the redirect — clean stdout is enough, and you want to see errors."),
        (RE_CMD_SUBST,
         "command substitution `$(...)` (other than `$(cat <<'EOF' ... EOF)`)",
         "Run the inner command as its own call, read the output, then use the literal value."),
        (RE_BACKTICK,
         "backtick command substitution",
         "Same as `$(...)` — separate calls, literal values. No exception."),
        (RE_SLEEP_LOOP,
         "sleep-poll loop (`until/while ... sleep N`)",
         "Use the Monitor tool — it watches output and notifies on your condition "
         "without burning tokens."),
        (RE_EXIT_CODE,
         "exit-code reference `$?`",
         "Drop `; echo $?` — the Bash tool result already includes the exit code."),
    ]
    violations = []
    for rx, rule, fix in checks:
        if rx.search(command):
            violations.append((rule, fix))

    # ── Add your own ──────────────────────────────────────────────────────────
    # Gate a long-running foreground command specific to your stack so it can't
    # idle past the stream timeout. Example (uncomment + adapt):
    #
    #   run_bg = bool(payload_tool_input.get("run_in_background"))
    #   if re.search(r'\byour-test-runner\b.*\btest\b', command) and not run_bg:
    #       violations.append((
    #           "foreground long-running test — risks a stream-idle timeout",
    #           "Set run_in_background: true and pair with a ScheduleWakeup so you're "
    #           "notified when it finishes.",
    #       ))
    return violations


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # malformed payload — never block the agent

    if payload.get("tool_name") != "Bash":
        sys.exit(0)

    command = (payload.get("tool_input", {}) or {}).get("command", "") or ""
    violations = evaluate(command)
    if not violations:
        sys.exit(0)

    lines = ["BLOCKED by pre-bash-discipline.py (clean-shell) — prompt-free equivalents:", ""]
    for rule, fix in violations:
        lines.append(f"  - {rule}")
        lines.append(f"    Fix: {fix}")
        lines.append("")
    lines.append("Adjust the command and retry. To disable for a genuine one-off, edit "
                 ".claude/settings.local.json.")

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "\n".join(lines),
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
