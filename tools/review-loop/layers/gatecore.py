"""gatecore — shared review-loop check logic.

Imported by BOTH the PreToolUse commit gate (pre-commit-check.py) and the native
git pre-commit hook (native-pre-commit.py) so the two enforce IDENTICALLY — the
whole point of the framework is one definition, no drift. Also used by the merge
gate for config resolution.

Every function fails OPEN (returns "allow"/empty/None on any error) — a gate that
can't decide must never block real work.
"""
import hashlib
import os
import shlex
import subprocess
import sys

# make review-loop/config.py importable regardless of who invokes us
_RL_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if _RL_DIR not in sys.path:
    sys.path.insert(0, _RL_DIR)
try:
    import config as _config
except Exception:
    _config = None

DOC_SUFFIX = (".md", ".txt")
DOC_EXACT = {".gitignore", "LICENSE", "CHANGELOG", "CHANGELOG.md"}

# ---- command detection (quote- and compound-command robust) --------------------
# Both gates match a git/gh invocation out of a raw Bash string. A regex on the raw
# string breaks on quoted option values (`git -c user.name='Build Bot' commit`) and
# on compound commands (`git merge x && gh pr merge`). We tokenize with shlex and
# inspect subcommands instead, so quoting and `&&`/`;`/`|` are handled correctly.
# git global options that consume a SEPARATE value token (skip the value when
# scanning for the subcommand). `-c name=value` uses a separate `name=value` token.
_GIT_VALUE_OPTS = {"-C", "-c", "--exec-path", "--git-dir", "--work-tree", "--namespace"}
# `gh pr merge` flags that take a value (skip it when hunting for the PR ref).
_GH_MERGE_VALUE_FLAGS = {"-t", "--subject", "-b", "--body", "-F", "--body-file",
                         "--author-email", "--match-head-commit", "-R", "--repo"}
# gh options that take a value and can appear before/among the pr/merge words.
_GH_VALUE_OPTS = {"-R", "--repo"}
# command wrappers that precede the real command (`sudo git commit`, `env git ...`).
_CMD_WRAPPERS = {"command", "builtin", "exec", "env", "sudo", "nohup", "nice",
                 "time", "stdbuf", "setsid", "xargs", "timeout", "gtimeout"}
# wrapper options that CONSUME a separate value (so the value isn't mistaken for the
# real command word — `sudo -u root git commit`, `env -u NAME gh ...`, `timeout -s X`).
_WRAPPER_VALUE_FLAGS = {
    "-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-U",
    "--other-user", "-r", "--role", "-t", "--type", "-C", "--close-from", "--unset",
    "-S", "--split-string", "--chdir", "-P", "-n", "--adjustment", "-I", "--replace",
    "--max-args", "-L", "--max-lines", "--max-procs", "-s", "--signal", "-k",
    "--kill-after", "-d", "-E", "-a", "-o", "-e", "-i", "--input", "--output", "--error",
}
# wrappers whose FIRST positional is a value, not the command (`timeout 300 git ...`).
_WRAPPER_DURATION = {"timeout", "gtimeout"}
# shell keywords/control words that can prefix a command in a simple-command segment
# (`if gh pr merge; then ...`, `! gh pr merge`, `{ git commit; }`).
_SHELL_KEYWORDS = {"if", "then", "else", "elif", "fi", "while", "until", "do", "done",
                   "case", "esac", "in", "!", "{", "}", "coproc", "function"}
_OP_CHARS = set("&|;()<>")


def simple_commands(command):
    """Split a Bash command line into simple commands (token lists), honoring quotes
    AND shell operators even when unspaced (`a&&b`). `git x && gh y` ->
    [['git','x'], ['gh','y']]. [] on parse error (caller then fails open)."""
    # A newline is a Bash command separator (like `;`); shlex only treats it as
    # whitespace, so normalize it ourselves — first fold `\<newline>` continuations, then
    # turn real newlines into separators — else `git add .\ngit commit` reads as one
    # command and the commit hides. (A newline inside quotes becomes literal ` ; ` text
    # in that token, which is harmless for detection.)
    command = command.replace("\r\n", "\n").replace("\r", "\n")
    command = command.replace("\\\n", " ").replace("\n", " ; ")
    # Normalize Bash ANSI-C ($'...') and locale ($"...") quoting to ordinary quotes so
    # `git $'commit'` / `gh pr $'merge'` tokenize to the real subcommand words (shlex
    # doesn't implement these). Best-effort for detection; command substitution and the
    # like remain the native_git_hook layer's job.
    command = command.replace("$'", "'").replace('$"', '"')
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except Exception:
        return []
    out, cur = [], []
    for t in toks:
        if t and set(t) <= _OP_CHARS:            # &&, ||, |, ;, &, (, ), <, >, >>
            if cur:
                out.append(cur)
                cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out


