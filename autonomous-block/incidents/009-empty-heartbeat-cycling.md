# Incident 009 — Empty-heartbeat cycling: ~6h of CHECKPOINT-only commits (2026-05-31)

```yaml
---
id: 009
date: 2026-05-31
title: Queue exhausted at hour 3 of a 12h block; cron fired empty for 9h
tags: [autonomous-block, queue-exhaustion, empty-heartbeat, early-wrap, audit-sweep]
trigger-keywords: ["empty CHECKPOINT", "no actionable work", "cron firing nothing", "queue exhausted early"]
projects: [SolaraHorizon]
related-incidents: [005]
---
```

**Date:** 2026-05-31 (evening block)
**Impact:** A 12h evening block exhausted its actionable queue at ~3h in. The remaining ~9h fired heartbeat crons every 30 min with no work to do, producing empty `CHECKPOINT`-only commits to STATUS.md. ~12 wasted cycles × ~30 min = ~6h of API tokens burned for zero throughput value.
**Duration:** Queue exhaustion at ~T+3h; wasted cycles ran until ~T+9h.
**Verified fixed:** 2026-06-01 — `autonomous-block` skill v2.5 codified Step 4.5 (Queue-exhaustion gate) with 5 criteria + the heartbeat empty-counter check (3 consecutive empty CHECKPOINTs → evaluate Step 4.5).

---

## Symptom

STATUS.md tail showed a long string of CHECKPOINT entries, each citing zero code commits in its window, each containing only "no actionable work surfaced this cycle" or equivalent boilerplate. Git log between CHECKPOINT entries was empty for code paths — only `docs/` STATUS updates.

Cron continued firing on the `17,47` schedule, each fire producing another empty CHECKPOINT, until the mandate's expected-end time triggered Step 5 wrap-up.

## Investigation Steps

1. Read the last ~10 STATUS CHECKPOINT entries. Count how many cite zero code commits in their windows.
2. Check `git log --since=<block-start>` filtered to non-doc paths. If sparse or empty for the latter portion of the block, the queue exhausted before mandate end.
3. Check whether the skill at the time had an early-wrap clause. If not, the cron will keep firing regardless of queue state.

## Root Cause

Step 4 of the skill ("if `elapsed_fraction < 0.8` AND considering wrapping up: STOP, the queue isn't exhausted, your imagination is") was codified to prevent the timestamp-fabrication failure mode (Incident 005). It correctly refuses imagination-driven early wraps — but it gave no exit clause for the OPPOSITE failure mode: a genuinely-empty queue at <80% elapsed.

Result: when the queue WAS actually exhausted, the skill had no authorized way to stop. The cron loop continued faithfully but produced no work.

## Resolution

`autonomous-block` skill v2.5 — **Step 4.5: Queue-exhaustion gate.** 5 criteria, ALL must pass to authorize early wrap:

1. **No-commits window:** last 3 consecutive heartbeats produced ZERO code commits (docs-only OK but doesn't count).
2. **Comprehensive audit sweep completed:** all reachable categories examined (language-specific lint sweep — force unwraps / silent error swallowing / logger misuse / TODO/FIXME / disabled tests / workflow-status drift) — findings shipped OR logged to BACKLOG with classification.
3. **Briefing is current:** the morning briefing reflects cumulative state including post-briefing shipments.
4. **No surfaced launch-blocker** awaiting user awareness before BACKLOG read.
5. **Remaining work all user-decision-gated** (cost / architecture / public release / counsel) and not progressable by autonomous judgment.

**Heartbeat empty-counter check (added same revision):** counts consecutive empty CHECKPOINTs at STATUS tail. If 3 consecutive empties + no new BACKLOG entries, evaluate Step 4.5. All 5 pass → Step 5 wrap. Any fails → append CHECKPOINT noting which criterion failed + what action was taken, then resume.

This converts Step 4.5 from opportunistic to deterministic. The trigger fires at most every 3 heartbeats (~1.5h of empty cycles), bounding worst-case waste.

## Lessons Learned

1. **"Queue genuinely exhausted" ≠ "imagination exhausted."** Step 4 protects against the latter. Step 4.5 protects against the former. Both are needed.
2. **Continuing to fire heartbeats past genuine exhaustion is not discipline — it's compulsive cycling.** The cron is a safety net for active blocks, not a metronome for empty ones.
3. **Why FIVE criteria rather than one:** any single criterion alone is too easy to satisfy through laziness. The audit-sweep criterion is the load-bearing one — it forces a comprehensive check before authorizing wrap.
4. **The empty-counter is the deterministic trigger.** Without it, Step 4.5 stays opportunistic; with it, the gate fires reliably after ~1.5h of empty cycles.

## Related conventions

- `SKILL.md` §Step 4 — imagination-exhaustion refusal
- `SKILL.md` §Step 4.5 — queue-exhaustion gate (5 criteria)
- `SKILL.md` §Heartbeat step 5 — empty-counter check
