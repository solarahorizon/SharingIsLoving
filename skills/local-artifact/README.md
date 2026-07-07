# See Claude Code's output as a page — not a wall of terminal text

A Claude Code skill that renders a result as a **visual HTML page written to a local file in your repo** — so you can *look* at what Claude did instead of scrolling back through screen after screen of terminal replies. Diagrams, real screenshots, status boards, side-by-side comparisons — on your own disk, not a vendor's server.

This is the **actual `SKILL.md`** running in production at Solara Horizon Pty Ltd, sanitised for standalone use. Happy for anyone to adapt.

```
README.md   ← this file (what it is + why + how to adopt)
SKILL.md    ← the skill itself (~130 lines)
```

---

## Why you'd use it

Claude Code talks back in the terminal. For a quick answer that's fine — but the moment the work has any *shape* (it touched eight files, it compared three options, it shipped five commits, it wants your eye on a UI change), the terminal turns into a long scroll of prose you have to read line by line and reassemble in your head. The signal is in there; it's just flat.

A visual page fixes that. Instead of reading a wall of text, you **see the result at a glance**:

- **A status board or run wrap-up** — what got done, what's merged vs. needs-your-eyes, laid out so you scan it in seconds instead of re-reading a transcript.
- **Real screenshots** — Claude captures the actual app/simulator and drops the images straight into the page, so you inspect what really rendered (scaling, clipping, a UI change) instead of trusting a text description of it.
- **Diagrams** — an architecture sketch, a before/after, a decision tree — rendered visually, right next to the explanation.
- **A decision gallery** — options side by side with the trade-offs, so you can actually choose from pictures rather than paragraphs.

It's the difference between reading a report and looking at a dashboard. When you just want to *understand what happened* and decide what's next, a page beats a scrollback.

## What it does (and how it's different)

**This is a local-first counterpart to Anthropic's built-in `Artifact` tool.** Claude Code ships an `Artifact` tool that renders exactly these visual pages — but it *publishes* each one to a hosted `https://claude.ai/code/artifact/<uuid>` URL on Anthropic's servers. Convenient, but the page now lives off your device.

This skill produces the same kind of polished visual page and writes it **to a file in your repo instead — nothing is uploaded to Anthropic's servers.** Every image is embedded as a `data:` URI and all CSS/JS is inlined, so the result is a single portable `.html` file you can commit, diff, open offline, and hand around, entirely on your own machine.

Concretely, it **reuses Anthropic's `artifact-design` skill** (the built-in design-craft guidance — palette, type, layout, honesty rules) for the *look*, and only swaps the *delivery*: it calls `Write` to put a file on disk instead of calling the `Artifact` tool to publish to claude.ai. Same craft, local delivery. (Not to be confused with Anthropic's `project-artifact` skill, which is a specific tabbed *project-status page* built on top of the `Artifact` tool — different thing.)

## Why it exists (the point most repos skip)

Two reasons, one principled and one practical.

**Principled:** working artifacts — wrap-ups, decision galleries, status boards — are internal. If your standing preference is that generated pages stay on your own disk and version control rather than a vendor's servers, the hosted `Artifact` tool quietly violates that every time it's used, because "make me a visual" is exactly when it fires. This skill makes the private, on-disk path the default and the hosted path the explicit exception. For us that's not a preference, it's the mission: privacy-first is the default behind everything we ship, and "nothing leaves the device unless you choose to send it" should apply to Claude's own output too.

**Practical — the postmortem baked into the skill:** the first galleries used *hand-drawn placeholder* screenshots that resembled the real feature. One diverged from what had actually shipped and caused a "wait, is that what we approved?" confusion. So the skill has a hard rule: **real screenshots only — never a mockup that mimics a real feature; if no real capture exists, omit the card and say so.** There's also a blocking self-containment gate (a one-line `grep`) that refuses to open/commit the page if any external `src`/`href`/CDN/webfont reference survives — because a "self-contained" file with one stray CDN link isn't portable and breaks the moment it's offline.

## Pairs with `autonomous-block`

This skill is the natural closing move for [`autonomous-block`](../autonomous-block/) (also in this repo). After Claude Code has run unattended for a whole night — 14 hours, a dozen commits, a few PRs, some things merged and some needing your eye — the *last* thing you want at breakfast is to reconstruct all of it by scrolling a giant transcript. So the autonomous-block wrap-up renders through this skill: one visual page waiting for you with what shipped, what's merged vs. needs-your-eyes, and real screenshots of anything visual it touched. A long night of work becomes a page you read in a minute — and it's sitting in your repo, not on a server.

## How to run it standalone

1. Copy this `local-artifact/` folder into your skills directory:
   - per-project: `.claude/skills/local-artifact/`
   - or your user-level skills dir to load it in every session.
2. Set the default output folder. The skill writes durable pages to a docs directory (the author's default is `docs/session/`) — change that in `SKILL.md` §Output contract to wherever your repo keeps docs.
3. Invoke it whenever a visual page would beat terminal text: *"give me a visual wrap-up of this run"*, *"show me a before/after gallery"*. It writes the `.html`, runs the self-containment gate, and opens it locally.

**Requirements**
- Any Claude Code model (no special model needed).
- **Python 3 + Pillow** (`pip install Pillow`) — used to resize screenshots and base64-embed them.
- A shell with `open` (macOS) or `xdg-open` (Linux) to view the result.
- Optional: a built-in `artifact-design` skill for craft guidance — if absent, the skill's own §Design craft notes stand alone.

**No dependency on any private repo or internal path.** The one place to adapt is the default output folder (above); everything else is self-contained.

---

MIT — see repo `LICENSE`.
