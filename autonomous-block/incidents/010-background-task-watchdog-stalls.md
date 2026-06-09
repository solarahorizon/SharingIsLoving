# Incident 010 — Background-task watchdog stalls: 5 tasks silent at 600s (2026-06-09)

```yaml
---
id: 010
date: 2026-06-09
title: Long-running background tasks stalled silently at 600s watchdog with zero output
tags: [autonomous-block, background-tasks, run-in-background, watchdog, async, third-party-api]
trigger-keywords: ["TaskList all in_progress", "600s watchdog", "background task silent", "run_in_background stalled", "TaskOutput empty"]
projects: [SolaraHorizon]
related-incidents: []
---
```

**Date:** 2026-06-09
**Impact:** During an autonomous block, 5 long-running background tasks (Agent reviews + third-party image generation calls) all stalled silently at the 600s watchdog with no output written. The block continued firing heartbeats but the planned-output workstreams produced nothing. API quota was spent on tasks that never completed.
**Duration:** Discovered at heartbeat check ~T+1h after tasks were launched.
**Verified fixed:** 2026-06-09 — `autonomous-block` skill v3.0 codified "Avoid long-running background tasks" guidance under Step 3.

---

## Symptom

`TaskList` showed 5 tasks all in state `in_progress` with no progress updates and no streamed output. Each had been launched with `run_in_background: true`. The 600s watchdog elapsed without any task emitting a single line.

Polling for output via `TaskOutput` returned empty. No errors, no timeouts in the harness — just silence. Killing and re-running the same tasks in the foreground (synchronously) succeeded within their normal runtime budget.

## Investigation Steps

1. `TaskList` — confirms tasks are stuck `in_progress`.
2. `TaskOutput <id>` for each — empty output suggests the task never started producing.
3. Probe the relevant API in a fresh synchronous process (e.g., `curl <endpoint>` or a tiny `python3 -c "..."` script) to confirm the upstream is reachable.
4. If the fresh probe succeeds, the issue is the background-task harness itself for long-running async work — kill the stuck tasks and re-run synchronously.

## Root Cause

Long-running async tasks inside autonomous blocks are not reliable. The exact mechanism is unclear (harness-side watchdog interaction with the cron-driven session re-entry pattern), but the empirical pattern is consistent: tasks that take >10 min in background mode stall silently more often than tasks run synchronously.

This is NOT specific to one tool — both Agent invocations and Bash `run_in_background` calls exhibited the same pattern.

## Resolution

`autonomous-block` skill v3.0 — added §"Avoid long-running background tasks" under Step 3:

- **Prefer synchronous Bash** with explicit timeout for tasks under 10 minutes.
- **For tasks 10+ minutes:** chunk into smaller sync calls if possible (e.g., generate 1 candidate at a time, commit each).
- **If genuinely async required:** confirm with a fresh-process probe that the API is reachable BEFORE launching the long task. Multiple stalled tasks waste API quota.

## Lessons Learned

1. **Chunk over async.** A task that takes 30 minutes split into 6 sync calls of 5 minutes each is more reliable than a single 30-minute async call.
2. **Probe before async.** A small `curl` or `python3 -c "..."` confirms the upstream is reachable. If the probe fails, the long async task will fail too — but silently and after burning quota.
3. **Don't fan out N background tasks at once.** If one is broken, all N waste resources. Run one, verify it produces output, then consider the next.
4. **`TaskList` is the diagnostic for stuck tasks.** Empty `TaskOutput` + lingering `in_progress` state is the signature.

## Related conventions

- `SKILL.md` §Step 3 — "Avoid long-running background tasks"
