# SharingIsLoving

The actual artefacts behind running Claude Code at production scale. Skill files used day-to-day, postmortems behind every rule, configs and patterns that survived contact with reality.

Most AI workflow content is theoretical — what someone wishes were true, polished into a thought-leadership post. This repo is the opposite. Everything here is in active production use at [Solara Horizon Pty Ltd](https://solarahorizon.com.au), across four consumer-app projects shipping in parallel. Patterns earned the hard way; postmortems included.

**Start here → [autonomous-block/](autonomous-block/)**

---

## Currently featured

### [autonomous-block/](autonomous-block/) — Running Claude Code unattended for multi-hour blocks

Unattended Claude Code blocks of 4–14 hours, running almost every night across four parallel projects. The framework treats the AI agent as a distributed system: durable recovery loops, watchdogs, queue-exhaustion gates, state persistence on disk, instruction-clarification gates that fire before the cron arms.

What's in the package:

- The production `SKILL.md` (v3.2, ~330 lines) with adaptation guide
- Six incident postmortems with grep-able frontmatter (so future Claude sessions can find them when stuck)
- An incident template for your own postmortem log
- A model requirement note (Opus-class only — Sonnet skips the gates)

---

## What's coming

More topics ship as they get codified. Likely next: incident-log architecture for AI agents, multi-agent code review pipelines, on-device foundation-model fallback patterns.

---

## How to use this repo

Browse a topic folder. Each has its own README explaining the pattern, plus the artefacts you can copy and adapt. Everything is MIT-licensed (see [LICENSE](LICENSE) for terms).

## Contributing

One-way share: we publish what we've learned and don't take PRs on the artefacts themselves (they reflect our specific production context). Issues + LinkedIn DMs welcome for discussion.

## License

[MIT](LICENSE) — adapt freely.

---

*Lynn Yang, Solara Horizon Pty Ltd. 2026-06-10.*
