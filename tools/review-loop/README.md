# The Gauntlet — a review loop that keeps AI coding agents honest

> Never trust the agent's own confidence — **the gates are the signal.**

An AI coding agent will tell you it's done, confidently, while an edge case is
quietly broken. `review-loop` is the harness that stops that change from landing:
every commit and every merge runs a gauntlet of **independent** reviews first, and
each pass is bound to the exact diff it reviewed — so nothing sneaks through on a
stale approval.

It's a few small Python/bash scripts plus one config file per project. No service
to run, no dependency to vendor in. You point a project's git hooks at the shared
engine and pick a strictness preset; the engine does the rest.

A visual walk-through of the whole flow is in [`design.html`](design.html) — open
it in a browser.

---

## The five checks

Each is independently on/off per project.

| Check | Runs | Hardness | What it does |
|---|---|---|---|
| **`dev_review`** | before commit | soft | A *separate* agent (not the author) reviews the staged diff. No ego in the diff, so it actually finds things. |
| **`cross_vendor_commit`** | before commit | soft | A model from a *different vendor* reviews the same diff. When two independent AIs flag the same bug, it's almost certainly real. |
| **`merge_gate`** | before merge | soft | The whole PR head is reviewed once more — and re-blocked if anything moved since (rebase, force-push, extra commit). |
| **`native_git_hook`** | at commit, in git | **hard** | The same block lives *inside git*, so it fires for sub-agents, `add && commit` one-liners, and any shortcut a tool-level hook can't see. |
| **`ci_backstop`** | after merge | server-side | A real build/audit runs on the server — the last line no local trick can dodge. (Documented; you wire the CI job.) |

### Why a pass can't be faked

Every approval is recorded as a **sentinel file** whose contents are the
`sha256` of `git diff --cached` (or the PR head SHA for the merge gate). The gate
only lets the action through when the sentinel equals the *current* diff. Change
one line and the old sentinel no longer matches — the review has to run again.
The sentinels are written **only** by the review runners on a genuine pass, never
by hand, and they're git-ignored so they never travel between machines.

---

## Presets — dial the strictness

Pick one preset; each adds to the one before.

| Check | `minimal` | `standard` | `strict` |
|---|:--:|:--:|:--:|
| `dev_review` | ● | ● | ● |
| `cross_vendor_commit` | | ● | ● |
| `merge_gate` | | ● | ● |
| `native_git_hook` | | | ● |
| `ci_backstop` | | | ● |

- **`minimal`** — lower-stakes apps where a bug is recoverable. One honest independent review; more gates would be friction without payoff.
- **`standard`** — most production apps. A second-vendor opinion and a final pre-merge pass catch what one reviewer on one commit misses.
- **`strict`** — public or accuracy-critical work that simply can't ship a mistake. The review becomes impossible to route around, with a server as the last line.

---

## Install

Requires `python3` and `git`. For the vendor check you also need a review runner
(see below).

```bash
# 1. Drop a config in your project (or let the installer scaffold one)
#    <project>/.claude/review-loop.json
{
  "profile": "standard",
  "merge_base": "main",
  "vendor": "codex",
  "vendor_fallback": "deepseek"
}

# 2. Wire the enabled layers into the project
tools/review-loop/install.sh /path/to/your/project

#    inspect without changing anything:
tools/review-loop/install.sh /path/to/your/project --list
tools/review-loop/install.sh /path/to/your/project --dry-run
tools/review-loop/install.sh /path/to/your/project --uninstall
```

`install.sh` wires the commit + merge gates as Claude Code `PreToolUse` hooks in
`<project>/.claude/settings.json`, and (for `strict`) installs a `.git/hooks/pre-commit`
shim. It's idempotent — re-run any time; it replaces its own managed entries
rather than duplicating them. `config.py` is the single source of truth for what a
profile means, so no two projects drift.

## Config — the two things you'll actually change

```jsonc
{
  "profile": "standard",       // minimal | standard | strict
  "merge_base": "main",        // the branch you merge into (e.g. "develop")
  "vendor": "codex",           // primary cross-model reviewer
  "vendor_fallback": "deepseek" // steps in when the primary is rate-limited; null to disable
}
```

You can also override individual layers regardless of preset:

```jsonc
{ "profile": "standard", "layers": { "native_git_hook": true } }
```

## Vendor runners (bring your own)

The cross-vendor check shells out to a reviewer you provide:

- **`codex`** — OpenAI's [`codex`](https://github.com/openai/codex) CLI on your `PATH`; the gate calls `codex exec`.
- **`deepseek`** — a small runner script that takes a diff-file argument and the `$DEEPSEEK_SYS` system prompt and prints the review. Defaults to `~/.config/deepseek/deepseek-review.sh`; set `$DEEPSEEK_RUNNER` to point elsewhere.

A runner just has to emit findings tagged `[P1]`/`[P2]`/`[P3]`. The gate **fails**
on any `[P1]`, and writes the sentinel only on a clean pass. If a vendor is
rate-limited it auto-falls-back to `vendor_fallback`, then retries once — the
review never silently skips.

---

## How a change actually flows

```
agent writes code
   → dev_review          (separate agent; writes last-dev-review-sha.txt on Ready)
   → cross_vendor_commit (other-vendor AI; writes last-vendor-review-sha.txt on no-[P1])
   → git commit          ← blocked until both sentinels == sha256(git diff --cached)
   → open PR
   → merge_gate          (review of the PR head; writes last-merge-review-sha.txt = head SHA)
   → gh pr merge         ← blocked until the sentinel == the current PR head
```

Doc-only commits (everything under `docs/` or matching `*.md` / `*.txt`) are
exempt. Every gate **fails open** on an internal error — a gate that can't decide
must never block real work — *except* the merge gate, which **fails closed**: a
merge it can't verify must not proceed.

---

## What the gate expects (and what it blocks)

The model is **stage → review the staged diff → commit that exact diff**. To keep the
sentinel meaningful, the commit gate requires an *explicit, reviewed staged commit* and
**fails closed** on forms whose committed content isn't that reviewed index:

- **Stage and commit as separate commands.** `git add . && git commit` in one line is
  blocked — the hook runs *before* `git add`, so it can't have reviewed the final diff.
- **No `git commit -a` / pathspec / `-p` / `--amend`, no `-C`/`GIT_DIR` cross-repo commits.**
- **`git merge` / `pull` / `cherry-pick` / `revert` / `am` are blocked** (they land content
  without a reviewed `git commit`). Sync via `git fetch` then `git merge --no-ff --no-commit`,
  review, and commit; or `--squash`.
- **Aliases and path/quoted/wrapped forms are resolved** (`git ci`, `git -c alias…`, `sudo …`,
  `/usr/bin/git …`, `gh pm`, `gh api …/merge`), so they can't slip the gate.
- The **merge gate** fails closed on `--auto`, `-R/--repo`/`--hostname`/`GH_REPO=` (cross-repo),
  and a `git push` earlier in the same line (stale head).

Deliberate one-off bypass is always `git commit --no-verify` (visible and intentional).

**Known limitation:** git fires **no hook on a fast-forward merge**, and `--ff-only`
overrides `merge.ff=false` — so the *native* layer can't block a raw-terminal `--ff-only`
fast-forward (the PreToolUse gate does block it on the agent path). Deliberate obfuscation
(command substitution, `eval`) is out of scope for the tool-layer gate; the native
`pre-commit`/`pre-merge-commit`/`pre-applypatch` hooks are the hard backstop there.

---

Part of [Solara Horizon · building real AI in public](https://github.com/solarahorizon/SharingIsLoving).
