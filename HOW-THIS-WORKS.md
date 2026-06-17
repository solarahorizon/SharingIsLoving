# How this repo works

This repo is a curated set of artefacts from building consumer apps solo with AI —
the things that survived contact with production, postmortems included. It is **not**
a tutorial collection or a thought-leadership dump. If something here didn't earn its
place by doing real work, it shouldn't be here.

## What belongs here

| In | Out |
|---|---|
| Claude Code **skills** in active production use | Theoretical "best practices" / wished-for workflows |
| Standalone **tools** that pull their weight in a real pipeline | One-off throwaways, half-finished experiments |
| **Patterns / configs** (hooks, CI gates) earned the hard way | Anything internal-only, secret, or client-specific |
| The **postmortem** behind a rule, where there is one | Polished narratives with the failures sanded off |

Two questions decide it: *Is it in real use?* and *Did I earn it the hard way (can I show the failure behind it)?* If both aren't yes, leave it out.

## Categories

Top-level folders are categories. A category is born when its first real artefact lands — empty category folders aren't created ahead of need.

- `skills/` — Claude Code skills (e.g. `autonomous-block`)
- `tools/` — standalone scripts/utilities (e.g. `ai-art-cleanup`)
- `patterns/` — reusable recipes that aren't a packaged skill or tool *(when the first lands)*
- `configs/` — hooks, settings snippets, CI gates *(when the first lands)*

## Per-artefact convention

Every artefact is a **self-contained folder** whose README answers three things:

1. **What it does** — one paragraph, concrete.
2. **Why it exists** — the problem / the postmortem behind it. This is the part most repos skip; here it's the point.
3. **How to run it standalone** — for tools: `requirements.txt` + `--help` on every script; for skills: the adaptation notes + any model requirement.

Keep each folder runnable/usable on its own, with no dependency on our private repos or internal paths.

## A note on history

These are published *mirrors* of artefacts that live in active internal use. They're sanitised on the way out (no internal paths, secrets, or client specifics) and updated when the production version teaches us something new — so expect occasional version bumps rather than a frozen snapshot.
