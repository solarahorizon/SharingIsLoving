# Incident 008 — Clarification stall: 10h block shipped 0 lines (2026-05-29)

```yaml
---
id: 008
date: 2026-05-29
title: Claude paused on a skill-choice question at hour 0.5, user saw it at hour 9.9
tags: [autonomous-block, ambiguity, askuserquestion, kickoff, clarification-gate]
trigger-keywords: ["block shipped nothing", "AskUserQuestion during autonomous", "hour 0.5 stall", "should I use approach A or B"]
projects: [Solara Horizon]
related-incidents: []
---
```

**Date:** 2026-05-29
**Impact:** A 10h overnight autonomous block produced **0 lines of code.** At hour ~0.5, Claude paused on a skill-choice question and issued an `AskUserQuestion`. The user was already asleep. They didn't see the question until hour ~9.9 — by which time the session context was 90% full and the block was effectively over.
**Duration:** Stall began at ~T+0.5h; only resolved at ~T+9.9h after the user returned.
**Verified fixed:** 2026-05-29 — `autonomous-block` skill v2.0 codified Step 0.5 (Instruction Clarification Gate) which forces all clarifications BEFORE the heartbeat cron arms, while the user is still at their desk.

---

## Symptom

STATUS showed a start-block DECISION entry at ~T+0, an `AskUserQuestion` invocation at ~T+0.5h, and then nothing. No CHECKPOINTs, no commits, no wrap-up — just silent waiting on a question the user couldn't see until they next opened the laptop.

The heartbeat cron fired on schedule (it was correctly armed) but each fire saw a pending `AskUserQuestion` and could do no useful work; it logged minimal CHECKPOINTs that burned context tokens.

## Investigation Steps

1. Check the STATUS file for the gap between the `AskUserQuestion` entry and the next non-checkpoint entry.
2. Confirm the question was posed AFTER cron arm (the failure mode) vs BEFORE (the protected case).
3. Audit whether the ambiguity was Claude-judgeable or genuinely required user input. Many "ambiguities" are actually skill-choice or convention-defaulted — Claude can judge those.

## Root Cause

The ambiguity (skill-choice — which named workflow to use) was Claude-judgeable: the work shape pointed clearly to one of the two options. Claude could have called the judgment, documented it in STATUS under `### Judgments locked`, and proceeded.

Instead, Claude defaulted to "ask the user" — but the user was already away (autonomous block, overnight). The question landed in a queue the user wouldn't see for ~9.4 hours.

The skill's prior shape didn't distinguish between "Claude should judge this" and "the user must answer this." All ambiguity routed to `AskUserQuestion`.

## Resolution

`autonomous-block` skill v2.0 — **Step 0.5: Instruction Clarification Gate** added BEFORE Step 1 (timestamp lock) and BEFORE Step 2b (cron arm). The gate:

1. Reads the user's full prompt once.
2. Identifies ambiguity classes (skill mismatch / wrong-tool reference / conflicting constraints / undefined scope edge / locked-but-stale reference / workflow placeholder).
3. For each ambiguity, judges whether it blocks implementation if Claude calls it.
   - **NO:** record the judgment + reasoning in STATUS under `### Judgments locked`. Do NOT ask the user. Continue.
   - **YES (genuine choice with implementation consequence):** batch ALL such questions into ONE `AskUserQuestion` call. Ask BEFORE the cron arms. Wait for the answer.
4. Lists ambiguity classes that ALWAYS require user input (cost / architecture / destructive ops / public release / counsel) vs classes Claude should ALMOST ALWAYS judge (skill choice with locked spec / convention naming / sequencing where /X doesn't fit / ±30% effort estimates / UX path A vs B).
5. Hard rule: do not proceed to Step 1 until either (a) all genuine ambiguities are answered OR (b) all ambiguities have documented judgments in STATUS.

The gate is positioned BEFORE cron creation so the user answers while still at the desk; the cron starts only after work can proceed.

## Lessons Learned

1. **Resolve ambiguity at kickoff, not at hour 0.5.** The user is present at kickoff and absent during the block. Every "let me ask" issued after the user leaves wastes the rest of the mandate.
2. **Distinguish Claude-judgeable from user-required ambiguity.** Most ambiguity falls in the "Claude judges + documents" bucket. Asking the user is the exception, not the default.
3. **Batch all genuine questions into ONE `AskUserQuestion` call.** Don't fire two separate questions if you can batch them. The tool allows up to 4 questions per call.
4. **An empty heartbeat is not a heartbeat — it's wasted context tokens.** Cron fires during a pending question burn tokens for no progress. Hence: clarification BEFORE cron.

## Related conventions

- `SKILL.md` §Step 0.5 — Instruction Clarification Gate