def _skip_prefix(tokens):
    """Index of the real command word — skips a `FOO=bar` env prefix and command
    wrappers (`env`, `sudo`, `command`, `exec`, ...) plus a wrapper's own leading
    flags, so `sudo -E git commit` / `env -i git commit` resolve to git.

    Best-effort by design: an exotic wrapper option that takes a *value*
    (`sudo -u user git commit`) can still slip past this tool-layer gate — the
    HARD guarantee for those is the native_git_hook layer (strict profile), which
    fires inside git itself for every committer regardless of shell form."""
    i = 0
    while i < len(tokens):
        t = tokens[i]
        base = os.path.basename(t)                      # `/usr/bin/sudo` -> `sudo`
        if "=" in t and not t.startswith("-"):        # VAR=val env assignment
            i += 1
            continue
        if base in _SHELL_KEYWORDS:                     # if / ! / { / while ...
            i += 1
            continue
        if base in _CMD_WRAPPERS:                       # wrapper word ...
            is_duration = base in _WRAPPER_DURATION
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):   # ... its flags ...
                # consume a flag's separate value UNLESS that value is `git`/`gh` — those
                # are the command word, never a wrapper flag value (guards `time -p git …`,
                # where `-p` is boolean for time but value-taking for other wrappers).
                if (tokens[i] in _WRAPPER_VALUE_FLAGS and "=" not in tokens[i]
                        and i + 1 < len(tokens) and os.path.basename(tokens[i + 1]) not in ("git", "gh")):
                    i += 2
                else:
                    i += 1
            if is_duration and i < len(tokens) and os.path.basename(tokens[i]) not in ("git", "gh"):
                i += 1                                  # skip `timeout`'s duration positional
            continue
        break
    return i


def _resolve_cmd(tokens):
    """(command_word, args_after_it) for a simple command, skipping an env prefix and
    command wrappers. The command word is normalized to its basename so a path-qualified
    binary (`/usr/bin/git`, `./gh`) resolves to `git`/`gh`. (None, []) if empty. This is
    what makes `echo gh pr merge` resolve to command word 'echo' (NOT a gh invocation)
    rather than matching on the mere presence of 'gh'/'pr'/'merge' somewhere in the line."""
    i = _skip_prefix(tokens)
    if i >= len(tokens):
        return None, []
    return os.path.basename(tokens[i]), tokens[i + 1:]


def _next_positional(tokens, i, value_opts):
    """Advance past option flags (skipping the value of any in value_opts) and return
    the index of the next positional token, or len(tokens)."""
    while i < len(tokens) and tokens[i].startswith("-"):
        t = tokens[i]
        i += 2 if (t in value_opts and "=" not in t) else 1
    return i


def git_subcommand(tokens):
    """The git subcommand for a simple command (e.g. 'commit'), skipping global
    options and their values; None if git is not the invoked command."""
    cmd, rest = _resolve_cmd(tokens)
    if cmd != "git":
        return None
    i = _next_positional(rest, 0, _GIT_VALUE_OPTS)
    return rest[i] if i < len(rest) else None


# `git commit` flags that consume a separate value token (so a following positional
# is the flag's value, NOT a pathspec).
_GIT_COMMIT_VALUE_FLAGS = {"-m", "--message", "-F", "--file", "-c", "--reedit-message",
                           "-C", "--reuse-message", "--author", "--date", "-t",
                           "--template", "--cleanup", "--squash", "--fixup", "--trailer",
                           "--pathspec-from-file"}
# short commit flags that carry a value: an attached tail is that value (`-madd`,
# `-Skey`), so its chars must NOT be scanned as further flags (else `-Skey` reads the
# 'a' in the key as `-a`). REQUIRED ones also consume the next token when standalone
# (`-m msg`); OPTIONAL ones (-S) never consume the next token.
_SHORT_REQ_VALUE = set("mFcCt")
_SHORT_OPT_VALUE = set("S")
# commit modes whose content ISN'T the pre-reviewed index (interactive hunk selection).
_COMMIT_INTERACTIVE = {"-p", "--patch", "--interactive"}


