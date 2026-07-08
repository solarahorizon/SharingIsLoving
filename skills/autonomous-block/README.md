# How to run a 14-hour Claude Code autonomous block

What it is, why it works, and the five ingredients that hold it together — plus the clean-shell hook that keeps it from stalling on itself.

This repo contains the **actual `SKILL.md`** running in production at Solara Horizon Pty Ltd, plus the postmortem incidents that earned each rule. Happy for anyone to adapt.

```
README.md                     ← this file (the conceptual overview)
SKILL.md                      ← the skill itself (~330 lines, v3.2)
hooks/
  pre-bash-discipline.py      ← the "clean-shell" PreToolUse hook
incidents/
  TEMPLATE.md                 ← lazy-load incident template
  005-010.md                  ← six sanitised postmortems (one per rule)
(LICENSE — MIT, at the repo root)
```

---

## What's an "autonomous block"?

A wall-clock mandate where Claude Code works through a backlog unattended for N hours — "keep going for 14 hours while I'm out" — and ships actual production-ready commits without you having to babysit each tool use.

Distinct from:
- **Interactive turns.** Claude does one task, asks for confirmation, you respond. Bounded by your presence.
- **Single long task.** Claude works on one thing for an hour. No queue management.
- **`/loop`.** A built-in repeater that re-fires the same prompt; different shape. Full comparison at the end of this doc.

An autonomous block is closer to giving a junior engineer a backlog + their own laptop + a clear deadline.

---

## The five ingredients

1. **Auto-mode on.** Claude makes decisions without pausing to ask for each tool use. Set in `~/.claude/settings.json`:

   ```json
   { "permissions": { "defaultMode": "auto" } }
   ```

   Without this, every Bash call halts the block waiting for your approval.

2. **A "heartbeat" cron** that fires every 30 min via `CronCreate`. Checks the session is alive, resumes work if it dropped, deletes itself when the mandate expires. Survives socket drops, server-side rate limits, and your Claude plan resetting mid-block. The cron is the safety net that catches the failure mode where the session silently dies overnight.

3. **Disk-backed backlog** (`BACKLOG.md` + `STATUS.md`). Claude reads what to work on from disk, not from conversation memory. A dead session can be revived from these files alone. The backlog must always reflect current state; every completed task gets marked done in the same commit as the work.

4. **Push-per-commit discipline.** Every `git commit` is immediately followed by `git push origin <branch>`. No batching ("I'll push at the end"). GitHub is the durable backup; nothing is "shipped" until pushed. This sounds obvious, but 196 commits piled up unpushed across 6 days before it became a hard rule.

5. **A custom `autonomous-block` skill** that orchestrates all the above. It locks a real start timestamp via `date` (not made up), runs an instruction-clarification gate so ambiguity is resolved while you're still at your desk, arms the heartbeat cron BEFORE work begins, writes per-work-unit commits, applies a queue-exhaustion gate before authorising an early wrap, and does an honest wrap-up at the end with actual elapsed time. The skill (`SKILL.md` in this repo) encodes every lesson the project has learned.

   The end-of-block wrap-up pairs naturally with the companion **`local-artifact`** skill (also in this repo): instead of a wall of terminal text, the block's outcome renders as a single self-contained HTML page you can open, keep, and version-control — a scannable summary of what shipped overnight. Wiring `local-artifact` into the wrap-up step is the recommended finishing touch.

---

## The six failures that earned the rules

Every gate in the skill maps to a real incident. Each failure → one rule encoded.

| Date | What broke | Rule added |
|---|---|---|
| 2026-05-22 | Claude fabricated STATUS timestamps to match a 6h mandate (the work "felt like 6h", so the timestamps did too) | `date` lock — real `date` output is the contract; no fabricated timestamps anywhere |
| 2026-05-25 | 12h block lost 8.5h — used `ScheduleWakeup` instead of `CronCreate`; session died at 3.5h with no recovery; the block didn't resume until I noticed in the morning | Heartbeat cron via `CronCreate` (durable: true) — armed and `CronList`-verified BEFORE any work starts |
| 2026-05-23 → 29 | 196 commits accumulated locally without a single `git push` across 6 days. Discovered only when I asked "is X on GitHub?" — GitHub backup window = 0 for solo work | Push-per-commit gate — every `commit` is followed by `push` in the same turn; treat as one atomic action |
| 2026-05-29 | 10h block produced 0 lines of code — Claude paused at hour 0.5 on a skill-choice question and waited; I didn't see it until hour 9.9 | Step 0.5 instruction-clarification gate — all genuine ambiguities batched into ONE question BEFORE the cron arms, while user is still at desk |
| 2026-06-01 | Heartbeat fired for hours after the real queue was exhausted; STATUS filled with empty CHECKPOINTs; tokens burned for no work | Step 4.5 queue-exhaustion gate — after 3 consecutive empty heartbeats, run a 5-criteria sweep; if all pass, wrap early; if any fail, log which + resume |
| 2026-06-09 | 5 background tasks stalled silently at the 600s watchdog limit. Quota burned, no output, no error surfaced | Avoid long-running background tasks — prefer synchronous Bash <10min; for 10+ min chunk into commits-per-piece; if genuinely async required, probe the API in a fresh process first |

