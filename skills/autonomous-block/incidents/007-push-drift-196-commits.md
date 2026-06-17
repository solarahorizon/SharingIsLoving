# Incident 007 — Push drift: 196 unpushed commits over 6 days (2026-05-23 → 2026-05-29)

```yaml
---
id: 007
date: 2026-05-29
title: 196 commits accumulated locally without a single push across 6 days
tags: [autonomous-block, git-push, push-drift, durability, github-backup]
trigger-keywords: ["ahead N", "[ahead 196]", "unpushed commits", "GitHub doesn't show this", "is X on GitHub"]
projects: [Solara Horizon]
related-incidents: [006]
---
```

**Date:** 2026-05-23 → 2026-05-29
**Impact:** Across ~5 autonomous blocks spanning 6 days, 196 commits accumulated on local `main` without a single `git push`. GitHub backup window = 0. Discovered only because the user asked "is X on GitHub?" — the answer was no. Six days of solo work was one disk failure away from total loss.
**Duration:** Drift across 5 blocks; resolution required a single batch `git push` once detected.
**Verified fixed:** 2026-05-29 — `autonomous-block` skill v2.0 codified Step 3a (PUSH-PER-COMMIT GATE), heartbeat step 6 (self-heal push drift), and Step 5a (PUSH-CLEAN wrap-up gate).

---

## Symptom

`git status -sb` reported `## main...origin/main [ahead 196]`. `git log @{u}..HEAD --oneline` listed 196 unpushed commits dating back 6 days. None of the work was visible on the GitHub remote; collaborators and CI saw a 6-day-stale tip.

## Investigation Steps

1. `git status -sb` — the "ahead N" annotation is the primary signal.
2. `git log @{u}..HEAD --oneline` — confirms which commits are unpushed.
3. Cross-check STATUS entries from the prior blocks — they likely show "commit + push" as a single bullet without push verification.
4. Confirm whether each block's wrap-up entry verified `git status` clean. If not, the wrap-up was effectively abandoned.

## Root Cause

"Commit + push" was treated as a single conceptual step but executed as two: commit landed locally, push was deferred to "the end of the block" or "the next commit." Each individual deferral felt small ("just one more, I'll push right after"). After 196 commits, GitHub still had nothing.

The skill's prior wording made push optional-feeling. No gate enforced it as atomic with commit.

## Resolution

`autonomous-block` skill v2.0:

- **Step 3a — PUSH-PER-COMMIT GATE (HARD RULE):** every `git commit` is immediately followed by `git push origin <branch>` in the same turn. No batching. Atomic.
- **Push-failure handling:** if push fails, log CHECKPOINT + PushNotification, and STOP creating new commits until push succeeds. Accumulating local commits on a broken push is the failure mode.
- **Heartbeat step 6 — Self-heal push drift:** every cron fire runs `git log @{u}..HEAD --oneline`; if there are unpushed commits, `git push origin <branch>` BEFORE resuming work. The heartbeat is the safety net if Step 3a slips.
- **Step 5a — PUSH-CLEAN GATE:** before declaring wrap-up complete, `git status -sb` must show clean (no `[ahead N]`). A block that ends with N local-only commits has NOT been wrapped — it has been abandoned.

## Lessons Learned

1. **Treat `commit` and `push` as one atomic action.** Mental separation of the two is exactly the failure mode. The skill body uses "commit + push" as one phrase and the gates enforce it.
2. **A clean `git status` is the wrap-up contract.** A wrap-up entry without a verified-clean working tree is not a wrap-up; it's an abandonment.
3. **Self-heal at the heartbeat level** is the right defense-in-depth — even if Step 3a slips in one turn, the next cron fire catches the drift before more accumulates.
4. **Catching this required a direct question.** Silent local-only commits look identical to pushed-and-shared work in `git log`. The `[ahead N]` annotation is the only signal, and only `git status -sb` (with `-b`) surfaces it.

## Related conventions

- `SKILL.md` §Step 3a — push-per-commit gate
- `SKILL.md` §Heartbeat step 6 — self-heal push drift
- `SKILL.md` §Step 5a — push-clean wrap-up gate