def _commit_unsafe_reason(args):
    """A human reason string if this `git commit`'s content wouldn't be EXACTLY the
    already-reviewed index — else None. Unsafe forms: `-a/--all` (also commits tracked
    worktree changes), a pathspec / --pathspec-from-file (commits worktree paths), and
    `-p/--patch/--interactive` (adds hunks outside the index). Short clusters like `-am`
    count as --all; `-mp...` etc. don't (the tail is the message value)."""
    uses_all = has_pathspec = interactive = amend = saw_ddash = False
    i = 0
    while i < len(args):
        t = args[i]
        if saw_ddash:                                   # everything after `--` is a path
            has_pathspec = True
            i += 1
        elif t == "--":
            saw_ddash = True
            i += 1
        elif t == "--amend" or (len(t) >= 4 and t.startswith("--am") and "--amend".startswith(t)):
            amend = True                                # --amend or an unambiguous abbrev (--am…)
            i += 1
        elif t in _COMMIT_INTERACTIVE:
            interactive = True
            i += 1
        elif t == "--pathspec-from-file" or t.startswith("--pathspec-from-file="):
            has_pathspec = True
            i += 1 if "=" in t else 2
        elif t.startswith("--"):                        # long flag (maybe --flag=val)
            name = t.split("=", 1)[0]
            if name == "--all" or (len(name) >= 3 and "--all".startswith(name)):
                uses_all = True                         # --all or an abbrev (--a, --al)
                i += 1
            else:
                i += 1 if ("=" in t or name not in _GIT_COMMIT_VALUE_FLAGS) else 2
        elif t.startswith("-") and len(t) > 1:          # short flag / cluster e.g. -am
            cluster = t[1:]
            advance = 1
            k = 0
            while k < len(cluster):
                ch = cluster[k]
                if ch in _SHORT_REQ_VALUE:
                    # value is the attached tail, or the NEXT token if this is the last char
                    if k == len(cluster) - 1:
                        advance = 2
                    break                               # rest of token is a value, not flags
                if ch in _SHORT_OPT_VALUE:
                    break                               # -S: attached key is the value; stop
                if ch == "a":
                    uses_all = True
                elif ch == "p":
                    interactive = True                  # -p patch mode
                k += 1
            i += advance
        else:                                           # bare positional -> pathspec
            has_pathspec = True
            i += 1
    if uses_all:
        return "`-a/--all` also commits tracked worktree changes"
    if amend:
        return "`--amend` rewrites the previous commit; its patch (vs HEAD^) isn't the reviewed staged diff"
    if interactive:
        return "interactive/patch mode (-p/--patch/--interactive) adds hunks outside the index"
    if has_pathspec:
        return "a pathspec / file list commits worktree content, not the reviewed index"
    return None


# git global options / env that retarget which repo the commit lands in — the local
# review sentinel can't attest to a commit in another repo/worktree, so fail closed.
_GIT_CROSS_DIR_OPTS = ("-C", "--git-dir", "--work-tree")
_GIT_CROSS_DIR_ENV = ("GIT_DIR=", "GIT_WORK_TREE=")
# common git subcommands we never treat as a possible commit alias (bounds alias lookups).
_GIT_BUILTIN_SUBCOMMANDS = {
    "add", "status", "log", "diff", "show", "push", "pull", "fetch", "clone", "init",
    "checkout", "switch", "restore", "reset", "revert", "branch", "merge", "rebase",
    "cherry-pick", "stash", "tag", "remote", "config", "fsck", "gc", "grep", "mv", "rm",
    "ls-files", "rev-parse", "blame", "describe", "bisect", "reflog", "shortlog",
    "submodule", "worktree", "apply", "format-patch", "am", "clean", "archive", "notes",
    "help", "version", "commit", "commit-graph", "commit-tree", "whatchanged", "cat-file",
}


def _prefix_chdir(tokens):
    """True if a command wrapper in the prefix changes directory before the command
    (`env -C dir`, `env --chdir=dir`, `sudo --chdir=dir`) — so the effective repo differs
    from the hook's cwd."""
    prefix = tokens[:_skip_prefix(tokens)]
    return any(t in ("-C", "--chdir") or t.startswith("--chdir=") for t in prefix)


def _exports_env(tokens, prefixes):
    """The value if this simple command SETS one of `prefixes` (e.g. ('GH_REPO=',)) for
    LATER commands in the line — `export VAR=val` or a standalone `VAR=val` assignment —
    else None. (An inline `VAR=val cmd …` prefix is handled at the command itself.)"""
    cmd, rest = _resolve_cmd(tokens)
    scan = rest if cmd == "export" else (tokens if cmd is None else [])
    for t in scan:
        if t.startswith(prefixes):
            return t.split("=", 1)[1] or "(env override)"
    return None