The skill is, in effect, six postmortems that run every time.

---

## What this survives

The heartbeat-cron + disk-backed-state design survives more than just session deaths. Three classes of failure are caught automatically — no special handling, no human babysitting:

| Failure mode | What happens | How it recovers |
|---|---|---|
| **Socket drop / session death** | Current session terminates mid-turn | Cron is durable (survives session exit); next scheduled fire spawns a fresh session that reads STATUS and picks up where the prior session stopped |
| **User hits Claude plan usage-limit mid-block** | Current session dies on `usage_limit_error` | Cron keeps firing on schedule; once the limit resets (next day / next reset window), a fresh fire lands cleanly and work resumes from STATUS. **No manual restart needed when you wake up.** |
| **Anthropic API server-side rate-limit (429)** | Current turn fails before doing work | §Heartbeat probes the API first via `date`; if 429, the cycle exits silently. Next 30-min fire retries. Zero tokens burned on a doomed turn |

The design treats every cron fire as a fresh-start attempt. Whatever broke the prior session — drop, plan limit, server throttle — doesn't matter; the cron is the recovery loop.

The 14h block doesn't require never-failing infrastructure. It just requires the recovery loop to be cron-driven rather than session-driven.

---

## The clean-shell hook — blocking the commands that stall a block

The five ingredients keep the block *running*; this hook keeps it from *stalling on itself*.

The worst autonomous-run failure is silent: the agent issues a command shape that trips a permission prompt the allow-list **can't** silence, or that hangs long enough to hit a stream-idle timeout. Either one freezes the block waiting on a human who isn't there. "Just remember the good form" wasn't enough — it decayed under context pressure — so it became a hard `PreToolUse` hook that blocks the shape and names the prompt-free equivalent.

`hooks/pre-bash-discipline.py` in this repo is the actual hook (MIT — adapt to your own stack). What it blocks and what to do instead:

| Blocked | Why it stalls | Prompt-free equivalent |
|---|---|---|
| `cd <dir> && git/gh` (or `; git`) | trips the "untrusted hooks from target directory" prompt | `git -C <abs-path>` (or `gh -R owner/repo`) in one call |
| `\| head/grep/wc/tail/…` | output is invisible to the tool result + often huge | the Grep tool (count mode) / Read tool (offset+limit) |
| `2>/dev/null`, `&>/dev/null`, `>/dev/null 2>&1` | hides the errors you actually need to see | drop the redirect (redirecting to a real log file is fine) |
| `$(...)` / backticks (except `$(cat <<…)`) | nests a command the tool can't audit | run it as its own call, reuse the literal value |
| `until/while … do … sleep` | burns tokens, can idle past the stream timeout | the Monitor tool |
| `$?` (exit-code reference) | redundant | the Bash result already carries the exit code |

Every blocked form has a prompt-free equivalent that does the same thing — so it's not a loss of capability, just the road that skips the tollbooth. Wire it as a `PreToolUse` hook on the `Bash` matcher in `.claude/settings.json` (snippet at the top of the file). It runs on **every** Bash call, not just during a block: the habit only holds during a block if it holds in every session.

---

## Model requirement (read before adopting)

This skill needs a **Claude Opus-class model** (Opus 4.x or later). In our testing, Sonnet won't hold the gates through an unattended block.

Tested both extensively in production:
- **Opus** follows the HARD-RULE gates reliably — Step 0.5 clarification, Step 3a push-per-commit, Step 4.5 queue-exhaustion all fire as written.
- **Sonnet** routinely skips the gates even when the rules are explicit and bolded. The empty-heartbeat counter, the clarification batching, the push-after-commit discipline — Sonnet treats them as suggestions rather than hard rules. No amount of phrasing tightening fixed this.

The instruction-following discipline gap is the difference between blocks that ship and blocks that quietly fail. If you're forced to use Sonnet, expect to babysit; the unattended-overnight pattern won't work.

This isn't a knock on Sonnet — it's a tool selection issue. Sonnet has strengths Opus doesn't. But for multi-hour autonomous discipline with binding gates, Opus is the practical floor.

---

## How I kick it off

I type one of these in Claude Code:

- `/autonomous-block 14h work on X`
- "keep going for 14 hours"
- "go autonomous for 14 hours while I'm out"
- "run overnight"

The skill detects the phrasing, runs the Step 0.5 clarification gate (batches any blocking ambiguities into one question), arms the cron, locks the timestamp via `date`, drafts a prioritised backlog to disk if one doesn't exist, then starts working in 2–3 commit units between heartbeats. Each commit is pushed immediately. When the queue feels empty, the Step 4.5 5-criteria gate runs before any wrap is authorised. The wrap-up at the end is honest about whether the mandate was satisfied — both in wall-clock terms and in queue-exhaustion terms.

---

## What the discipline catches

Real failure modes the rules block:

