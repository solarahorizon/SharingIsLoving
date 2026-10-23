# shell-autofix

A Claude Code mod (a plugin made of TypeScript function hooks) that fixes a few Bash command
shapes instead of letting a guardrail refuse them. Before a Bash call runs, it rewrites the
command into the form your PreToolUse hook allows, sends it on, and adds one line to the result
saying what changed, so the agent learns the allowed form.

| The agent writes | The mod sends |
|---|---|
| `cd /abs/path && git <args>` (one git step) | `git -C /abs/path <args>` |
| `<cmd> 2>/dev/null` | `<cmd>` (the error text now shows in the result) |
| `<cmd>; echo $?` as the last step | `<cmd>` (the Bash result already carries the exit code) |

Anything else passes through untouched. The mod runs in front of your settings hooks, so your
hook still judges the command that will really run and still refuses what is left.

## Why it exists

We run coding agents unattended behind a PreToolUse hook that refuses shell shapes which trigger
permission prompts: `cd && git`, `2>/dev/null`, pipes into `head`, backticks. A prompt stalls an
unattended agent, so the hook denies the command and names the allowed form. Every refusal still
cost a model turn and a near-identical retry. Over one month (120 sessions, 50,707 Bash calls)
the hook said no 1,645 times.

A hook can only allow or deny. A mod can rewrite. The first version, replayed on that month of
refusals, would have fixed 54%. Review blocked it: it split chains like
`cd wt && rm -rf build` into separate calls, and each call starts back in the original folder.
The next version copied what `head` and `grep` do and reached 18%; review found another edge,
because every copy of a tool differs from the real one somewhere.

So the rule changed instead of the examples:

- rewrite only when the same command runs in the same folder
- never remove a pipe, never filter output in code
- read commands with an allowlist of characters whose meaning no shell option changes, and leave
  the whole command alone on anything else
- keep the old hook behind it

Replayed on the same 1,645 refusals, this version turns 65 (about 4%) into commands the hook
allows on the first try. Small on purpose: it is the version we trust. Most refusals were pipes
(904) and recursive grep (395), which this mod does not touch.

## Install

Requirements: Claude Code with mod support (built and tested on 2.1.289; check with
`claude --version`). It only helps if you run a PreToolUse hook that refuses these shapes;
without one, it has nothing to save you from.

Claude Code loads a plugin it finds in `~/.claude/skills/<name>` in every project and reloads it
when its files change. Copy or link this folder there:

```bash
ln -s /path/to/SharingIsLoving/skills/shell-autofix ~/.claude/skills/shell-autofix
claude plugin validate ~/.claude/skills/shell-autofix
claude plugin test ~/.claude/skills/shell-autofix
```

Expect `Validation passed` and every test passing. Then start a new session and ask the agent to
run `cd <some repo> && git status`. The status line shows `shell-autofix: 1 rewritten` and the
result carries a note starting `shell-autofix sent`. If your hook still refuses the rewritten
command, the result is that refusal, with the same note: the note says what was sent, never that
it ran.

To turn it off, remove the link and start a new session.

## Adapting it

- `hooks/rewrite.ts` is pure: `choose(command)` returns the rewritten command and its notes, or
  `undefined` to pass the call through. Add a rewrite there only if you can show the shell runs
  it the same way, and add a test for every shape it must leave alone.
- `hooks/register.ts` wires `choose` into the `tool.call` hook for Bash.
- The tests in `tests/` (`claude plugin test`) are the contract: 103 cases, most of them commands
  that must NOT be rewritten.

## Known limits

- It reads commands as zsh would and leaves alone anything whose meaning can change with a shell
  option: `$`, backticks, a backslash outside double quotes, `$'...'`, globs (including zsh's `^`
  and `#`), braces, `!`, a word starting with `=` or `~`, non-ASCII text outside quotes, or a
  redirect other than `>`, `>>`, `<` to a named file and `2>&1`. So `git log HEAD^` after a `cd`
  is not rewritten.
- A `cd` target must be an absolute path in plain characters, with no `.` or `..` segment.
  `cd wt`, `cd ~/x`, `cd /a/..` and quoted paths are left alone. A git step with any redirect is
  left alone too: after `-C` the file would open in the caller's folder.
- What the rewrite changes on purpose: error text hidden by `2>/dev/null` now shows; after a
  dropped `echo $?` the call fails when the command failed; a `cd` to a missing folder fails with
  git's exit code 128 instead of 1.
- What the mod cannot see, and so cannot rule out:
  - `git -C` does not run zsh `chpwd` hooks, which a `cd` does (for example direnv). If such a
    hook sets variables git reads, the rewritten command can behave differently.
  - An alias or shell function named `cd` or `git`, or a global alias (`alias -g`) that expands to
    a separator, runs differently after the rewrite.
  - A relative entry in `PATH` (such as `.`) makes the word `git` find a different program once
    the `cd` is gone.
  - A git hook that reads `$PWD` sees the caller's folder after `-C`, not the repo.

  On a machine with any of these, do not install it.