def _has_cross_dir(tokens, global_opts):
    """True if a git commit is redirected to another repo/worktree via -C/--git-dir/
    --work-tree options, GIT_DIR/GIT_WORK_TREE env, or a chdir wrapper — where the local
    sentinel can't attest to it."""
    if any(g in _GIT_CROSS_DIR_OPTS or g.startswith(("--git-dir=", "--work-tree="))
           for g in global_opts):
        return True
    if any(t.startswith(_GIT_CROSS_DIR_ENV) for t in tokens):
        return True
    return _prefix_chdir(tokens)


def _commit_reason(tokens, rest, i):
    """Deny-reason for a resolved `git ... commit` (args after 'commit' at index i), or
    None if it's a plain THIS-repo index commit the sentinel can attest to."""
    reason = _commit_unsafe_reason(rest[i + 1:])
    if reason is None and _has_cross_dir(tokens, rest[:i]):
        reason = "-C/--git-dir/--work-tree/GIT_DIR commits into another repo"
    return reason


def git_commit_info(tokens):
    """{'reason': str_or_None} if this simple command is a `git ... commit` (not
    commit-graph, not `git config commit.*`), else None. `reason` is non-None when the
    committed content wouldn't be THIS repo's already-reviewed index (deny)."""
    cmd, rest = _resolve_cmd(tokens)
    if cmd != "git":
        return None
    i = _next_positional(rest, 0, _GIT_VALUE_OPTS)
    if i >= len(rest) or rest[i] != "commit":
        return None
    return {"reason": _commit_reason(tokens, rest, i)}


def _alias_commit_info(tokens, root):
    """If a git simple command's subcommand is a non-builtin that a git ALIAS expands to
    a commit OR an auto-committing subcommand (e.g. `git ci` = `commit`, `git up` = `pull
    --ff-only`), return its info dict; else None. One level, one `git config` lookup, only
    for unrecognized subcommands (so builtins cost nothing)."""
    if root is None:
        return None
    cmd, rest = _resolve_cmd(tokens)
    if cmd != "git":
        return None
    i = _next_positional(rest, 0, _GIT_VALUE_OPTS)
    if i >= len(rest):
        return None
    sub = rest[i]
    if sub.startswith("-") or sub in _GIT_BUILTIN_SUBCOMMANDS:
        return None
    # an inline `-c alias.<sub>=<expansion>` global option overrides persisted config
    exp_str = None
    for t in rest[:i]:
        if t.startswith("alias." + sub + "="):
            exp_str = t.split("=", 1)[1]
            break
    if exp_str is None:
        r = _sh(["git", "config", "--get", "alias." + sub], root)
        if r is None or r.returncode != 0 or not r.stdout.strip():
            return None
        exp_str = r.stdout.strip()
    # The expansion may itself be COMPOUND (`!git add -A && git commit`); walk it tracking
    # index mutations WITHIN the alias so a commit after in-alias staging fails closed.
    extra, alias_dirty = rest[i + 1:], False
    for ec in simple_commands(exp_str.lstrip("!")):   # `commit -s`, `!git commit …`, `add -A && commit`
        ecmd, erest = _resolve_cmd(ec)
        body = erest if ecmd == "git" else ([] if ecmd is None else ([ecmd] + erest))
        if _mutates_index(["git"] + body):
            alias_dirty = True
        # Effective command = git <this expansion step> <user's extra args>; run BOTH the
        # commit and auto-commit detectors (an alias may expand to commit OR merge/pull/…).
        info = git_commit_info(["git"] + body + extra) or _auto_commit_info(["git"] + body + extra)
        if info is not None:
            reason = info["reason"]
            if reason is None and alias_dirty:
                reason = ("this alias restages the index before committing, so the review sentinel "
                          "can't attest to what commits — stage, review, and commit as separate steps")
            if reason is None and _has_cross_dir(tokens, rest[:i]):
                reason = "-C/--git-dir/--work-tree/GIT_DIR commits into another repo"
            return {"reason": reason}
    return None


# git subcommands that advance the branch to content WITHOUT a reviewed `git commit`
# (create a merge commit, or fast-forward onto commits the sentinel never saw).
_AUTO_COMMIT_SUBS = {"merge", "pull", "cherry-pick", "revert", "am"}


