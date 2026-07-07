# Keep Claude's "artifacts" on your own disk

A Claude Code skill that renders a visual HTML page **to a local file in your repo** instead of publishing it to a hosted URL on a vendor's servers.

This is the **actual `SKILL.md`** running in production at Solara Horizon Pty Ltd, sanitised for standalone use. Happy for anyone to adapt.

```
README.md   ← this file (what it is + why + how to adopt)
SKILL.md    ← the skill itself (~130 lines)
```

---

## What it does

Some agent harnesses ship a built-in **Artifact** tool: ask for a nice visual page (a status board, a run wrap-up, a before/after gallery) and it renders one — but it *publishes* that page to a hosted URL on the vendor's infrastructure. Convenient, but the page now lives off your device.

This skill produces the same kind of polished, self-contained HTML page and writes it **to a file in your repo** instead. Every image is embedded as a `data:` URI and all CSS/JS is inlined, so the result is a single portable `.html` file you can commit, diff, open offline, and hand around — with nothing sent to a third party.

It reuses the harness's design-craft guidance (via an `artifact-design` skill if one exists) for the *look*, and only changes the *delivery*: disk, not a hosted URL.

## Why it exists (the point most repos skip)

Two reasons, one principled and one practical.

**Principled:** working artifacts — wrap-ups, decision galleries, status boards — are internal. If your standing preference is that generated pages stay on your own disk and version control rather than a vendor's servers, the hosted Artifact tool quietly violates that every time it's used, because "make me a visual" is exactly when it fires. This skill makes the private, on-disk path the default and the hosted path the explicit exception.

**Practical — the postmortem baked into the skill:** the first galleries used *hand-drawn placeholder* screenshots that resembled the real feature. One diverged from what had actually shipped and caused a "wait, is that what we approved?" confusion. So the skill has a hard rule: **real screenshots only — never a mockup that mimics a real feature; if no real capture exists, omit the card and say so.** There's also a blocking self-containment gate (a one-line `grep`) that refuses to open/commit the page if any external `src`/`href`/CDN/webfont reference survives — because a "self-contained" file with one stray CDN link isn't portable and breaks the moment it's offline.

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
