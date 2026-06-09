# SharingIsLoving

The actual artefacts behind running Claude Code at production scale: skill files, postmortems, configs. **Currently featuring:** [the production `SKILL.md` and six incident reports behind running unattended 14-hour Claude Code autonomous blocks](autonomous-block/).

[Solara Horizon Pty Ltd](https://solarahorizon.com.au) is building several consumer products in parallel (a kid's math game, a health app, a content platform) with Claude Code as the primary dev partner. Some patterns took painful incidents to land. This repo is where we share what worked, with attribution to the failure that earned each rule.

---

## Topics

- **[autonomous-block/](autonomous-block/)** — How to run multi-hour Claude Code autonomous blocks. Includes the actual `SKILL.md` in production, plus the six postmortem incidents that earned each rule. **Start here if you've ever asked "can I leave Claude running overnight?"**

*More topics added as we ship them.*

---

## How to use this repo

Browse a topic folder. Each has its own README explaining the pattern + the artefacts (skill files, templates, configs) you can copy + adapt. Everything is MIT-licensed; no attribution required.

## Contributing

One-way share: we publish what we've learned and don't take PRs on the artefacts themselves (they reflect our specific production context). Issues + LinkedIn DMs welcome for discussion.

## License

[MIT](LICENSE) — adapt freely.

---

*Lynn Yang, Solara Horizon Pty Ltd. 2026-06-09.*