def _auto_commit_info(tokens):
    """{'reason': str} if this simple command is an AUTO-COMMITTING git subcommand
    (merge/pull/cherry-pick/revert/am) that lands a commit without a reviewed `git
    commit`, else None. Safe forms (--no-commit / --ff-only / --abort, and `-n` for
    cherry-pick/revert) return None."""
    cmd, rest = _resolve_cmd(tokens)
    if cmd != "git":
        return None
    i = _next_positional(rest, 0, _GIT_VALUE_OPTS)
    if i >= len(rest):
        return None
    sub, opts = rest[i], rest[i + 1:]
    if sub == "rebase":
        # plain rebase replays already-committed (already-reviewed) commits; only
        # `--continue` (incl. unambiguous abbrevs like --cont) lands NEW conflict-
        # resolution content from the index without a reviewed `git commit`.
        if any(o == "--continue" or (len(o) >= 5 and "--continue".startswith(o)) for o in opts):
            return {"reason": "`git rebase --continue` commits conflict resolutions from the "
                              "index without a reviewed `git commit` (review + commit, or --abort)"}
        return None
    if sub not in _AUTO_COMMIT_SUBS:
        return None
    o = set(opts)
    if o & {"--abort", "--quit"}:                       # nothing lands
        return None
    if sub in ("cherry-pick", "revert") and (o & {"--no-commit", "-n"}):
        return None                                     # stages the change; no fast-forward
    if sub in ("merge", "pull"):
        # A plain `--no-commit` can STILL fast-forward (advancing the branch with no
        # staged merge to review). Only `--squash`, or `--no-commit` WITH `--no-ff`
        # (forces a staged, non-ff merge commit), leaves content for a reviewed commit.
        if "--squash" in o or ("--no-commit" in o and "--no-ff" in o):
            return None
    return {"reason": f"`git {sub}` advances the branch to content that wasn't staged-diff "
                      f"reviewed (use `git {sub} --no-ff --no-commit` or `--squash`, review, then "
                      f"a plain `git commit`; or --abort)"}


def git_commits(command, root=None):
    """Every `git ... commit` invocation in the line as info dicts. If `root` is given,
    also resolves git aliases that expand to a commit (e.g. `git ci`). [] if none."""
    out = []
    for c in simple_commands(command):
        info = git_commit_info(c) or _alias_commit_info(c, root)
        if info is not None:
            out.append(info)
    return out


_DIR_CHANGERS = ("cd", "pushd", "popd")


# git subcommands that change the STAGED INDEX or HEAD (so a commit AFTER them, in the
# same Bash line, would land content the pre-execution sentinel check never saw).
# `checkout`/`switch` restage (`checkout <tree> -- path`) or move HEAD; the sequencer
# subs in their STAGING forms (`cherry-pick -n`, `merge --squash`, `merge --no-commit`)
# stage content that a following same-line commit would land unreviewed (their
# committing forms are already denied by _auto_commit_info before reaching here).
_INDEX_MUTATING_SUBS = {"add", "rm", "mv", "reset", "restore", "stage", "apply",
                        "checkout", "switch", "merge", "pull", "cherry-pick", "revert",
                        "am", "rebase", "update-index", "read-tree", "stash"}


def _mutates_index(tokens):
    """True if this simple command is a git subcommand that restages the index."""
    cmd, rest = _resolve_cmd(tokens)
    if cmd != "git":
        return False
    i = _next_positional(rest, 0, _GIT_VALUE_OPTS)
    return i < len(rest) and rest[i] in _INDEX_MUTATING_SUBS


def _mutates_pr_head(tokens):
    """True if this simple command can change a PR's head before a later `gh pr merge`
    (a `git push`) — after which the gate's earlier `gh pr view` head is stale."""
    cmd, rest = _resolve_cmd(tokens)
    if cmd != "git":
        return False
    i = _next_positional(rest, 0, _GIT_VALUE_OPTS)
    return i < len(rest) and rest[i] == "push"