- **"Natural completion feeling = done"** — Claude finishes the queue at 3h of a 14h mandate and starts wrapping. The rule: if elapsed < 80%, the queue isn't exhausted — your imagination is. Refill the queue. (Step 4 mid-block check.)
- **"Imagination exhausted" masquerading as "queue exhausted"** — wrapping at 30% because nothing visible remains in the backlog, when an audit sweep would surface dozens of latent items. The rule: 5-criteria gate (no-commits window + comprehensive audit + briefing current + no surfaced blocker + remaining work all decision-gated) must ALL pass before early wrap is authorised. (Step 4.5.)
- **Ambiguity-stall before the cron arms** — Claude pauses 30 min in to ask "should I use approach A or B?" and waits 9 hours for an answer. The rule: resolve all genuine ambiguity BEFORE arming the cron, while user is still at desk. (Step 0.5.)
- **Large turns accumulating context** — a turn that does 5–6 work units risks socket drop mid-turn. The cron brings you back every 30 min regardless; trust it. Keep turns to 2–3 units.
- **Skipping reviews on "mechanical" changes** — when the backlog feels like grunt work, the temptation is to skip pre-commit review. Don't. A 10h autonomous block proved that "small" changes ship unreviewed bugs at the same rate as big ones.
- **Push drift on the last commit before sleep** — "I'll push when I wake up" loses commits if the session dies overnight. Push-per-commit catches this. (Step 3a.)
- **Background tasks stalling at watchdog limits** — fire-and-forget long-running tasks die silently at 600s with no error surfaced. The rule: prefer sync, chunk if long, probe before launching async. (Codified after 5 stalled tasks in one block.)

---

## What you need to set up

If you want to try this in your own Claude Code:

1. **Auto-mode on** in `~/.claude/settings.json` (`"defaultMode": "auto"`)
2. **Allow-list** for common Bash commands in `.claude/settings.local.json` so each call doesn't prompt (cumulative list grows over time)
3. **`CronCreate` + `CronList` + `CronDelete` tools** — standard Claude Code primitives once the right plugins are enabled
4. **The `SKILL.md` from this repo** copied to `.claude/skills/autonomous-block/SKILL.md` in your project, adapted to your conventions (see the disclaimer at the top of `SKILL.md`)
5. **A real backlog file** (`BACKLOG.md`) the skill can read + update. This is the most underrated ingredient — the discipline of "the backlog lives on disk, not in Claude's head" is what makes dead-session-recovery work
6. **An incident log** (`docs/knowledge_base/incidents/*.md` or wherever) the skill references for full-context postmortems. The skill stays under 500 lines by linking to incident files rather than narrating each in-line — load only what you need

The skill is around 330 lines of project-specific discipline. Each gate was added in response to something that broke. v1.0 itself was the response to the timestamp-fabrication failure; the pre-skill informal version offered no protection.

---

## How is this different from `/loop`?

Both are unattended, but different shapes:

| Dimension | `/loop` (built-in) | `/autonomous-block` (custom) |
|---|---|---|
| **What it does** | Re-fires the SAME prompt on an interval | Drains a VARIED backlog within a wall-clock window |
| **Per-cycle work** | Same task repeats ("check deploy", "poll PRs") | Different task each turn (Claude picks next item from `BACKLOG.md`) |
| **State across cycles** | Mostly stateless — each tick independent | Heavily stateful — `BACKLOG.md` + `STATUS.md` persist progress |
| **Stop condition** | User cancels OR condition met | Wall-clock elapsed (Nh) OR queue exhausted via 5-criteria gate |
| **Recovery from session death** | Next interval fires retries the same prompt | Heartbeat cron + `STATUS` DECISION-start entry tells next session WHERE to resume |
| **Commit discipline** | None built-in | Push-per-commit hard rule; `date`-locked timestamps |
| **Built-in or custom?** | Built-in Claude Code skill | Custom project skill (~330 lines) |
| **Best for** | Monitoring, polling, repeated checks | Multi-task dev work, backlog drain |

**When to use which:**

- **`/loop`** when the work is "the same thing, again":
  - "Check CI status every 5 min until green"
  - "Keep running `/babysit-prs`"
  - "Watch this log file for errors"

- **`/autonomous-block`** when the work is "many different things from a queue":
  - "Build out a feature + its docs for 14 hours"
  - "Go autonomous for 6 hours, work through items tagged for autonomous work"
  - "Run overnight, ship as much of the backlog as you can"

**They can compose.** During an autonomous block, Claude might internally use `/loop`-style polling (e.g., "poll the job_id every 5s until done"). The outer container is the block; `/loop` is one tool inside it.

**One-line distinction:** `/loop` is a **repeater** — same prompt, interval-driven, lightweight. `/autonomous-block` is a **drainer** — varied queue, time-bound, heavyweight (cron + backlog + commits + clarification gate + queue-exhaustion gate + wrap-up).

---

## TL;DR

Auto-mode + a heartbeat cron + a disk-backed backlog + push-per-commit + a custom orchestration skill that ties it all together.

The discipline was earned the hard way — six failures, six gates. The skill is the postmortem that runs every time.

---

*Author: Lynn Yang, Solara Horizon Pty Ltd. 2026-06-09. MIT licensed — happy for anyone to adapt.*
