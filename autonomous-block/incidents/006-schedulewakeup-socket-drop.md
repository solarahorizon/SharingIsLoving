# Incident 006 — ScheduleWakeup socket-drop lost 8.5h (2026-05-25)

```yaml
---
id: 006
date: 2026-05-25
title: ScheduleWakeup is session-bound — socket drop killed an unattended block
tags: [autonomous-block, schedulewakeup, cron, session-bound, recovery, durable]
trigger-keywords: ["ScheduleWakeup", "block stopped progressing", "session died", "wakeups cancelled"]
projects: [Solara Horizon]
related-incidents: [005, 007]
---
```

**Date:** 2026-05-25
**Impact:** 12h autonomous block used `ScheduleWakeup` as the primary loop mechanism. Socket dropped at ~3.5h; session died. `ScheduleWakeup` is session-bound — its scheduled fires died with the session. No heartbeat existed to resume. **8.5h of work lost.**
**Duration:** Drop at ~T+3.5h; discovered when the user returned at ~T+12h.
**Verified fixed:** 2026-05-25 — `autonomous-block` skill v1.5 codified Step 2b (`CronCreate` with `durable: true`) and prohibited `ScheduleWakeup` as the primary block-loop mechanism.

---

## Symptom

Block stopped progressing silently. Last STATUS entry was at ~T+3.5h. No subsequent CHECKPOINT entries, no commits, no completion of the wrap-up ceremony. On session-restart inspection, no scheduled wakeups were pending — they had been cancelled when the previous session terminated.

## Investigation Steps

1. Check the previous session's STATUS entries for the last activity timestamp.
2. Look for the loop mechanism the skill used — `ScheduleWakeup` vs `CronCreate`.
3. If `ScheduleWakeup` only: confirm the session-bound semantics in the tool description. The scheduled wakeups die with the session that created them.
4. Confirm no `durable: true` cron was registered — `CronList` shows the active set.

## Root Cause

`ScheduleWakeup` schedules a callback inside the current session. When the session dies (socket drop, rate limit, user exit), all pending `ScheduleWakeup` callbacks die with it. The block had no out-of-session safety net.

`CronCreate({durable: true})` survives session death. The cron fires regardless of whether the original session is alive; a fresh session picks up the cron's prompt and resumes.

## Resolution

`autonomous-block` skill v1.5:

- **Step 2b:** `CronCreate` with `durable: true` is mandatory for ALL blocks ≥ 1h.
- **Step 2c — VERIFY-CRON GATE:** call `CronList` immediately after `CronCreate` to confirm registration. STOP if verification fails.
- **Measure 4:** `ScheduleWakeup` is prohibited as the primary loop. May be used as an optional intra-turn pacer in addition to the cron, never instead.
- **§Heartbeat protocol:** codifies what the cron-driven session does on each fire (API probe, elapsed compute, CHECKPOINT, idempotency check).

## Lessons Learned

1. **`ScheduleWakeup` is session-bound. Crons are not.** For any process spanning multiple sessions (autonomous blocks, recurring loops > 1h), use `CronCreate({durable: true})`.
2. **Verify cron registration before starting work.** If `CronList` doesn't show the new cron, the rest of the block's safety net is illusory.
3. **The cron prompt template should be self-contained.** The fresh session that wakes up has no memory of the original; the cron's prompt must tell it where STATUS lives, what to do, and when to stop.
4. **Idempotency in the heartbeat protocol** — multiple queued fires after a long stall must be safe to re-execute. Always check `git status` + `git log -10` before applying any action.

## Related conventions

- `SKILL.md` §Step 2b — CronCreate gate
- `SKILL.md` §Step 2c — verify-cron gate
- `SKILL.md` §Heartbeat — what the cron-driven session does
