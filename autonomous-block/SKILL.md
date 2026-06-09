---
name: autonomous-block
description: Disciplined execution of a wall-clock autonomous mandate. Invoke when the user types `/autonomous-block Nh` or says "keep going for N hours," "go autonomous for N hours," "run overnight," "work on this while I'm out," "12 hours block." Sets a recovery heartbeat cron BEFORE any work, locks the start timestamp via `date`, runs the Step 0.5 clarification gate, ships in commit+push pairs, applies the Step 4.5 queue-exhaustion gate when the queue is genuinely empty. HARD-RULE gates throughout the block lifecycle, codified from incidents at `docs/knowledge_base/incidents/`.
allowed-tools: Bash(date:*), Bash(git push:*), Bash(git status:*), Bash(git log:*), Bash(git diff:*), Bash(git commit:*), Bash(git add:*), Bash(git -C *), Read, Edit, Write, Grep, Glob, CronCreate, CronList, CronDelete, AskUserQuestion, PushNotification, Agent
---

# Autonomous Block Skill

**Version:** 3.2 · **Last updated:** 2026-06-09 · **Extracted from production at SolaraHorizon Pty Ltd**

> **About this file.** This is the actual `SKILL.md` running in production. The 12 HARD-RULE gates are universal patterns; the specifics they encode (the user's name, CLAUDE.md cross-references, Swift/iOS examples, project workflow concepts) are illustrative and meant to be adapted.
>
> **What to adapt for your project:**
>
> | Token in this file | What it means | Replace with |
> |---|---|---|
> | "Lynn" | The human running the block | Your name / "the user" |
> | `CLAUDE.md §Dev-Review Gate` / §Shell Discipline / §Git Workflow | Project-specific rules in your `CLAUDE.md` | Your project's equivalents |
> | `feedback_autonomous_block_decision_authority.md` | An auto-memory file specifying user-only decisions | Your decision-authority spec |
> | Swift/iOS sweep items in Step 4.5 (force unwrap, `try!`, `os.Logger`, `.disabled`) | Language-specific lint sweep | Your language's equivalents |
> | `WI` (work item), `PROBLEM doc`, `INFRA backlog` in Step 4.5 | Project-specific workflow labels | Your workflow's labels |

Disciplined execution of a wall-clock autonomous mandate (the user says "keep going for N hours" or invokes `/autonomous-block Nh`).

Each HARD-RULE gate below was codified after a real incident. Full incident reports:

| Incident | Report |
|---|---|
| Timestamp fabrication (2026-05-22) | `docs/knowledge_base/incidents/005_autonomous_block_timestamp_fabrication_2026-05-22.md` |
| ScheduleWakeup socket-drop (2026-05-25) | `docs/knowledge_base/incidents/006_autonomous_block_schedulewakeup_socket_drop_2026-05-25.md` |
| Push drift, 196 commits (2026-05-23 → 29) | `docs/knowledge_base/incidents/007_autonomous_block_push_drift_196_commits_2026-05-29.md` |
| Clarification stall, 10h / 0 lines (2026-05-29) | `docs/knowledge_base/incidents/008_autonomous_block_clarification_stall_10h_0_lines_2026-05-29.md` |
| Empty-heartbeat cycling (2026-05-31) | `docs/knowledge_base/incidents/009_autonomous_block_empty_heartbeat_cycling_2026-05-31.md` |
| Background-task watchdog stalls (2026-06-09) | `docs/knowledge_base/incidents/010_autonomous_block_background_task_watchdog_stalls_2026-06-09.md` |

---

## Proactive trigger (HARD RULE)

If the user uses any of the trigger phrases in the frontmatter `description` and this skill has not been invoked, say: *"I'll set up the autonomous block with heartbeat cron first — give me a moment."* Then invoke this skill BEFORE any other work. Do NOT ask "want me to arm the cron?" — just do it.

Do NOT invoke for tasks < 1h — overhead exceeds value. If phrasing is ambiguous, ask once before invoking.

---

## Step 0 — Pre-flight CronList (HARD RULE — BEFORE ANYTHING ELSE)

```
CronList
```

If an existing `autonomous-block` cron is found, ask the user: replace, keep, or leave both?

---

## Step 0.5 — Instruction Clarification Gate (HARD RULE — codified 2026-05-29, incident 008)

**Resolve ambiguity BEFORE the cron arms, while the user is still at their desk.** Codified because a 10h block once produced 0 lines of code when Claude paused on a skill-choice question at hour 0.5 and the user didn't see it until hour 9.9.

1. Read the user's full prompt once. Identify every directive, named tool/skill/file, constraint.

2. Identify ambiguity classes:

   | Class | Example |
   |---|---|
   | Skill mismatch | Prompt says `/problem-identify` but input is new-capability not a bug |
   | Wrong-tool reference | Prompt names a file/path that doesn't exist |
   | Conflicting constraints | "Zero deps" vs "use SPM packages" |
   | Undefined scope edge | "Build the schema" — but which node types? |
   | Locked-but-stale reference | Prompt cites "197-item catalog" but current is 202 |
   | Workflow placeholder | "Run /X then /Y" where /X doesn't apply |

3. For each ambiguity, judge: does this block implementation if Claude makes the call?
   - **NO** → record judgment + reasoning in STATUS `### Judgments locked`. Do NOT ask the user. Continue.
   - **YES** → batch ALL such questions into ONE `AskUserQuestion` call BEFORE creating the cron. Wait for the user's answer.

4. If zero ambiguities: log "Prompt verified unambiguous; no clarifications needed" under `### Judgments locked`.

5. **Hard rule:** do NOT proceed to Step 1 until either (a) all genuine ambiguities are answered OR (b) all have documented judgments in STATUS.

### User-required ambiguity (cannot be judged)

Cost decisions · architecture/schema locks · destructive operations · public release / App Store gating · counsel/legal-review timing.

### Claude-judges-by-default ambiguity (no AskUserQuestion)

Skill-choice when locked spec exists · convention-defaulted naming · "/X then /Y" sequencing where /X doesn't fit · effort estimates within ±30% · UX path A vs B (per `feedback_autonomous_block_decision_authority.md`).

---

## Step 1 — Lock the start timestamp (HARD RULE — codified 2026-05-22, incident 005)

```bash
date +"%Y-%m-%dT%H:%M:%S%z"
```

Log to STATUS as a DECISION entry:

```markdown
## [real timestamp] — DECISION — Autonomous block start (Nh mandate)

**Start:** [real timestamp]
**Mandate:** N hours wall-clock
**Expected end:** [start + N hours]
**Heartbeat cron:** [to be filled in Step 2b]
**Backlog snapshot:** [link]

### Judgments locked (from Step 0.5)
| # | Ambiguity | Disposition | Reasoning |
|---|---|---|---|

(Or single line: "Prompt verified unambiguous; no clarifications needed.")
```

**Never fabricate the timestamp.** The `date` output is the contract.

---

## Step 2 — Write a prioritized backlog

Draft a backlog of candidate items with rough effort estimates. The backlog lives on disk (BACKLOG.md, STATUS.md, or temp file) — NEVER only in Claude's head.

If the backlog can't fill 80% of the mandate at first draft, spawn web-research agents NOW. Don't start with a thin queue.

### Step 2b — Set a recovery cron (HARD RULE — codified 2026-05-25, incident 006)

```
CronCreate({
  schedule: "17,47 * * * *",   # every 30 min on off-minutes
  command: <locked prompt below>,
  durable: true                 # ALWAYS — survives session death
})
```

**Locked cron prompt template:**

```
[scheduled heartbeat — autonomous-block]

Run §Heartbeat from .claude/skills/autonomous-block/SKILL.md. Probe the API first via `date` (tiny call). If 429/rate-limited: do nothing this cycle, return. If responsive: check elapsed vs mandate from STATUS.md DECISION-start entry; log CHECKPOINT if mid-block, trigger Step 5 wrap-up + CronDelete if past expected end. Read BACKLOG.md for work queue. Idempotent — safe to re-fire. No greeting, no recap. Silent execute.
Project: <PROJECT_PATH>.
```

### Step 2c — VERIFY CRON GATE (HARD RULE — BLOCKING)

After CronCreate, IMMEDIATELY:

```
CronList
```

Verify ALL: cron appears in list with correct schedule · marked `durable: true` · has a job ID.

If ANY verification fails: STOP. Report to the user. Log to STATUS:

```markdown
**Heartbeat cron:** [job ID] — VERIFIED via CronList at [timestamp]
**Schedule:** 17,47 * * * * (every 30 min, durable)
**Next fire:** [next :17 or :47]
```

Only after verification passes may Claude begin work.

---

## §Heartbeat — what the cron-driven session does on fire

1. **API probe (HARD RULE — first action):** run `date "+%Y-%m-%dT%H:%M:%S%z"`.
   - Succeeds → step 2.
   - Fails with 429/rate-limit → do nothing this cycle. Return.

2. **Read block state:** find the most recent `DECISION — Autonomous block start` in STATUS. Extract start timestamp, mandate hours, expected end.
   - If no active block (or wrap-up already written): cron is **orphaned**. `CronList` → `CronDelete` this cron. Return.

3. **Compute elapsed** from `date` output vs start timestamp.

4. **Branch on elapsed vs mandate:**
   - `now >= expected_end` → trigger Step 5 wrap-up + `CronDelete`. Stop.
   - Else → step 5.

5. **Empty-heartbeat counter check (codified 2026-06-01, incident 009).** Read last 3 STATUS CHECKPOINTs. Commits that do not change application behavior — `docs/`, `.claude/`, `MEMORY.md`, BACKLOG/STATUS updates, asset-only changes — are NOT code commits for this count.
   - 0/1/2 of prior 3 empty → queue still active. Append today's CHECKPOINT, resume per BACKLOG.
   - ALL 3 empty AND no new BACKLOG entries → queue provisionally empty. Evaluate §Step 4.5 Queue-exhaustion gate's 5-criteria check. All pass → Step 5 wrap. Any fail → append CHECKPOINT noting which criterion failed + action taken, then resume.

   Trigger fires AT MOST every 3 heartbeats (~1.5h of empty cycles), bounding worst-case waste.

6. **Self-heal push drift (codified 2026-05-29, incident 007):** run `git log @{u}..HEAD --oneline`. If unpushed commits, `git push origin <branch>` BEFORE resuming work. Log to STATUS if drift was found.

7. **Idempotency:** before applying any action, check `git status` + `git log -10` to verify it isn't already done. Multiple queued fires are safe to repeat.

---

## Step 3 — Execute (commit+push per unit, real timestamps)

For each commit:
- Brief in STATUS with real timestamp + elapsed
- Commit + **push (see Step 3a)**
- Update BACKLOG: mark done

### Step 3a — PUSH-PER-COMMIT GATE (HARD RULE — codified 2026-05-29, incident 007)

**`git commit` without `git push` does not count as shipped.** Every commit MUST be followed by `git push origin <branch>` in the same turn. No batching. Treat `commit` and `push` as one atomic action.

If push fails: log CHECKPOINT, surface via PushNotification, DO NOT create more commits until push succeeds. Accumulating local commits on a broken push is the failure mode.

### Make decisions autonomously (codified 2026-05-27)

During an autonomous block, Claude MUST make design and implementation decisions without stopping to ask the user. Log all decisions as a DECISION table in STATUS.md. Research alternatives, pick the better one, log why, ship it. Technical decisions (architecture, data model, algorithm, threshold tuning) are fully autonomous; product-strategy pivots (direction, new feature ideas, user-facing design language) still need the user.

### Keep turns small

Do 2-3 units of work per heartbeat cycle, not 5-6. Large turns risk socket drops. The cron brings you back every 30 min — trust it.

### Avoid long-running background tasks (codified 2026-06-09, incident 010)

- **Prefer synchronous Bash** with explicit timeout for tasks under 10 min.
- **For 10+ min tasks:** chunk into smaller sync calls (e.g., generate 1 candidate at a time, commit each).
- **If genuinely async required:** probe the API in a fresh process (`curl`, tiny `python3 -c "..."`) BEFORE launching. Multiple stalled tasks waste quota.

---

## Step 4 — Mid-block check (HARD RULE)

When you feel "natural completion of the work arc," run `date`. Compute elapsed fraction.

If `elapsed_fraction < 0.8` AND considering wrapping up: **STOP. The queue isn't exhausted — your imagination is.** Refill the queue.

**Exception:** Step 4.5 may override. See below.

---

## Step 4.5 — Queue-exhaustion gate (HARD RULE — codified 2026-06-01, incident 009)

Distinguishes "imagination exhausted" (Step 4 — wrap not authorized) from "queue genuinely exhausted" (acceptable early wrap). When ALL FIVE criteria pass, Step 5 wrap-up is AUTHORIZED regardless of elapsed_fraction:

1. **No-commits window:** last 3 consecutive heartbeats produced ZERO code commits (docs-only OK, doesn't count).

2. **Comprehensive audit sweep completed:** all reachable categories examined; findings either shipped (TINY-tier) OR logged to BACKLOG with classification + promotion path. Document each category checked in the wrap-up STATUS under `### Step 4.5 gate verification`. Default sweep (Swift/iOS example — adapt to your language):
   - Force unwraps + `try!` in production code
   - Empty catch blocks / silent error swallowing
   - `print()` vs `os.Logger` usage
   - `// TODO` / `// FIXME` / `// HACK` comments
   - Disabled tests (`.disabled(...)`)
   - DRAFT WI status drift (shipped WIs still labeled `DRAFT_FOR_USER_REVIEW`)
   - PROBLEM doc status drift (shipped problems still in `docs/PROBLEMS/` root)
   - INFRA backlog entries (PARKED items vs ready-to-promote)

3. **Briefing is current:** the morning briefing reflects cumulative state including post-briefing shipments.

4. **No surfaced launch-blocker** that needs the user's awareness BEFORE they read BACKLOG.

5. **Remaining work all user-decision-gated** (cost / architecture / public release / counsel) and NOT progressable by autonomous judgment.

When ALL FIVE pass: write the Step 5 wrap-up STATUS entry citing each criterion's evidence (under `### Step 4.5 gate verification`), `CronDelete` the heartbeat, exit. Mandate recorded as "Queue exhausted early (5/5 gate criteria met at X% elapsed); time-mandate not reached" — keeps the time-vs-queue distinction explicit.

When ANY criterion fails: continue cron-driven minimal-checkpoint cadence.

---

## Step 5 — Honest wrap-up (HARD RULE)

When you DO wrap, run `date` one more time. Final STATUS entry:

```markdown
## [real timestamp] — DECISION — Autonomous block wrap-up

**Start:** [Step 1 timestamp]
**End:** [this `date` timestamp]
**Mandate:** N hours
**Actual:** X hours Y minutes
**Mandate satisfied?:** Yes / No
[If No: explicit concrete reason]
[Summary of work shipped, queue status, next-session priorities]
```

### Step 5a — PUSH-CLEAN GATE (HARD RULE — codified 2026-05-29, incident 007)

Before declaring wrap-up complete:

```bash
git status -sb               # must show: ## <branch>...origin/<branch>  (no [ahead N])
git log @{u}..HEAD --oneline # must be empty
```

If either shows pending work: commit (or stash with STATUS note), `git push origin <branch>` until clean, log "**Push-clean verified:** [timestamp]" to wrap-up STATUS.

A block that ends with N local-only commits has NOT been wrapped — it has been abandoned.

After wrap-up entry: `CronList` → `CronDelete` the heartbeat cron.

---

## Additional safety measures

- **PushNotification breadcrumb (non-blocking):** if context pressure detected, send a PushNotification. The cron is what saves the block; this just leaves a trace. Example: `PushNotification({message: "Block at Xh/Yh — context getting large. Work saved to git. Cron will resume."})`
- **Commit-per-unit discipline:** every discrete unit (one article, one event, one fix) gets its own commit + push IMMEDIATELY. Never batch 5 into one commit.
- **BACKLOG as single source of truth:** every completed task is marked done in BACKLOG in the same commit as the work. A fresh session reading BACKLOG + git log can reconstruct where to resume.

---

## What this skill does NOT do

- **Does NOT write the dev-review sentinel.** Block-end commits are doc-only (STATUS.md, BACKLOG.md, memory pointer updates) and auto-exempted from the dev-review commit gate per your project's CLAUDE.md §Dev-Review Gate. Code commits *within* a block are still subject to the dev-review gate via the dev-reviewer Agent.
- **Does NOT bypass shell-discipline gates.** All commands must comply with your project's CLAUDE.md §Shell Discipline (e.g., no `cd && git`, no compound pipes, no command substitution, no sleep-poll loops, no parameter expansion). Use `git -C <abs> <cmd>`.
- **Does NOT bypass the merge-to-develop three-gate rule.** Per your project's CLAUDE.md §Git Workflow, merging to develop typically requires unit tests + UI tests + dev-review ALL passing. Blocks ship to feature branches; the merge gate still applies.
- **Does NOT replace human judgment on Tier-3 decisions** (cost, schema lock, public release, counsel timing). Step 0.5 routes these to the user before the cron arms.
- **Does NOT use `ScheduleWakeup` as the primary loop.** `ScheduleWakeup` is session-bound and dies with the session. The CronCreate heartbeat IS the loop. `ScheduleWakeup` may be used as an OPTIONAL intra-turn pacer in ADDITION to the cron.

---

## Deferred enhancements

- **v2 reboot-survivable cron** (state-marker-file design). NOT activated; needs test scenarios A-G to pass before promotion. Current skill survives socket drops + rate limits; v2 would add survival across full Mac restart via a state-marker JSON file.

---

## Skill evolution log

| Version | Date | Change | Incident |
|---|---|---|---|
| 1.0 | 2026-05-22 | Step 1 `date` lock | 005 |
| 1.5 | 2026-05-23 | §Heartbeat + Step 2b cron + Step 2c verify | 006 |
| 2.0 | 2026-05-29 | Step 0.5 clarification gate + Step 3a push-per-commit + Step 5a push-clean | 007, 008 |
| 2.5 | 2026-06-01 | Step 4.5 queue-exhaustion gate + heartbeat empty-counter | 009 |
| 3.0 | 2026-06-09 | Frontmatter + §What this skill does NOT do + background-task guidance | 010 |
| 3.1 | 2026-06-09 | Condensed: incidents moved to `docs/knowledge_base/incidents/005`–`010`; §Failure modes folded into gate annotations | — |
| 3.2 | 2026-06-09 | Wording polish: drift-proof gate-count phrasing; docs-only rule-of-thumb; queue-vs-time-mandate label; misc | — |

**On next change:** bump the version banner at the top of this file, append a row above, and (if codified from a new incident) add the incident report under `docs/knowledge_base/incidents/`.
