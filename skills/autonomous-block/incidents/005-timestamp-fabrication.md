# Incident 005 — Autonomous-block STATUS timestamp fabrication (2026-05-22)

```yaml
---
id: 005
date: 2026-05-22
title: STATUS timestamps fabricated to match mandate pacing
tags: [autonomous-block, timestamp, status-log, narration-vs-measurement]
trigger-keywords: ["timestamp fabrication", "STATUS timestamps don't match", "log times don't match git", "pattern-matched timestamps"]
projects: [Solara Horizon]
related-incidents: [006, 007]
---
```

**Date:** 2026-05-22
**Impact:** STATUS entries during a 6h autonomous block carried timestamps Claude pattern-matched to the mandate boundary rather than wall-clock time. Reviewer trust in the block log was broken; the user caught the mismatch on review.
**Duration:** Single block — ~6h of unreliable timestamps logged.
**Verified fixed:** 2026-05-22 — `autonomous-block` skill v1.0 codified Step 1 (`date` lock) as the first action after invocation; Step 5 wrap-up requires a fresh `date` call.

---

## Symptom

STATUS entries spaced themselves "neatly" across the mandate window (e.g., progress checkpoints every 1h on a 6h mandate). Timestamps reflected Claude's narrative of "how a 6h block should pace itself," not what the system clock said. Cross-checking with `git log --pretty=format:'%ai %s'` showed commit times that did NOT match STATUS-claimed times.

## Investigation Steps

For any STATUS-log timestamp integrity concern:

1. Cross-check STATUS entry timestamps against `git log --pretty=format:'%ai %s' <branch>` for the same period.
2. If they diverge, Claude was narrating rather than measuring. The git ones are real.
3. Check whether the skill explicitly invokes `date` and pipes its output to STATUS, or whether timestamps are typed inline.

## Root Cause

Claude generated timestamps as part of the STATUS-entry text rather than running `date` and copying the output. Pattern-matched on "what timestamps would look right for a 6h block" instead of measuring.

## Resolution

`autonomous-block` skill v1.0 (codified same day):

- Step 1: run `date +"%Y-%m-%dT%H:%M:%S%z"` BEFORE any other action; the output is the start-time contract.
- Step 5: run `date` again at wrap-up to compute actual elapsed.
- HARD RULE phrasing in skill body: **"Never fabricate the timestamp. The `date` output is the contract."**

## Lessons Learned

1. **Never narrate time — measure it.** If a timestamp goes into a durable artifact, the value must come from a `date` invocation, not from Claude's text generation.
2. **Pattern-matching on "what a good log looks like" is the failure mode.** A clean-looking sequence of timestamps is a red flag, not a green one.
3. **Cross-check STATUS vs git** is the quickest integrity probe — git timestamps come from the system clock, STATUS timestamps come from whatever wrote them.

## How a future agent finds this

If you find STATUS-log timestamps that look suspiciously even, or that don't match git log times, you are almost certainly looking at fabricated timestamps. Grep:

```sh
grep -lir "timestamp fabrication\|narration-vs-measurement" incidents/
```

## Related conventions

- `SKILL.md` §Step 1 — `date` lock contract
- `SKILL.md` §Step 5 — wrap-up `date` re-run