def _cd_target(cwd, tokens):
    """(new_cwd, ok) after a `cd`/`pushd`/`popd` simple command. ok=False means the new
    directory can't be statically resolved — `cd $VAR`/`cd -`/glob/subst, or ANY `popd`
    (the dir stack isn't modeled) — so the caller must fail closed. Non-dir commands
    leave cwd unchanged (ok=True)."""
    cmd, rest = _resolve_cmd(tokens)
    if cmd == "popd":
        return cwd, False                                      # dir stack not modeled
    if cmd not in ("cd", "pushd"):
        return cwd, True
    dirs = [a for a in rest if not a.startswith("-")]          # ignore -L/-P
    if not dirs:
        return (os.path.expanduser("~"), True) if cmd == "cd" else (cwd, True)
    d = dirs[0]
    if d in ("-", "+", "~-") or any(ch in d for ch in "$`*?"):  # unresolvable / dir-stack
        return cwd, False
    d = os.path.expanduser(d)
    target = os.path.normpath(d if os.path.isabs(d) else os.path.join(cwd, d))
    if not os.path.isdir(target):
        # cd would FAIL; with `&&` the next command won't run, with `;` it runs in the
        # ORIGINAL dir — either way the effective cwd is uncertain. Fail closed.
        return cwd, False
    return target, True


def _advance_cwd(command_has_subshell, cmd, tokens, cwd, uncertain):
    """Apply a dir-changing simple command to (cwd, uncertain); return the new pair. A
    subshell group `( … )` restores the outer cwd on `)`, which we can't scope after
    flattening, so any dir change when grouping is present makes cwd unknown (conservative;
    such forms are rare). popd / unresolvable cd targets also make it unknown."""
    if cmd not in _DIR_CHANGERS:
        return cwd, uncertain
    if command_has_subshell:
        return cwd, True
    new_cwd, ok = _cd_target(cwd, tokens)
    return (new_cwd, uncertain) if ok else (cwd, True)


def commits_with_cwd(command, start_cwd):
    """[(reason_or_None, cwd_or_None)] for each git-commit, tracking cd so each is judged
    against the dir Bash runs it in. cwd None => unknown effective repo => fail closed."""
    subshell = "(" in command or ")" in command
    cwd, uncertain, git_env, index_dirty, out = start_cwd, False, None, False, []
    for c in simple_commands(command):
        cmd, _ = _resolve_cmd(c)
        ev = _exports_env(c, _GIT_CROSS_DIR_ENV)      # exported GIT_DIR=/GIT_WORK_TREE=
        if ev is not None:
            git_env = ev
        info = (git_commit_info(c) or _auto_commit_info(c)
                or (None if uncertain else _alias_commit_info(c, cwd)))
        if info is not None:
            reason = info["reason"]
            if reason is None and git_env is not None:
                reason = "GIT_DIR/GIT_WORK_TREE was exported, redirecting the commit to another repo"
            if reason is None and index_dirty:
                reason = ("the index is restaged earlier in the SAME command line (git add/reset/…), so "
                          "the review sentinel can't attest to what commits — stage, review, then commit "
                          "as separate commands")
            out.append((reason, None if uncertain else cwd))
        elif uncertain and cmd == "git":
            # a git command in an unknown dir might be a commit (alias) -> fail closed
            out.append(("the working directory changed to a path the gate can't resolve", None))
        else:
            if _mutates_index(c):
                index_dirty = True
            cwd, uncertain = _advance_cwd(subshell, cmd, c, cwd, uncertain)
    return out


def merges_with_cwd(command, start_cwd):
    """[(merge_info, cwd_or_None)] for each `gh pr merge`, tracking cd. cwd None =>
    unknown effective dir => fail closed. Resolves gh aliases (e.g. `gh pm` = `pr merge`)
    — one `gh alias list` lookup, only when some gh command uses a non-builtin subcommand."""
    cmds = simple_commands(command)
    aliases = None
    for c in cmds:
        cc, cr = _resolve_cmd(c)
        if cc == "gh":
            gi = _gh_first_sub_index(cr)
            if gi < len(cr) and cr[gi] not in _GH_BUILTINS and not cr[gi].startswith("-"):
                aliases = _gh_alias_map()
                break
    subshell = "(" in command or ")" in command
    cwd, uncertain, gh_env, head_dirty, out = start_cwd, False, None, False, []
    for c in cmds:
        cmd, _ = _resolve_cmd(c)
        ev = _exports_env(c, ("GH_REPO=", "GH_HOST="))    # exported gh repo/host override
        if ev is not None:
            gh_env = ev
        m = _gh_merge_in(c, aliases)
        if m is not None:
            if m["repo"] is None and gh_env is not None:
                m = {**m, "repo": gh_env}
            if head_dirty:
                m = {**m, "stale": True}                   # a git push earlier can change the head
            out.append((m, None if uncertain else cwd))
        elif uncertain and cmd == "gh":
            out.append(({"ref": None, "repo": None, "auto": False}, None))
        else:
            if _mutates_pr_head(c):
                head_dirty = True
            cwd, uncertain = _advance_cwd(subshell, cmd, c, cwd, uncertain)
    return out


