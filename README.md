# SharingIsLoving

The actual artefacts behind running Claude Code at production scale. Skill files used day-to-day, postmortems behind every rule, configs and patterns that survived contact with reality — plus the small tools that handle the unglamorous parts of the pipeline.

Most AI workflow content is theoretical — what someone wishes were true, polished into a thought-leadership post. This repo is the opposite. The skills here run in active production at [Solara Horizon Pty Ltd](https://solarahorizon.com.au), across four consumer-app projects shipping in parallel — earned the hard way, postmortems included. The tools are newer: written this week for a real game-art pipeline, doing real work in the build.

---

## Contents

### `skills/` — Claude Code skills used in production

- **[skills/autonomous-block/](skills/autonomous-block/)** — running Claude Code unattended for multi-hour blocks (4–14h, almost nightly). Treats the agent as a distributed system: durable recovery loops, watchdogs, queue-exhaustion gates, on-disk state, clarification gates that fire before the cron arms. Ships the production `SKILL.md` (v3.2), six incident postmortems with grep-able frontmatter, an incident template, and a model-requirement note (Opus-class only).

### `tools/` — small scripts that pull their weight

- **[tools/ai-art-cleanup/](tools/ai-art-cleanup/)** — turn AI-generated / exported art into game-ready sprites. `align_walk.py` (de-drift a looping animation + knock out its white background, preserving interior whites), `measure_frames.py` (quantify animation drift), `slice_sheet.py` (sprite sheet → individual PNGs + gallery), `montage.py` (side-by-side comparison strips). The drift + transparent-key combo solves problems image editors and prompt tricks don't.

---

## What's coming

More topics ship as they get codified. Likely next: incident-log architecture for AI agents, multi-agent code review pipelines, on-device foundation-model fallback patterns.

---

## How to use this repo

Browse `skills/` or `tools/`. Each artefact folder has its own README explaining the pattern (and, for tools, a `requirements.txt` + `--help` on every script). Everything is MIT-licensed (see [LICENSE](LICENSE) for terms).

New here, or curious what belongs in this repo and how each artefact is structured? See **[HOW-THIS-WORKS.md](HOW-THIS-WORKS.md)**.

## Contributing

One-way share: we publish what we've learned and don't take PRs on the artefacts themselves (they reflect our specific production context). Issues + LinkedIn DMs welcome for discussion.

## License

[MIT](LICENSE) — adapt freely.

---

*Lynn Yang, Solara Horizon Pty Ltd. 2026-06-15.*