def is_git_commit(command):
    """True if any simple command in the line is a `git ... commit`. Quote/compound
    robust (not commit-graph, not `git config commit.*`)."""
    return bool(git_commits(command))


def _gh_repo_override(rest):
    """Any cross-context override in a gh command that makes THIS repo's local review
    sentinel unable to attest to the merge — -R/--repo (another repo) or --hostname
    (another host). Returns the override value (truthy) or None. Detection-only: the
    gate fails closed on any such form."""
    for k, t in enumerate(rest):
        if t in ("-R", "--repo"):
            return rest[k + 1] if k + 1 < len(rest) else "(repo override)"
        if t.startswith("--repo="):
            return t.split("=", 1)[1]
        if t.startswith("-R") and len(t) > 2:          # attached -Rowner/repo
            return t[2:]
        if t == "--hostname" or t.startswith("--hostname="):
            return "(host override)"
    return None


# gh top-level commands — a first positional not in here MIGHT be an alias (bounds
# `gh alias list` lookups to genuinely unknown subcommands).
_GH_BUILTINS = {
    "pr", "issue", "repo", "run", "workflow", "release", "gist", "auth", "api", "config",
    "alias", "browse", "search", "label", "secret", "variable", "cache", "codespace",
    "extension", "ssh-key", "gpg-key", "org", "project", "status", "completion", "ruleset",
    "attestation", "accessibility", "preview", "help", "version",
}


def _gh_alias_map():
    """{alias: expansion} from `gh alias list` (global gh config). {} on any error."""
    r = _sh(["gh", "alias", "list"], None)
    if r is None or r.returncode != 0:
        return {}
    out = {}
    for line in r.stdout.splitlines():
        name, sep, exp = line.partition(":")
        if sep and name.strip() and exp.strip():
            out[name.strip()] = exp.strip()
    return out


def _gh_first_sub_index(rest):
    """Index of the first positional (the gh subcommand) after any gh global options."""
    i = 0
    while i < len(rest) and rest[i].startswith("-"):
        i += 2 if rest[i] in ("-R", "--repo") else 1
    return i


def _gh_merge_in(tokens, aliases=None):
    """If a simple command invokes `gh ... pr ... merge ...`, return
    {'ref': pr_ref_or_None, 'repo': override_or_None}; else None. Requires gh to be the
    command word (so `echo gh pr merge` is NOT a merge). `pr`/`merge` are matched as
    BARE subcommand words so unknown value-options around them (e.g. GHE `--hostname X`)
    can't shift the parse and slip a merge past the gate. If `aliases` is given, a gh
    alias in the subcommand slot (e.g. `gh pm` = `pr merge`) is expanded first. Ambiguous
    ref extraction fails CLOSED downstream: a wrong ref makes `gh pr view` error → deny."""
    cmd, rest = _resolve_cmd(tokens)
    if cmd != "gh":
        return None
    if aliases:                                          # expand a gh alias `gh <alias> …`
        gi = _gh_first_sub_index(rest)
        if gi < len(rest) and rest[gi] in aliases:
            exp = simple_commands(aliases[rest[gi]].lstrip("!"))
            if exp:
                ec = exp[0][1:] if exp[0][:1] == ["gh"] else exp[0]
                rest = rest[:gi] + ec + rest[gi + 1:]
    # `gh api … pulls/<n>/merge` merges via the raw GitHub API, bypassing `gh pr merge`.
    # Can't bind it to the local head sentinel -> fail closed (use `gh pr merge` instead).
    if rest[:1] == ["api"] and any("pulls/" in t and t.rstrip("/").endswith("/merge")
                                   for t in rest):
        return {"ref": None, "repo": "(gh api merge)", "auto": False}
    # locate the bare subcommand words: 'pr' then a later 'merge'
    pr_at = next((k for k, t in enumerate(rest) if t == "pr" and not t.startswith("-")), None)
    if pr_at is None:
        return None
    merge_at = next((k for k in range(pr_at + 1, len(rest)) if rest[k] == "merge"), None)
    if merge_at is None:
        return None
    # repo/host override via -R/--repo/--hostname, a GH_REPO=/GH_HOST= env prefix (env is
    # stripped by _resolve_cmd, so check the raw tokens), or a chdir wrapper (env -C) that
    # moves gh into another repo -> fail closed.
    repo = _gh_repo_override(rest)
    if repo is None:
        for t in tokens:
            if t.startswith(("GH_REPO=", "GH_HOST=")):
                repo = t.split("=", 1)[1] or "(env override)"
                break
    if repo is None and _prefix_chdir(tokens):
        repo = "(wrapper chdir)"
    # ref = first bare token after 'merge', skipping known merge value-flags' values.
    # An UNKNOWN value-flag here leaves its value looking like the ref -> `gh pr view`
    # fails on it -> the gate denies (fail closed), never fail-open.
    ref = None
    j = merge_at + 1
    while j < len(rest):
        t = rest[j]
        if not t.startswith("-"):
            ref = t
            break
        if t in _GH_MERGE_VALUE_FLAGS and "=" not in t:
            j += 2
        else:
            j += 1
    # --auto (or --auto=<bool>) defers the merge to GitHub; the head can advance past the
    # verified sentinel before it fires, so it can't be gated at command time -> fail closed.
    auto = any(t == "--auto" or t.startswith("--auto=") for t in rest[merge_at + 1:])
    return {"ref": ref, "repo": repo, "auto": auto}


def gh_pr_merges(command):
    """EVERY `gh pr merge` invocation in the line, in order — so a compound command
    like `gh pr merge 1 && gh pr merge 2` yields BOTH (the gate must verify each; one
    sentinel can't vouch for two heads). [] if none is a real gh pr merge."""
    out = []
    for c in simple_commands(command):
        m = _gh_merge_in(c)
        if m is not None:
            out.append(m)
    return out


def _sh(args, cwd):
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=20)
    except Exception:
        return None


def _diff_cached_bytes(root):
    """Raw bytes of `git diff --cached` — never text-decoded, so a staged diff with
    non-UTF-8 bytes (binary content, latin-1) can't raise a decode error and turn the
    gate into a fail-open allow. None on git error/timeout."""
    try:
        r = subprocess.run(["git", "diff", "--cached"], cwd=root,
                           capture_output=True, timeout=20)  # bytes: no text=True
    except Exception:
        return None
    return r.stdout if r.returncode == 0 else None


def repo_root(cwd):
    r = _sh(["git", "rev-parse", "--show-toplevel"], cwd)
    return r.stdout.strip() if (r and r.returncode == 0) else cwd


def resolve(root):
    """Resolved review-loop config for a project, or None if unresolvable."""
    if _config is None:
        return None
    try:
        return _config.resolve(root)
    except Exception:
        return None


def _sentinel(root, name):
    try:
        with open(os.path.join(root, "docs", "dev-review", name)) as f:
            return f.read().strip()
    except Exception:
        return None


def staged_sha(root):
    """SHA-256 of `git diff --cached` — THE single definition of the staged-diff
    identity. Every sentinel writer (dev-review, vendor gate) must use this so a
    written sentinel always satisfies the gate; hashing the diff a second way
    (e.g. shell shasum) can mismatch on large diffs. Hashes raw bytes."""
    b = _diff_cached_bytes(root)
    if b is None:
        return None
    return hashlib.sha256(b).hexdigest()


def commit_missing(root, need_dev, need_vendor):
    """Missing-review labels for the staged diff. [] = allow (also on error/exempt)."""
    b = _diff_cached_bytes(root)
    if b is None or not b.strip():
        return []  # nothing staged / git error -> fail open
    # NUL-delimited so paths with spaces (`release notes.md`) stay intact — splitting
    # on whitespace would break the doc-only exemption and falsely block valid work.
    names = _sh(["git", "diff", "--cached", "--name-only", "-z"], root)
    files = [f for f in names.stdout.split("\0") if f] if names and names.returncode == 0 else []
    if files and all(
        f.endswith(DOC_SUFFIX) or f.startswith("docs/") or f in DOC_EXACT for f in files
    ):
        return []  # doc-only commit is exempt
    current = hashlib.sha256(b).hexdigest()
    missing = []
    if need_dev and _sentinel(root, "last-dev-review-sha.txt") != current:
        missing.append("dev-review — a FRESH separate agent reviews the staged diff, then writes "
                       "docs/dev-review/last-dev-review-sha.txt on a Ready verdict")
    if need_vendor and _sentinel(root, "last-vendor-review-sha.txt") != current:
        missing.append("cross-vendor review — run the vendor gate; it writes "
                       "docs/dev-review/last-vendor-review-sha.txt only on a no-[P1] pass")
    return missing
