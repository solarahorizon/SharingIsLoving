# agent-spawn-budget — put a budget on how many agents Claude Code starts at once

A stdlib-only Python hook that sits in front of Claude Code's `Agent` tool. It
denies a spawn when too many start in quick succession, and denies a spawn that
does not say which model to run. One file, no dependencies.

## The problem

Claude Code will start several subagents when it judges work parallelisable.
That is a good default when tokens are not your constraint. On a capped weekly
subscription it is the largest single line, because a subagent is not a function
call. It is another conversation: its own context, re-read on every one of its
turns, counted the whole way.

Measured on one machine, from the raw session transcripts, with the tool's own
`--report`:

```
Spawns issued from main sessions: 1194
A spawn made BY a subagent lives in that subagent's transcript and is not counted here.

At the current budget of 2 per 120s, the hook would have denied 66 of them (5.5%).

Clusters. Each spawn in a cluster is within 120s of the PREVIOUS one, so a
cluster can span longer than the window, and the widest span says by how much.
   size      clusters   spawns    share  widest span
   1              895      895    75.0%           0s
   2               72      144    12.1%         116s
   3               23       69     5.8%         185s
   4               11       44     3.7%         145s
   5                2       10     0.8%         127s
   6                2       12     1.0%         256s
   8                1        8     0.7%          50s
   12               1       12     1.0%         130s

What one agent costs, from 1297 subagent transcripts.
A different population from the spawns above: it includes agents started by
other agents, which the spawn scan never sees.
   median first turn           47,770 tokens  (the cold start, output excluded)
   median whole life        7,047,370 tokens  (every field, every turn)
   total               14,146,468,557 tokens

   six median agents: 42,284,220 tokens. That is arithmetic, not a measured cluster.

What those tokens are. A cache read bills far below fresh input, so read this
split before turning any total above into money. Against a subscription's usage
limit the raw token count is the figure that matters; against an invoice it is not.
   input_tokens                          4,246,543    0.0%
   cache_creation_input_tokens         719,365,730    5.1%
   cache_read_input_tokens          13,382,407,996   94.6%
   output_tokens                        40,448,288    0.3%
```

**The cold start is not the expensive part.** Starting an agent costs about
48,000 tokens of context. Living costs 7 million, so the cold start is 0.7% of
one agent and the other 99.3% is the agent living. The decision that costs you
is not how big the opening brief was, it is how many separate conversations you
agreed to pay for.

**Read the token split before turning any of this into money.** `--report`
prints it: on that machine 94.6% of the total is cache reads, which bill far
below fresh input. Against a subscription's usage limit the raw token count is
the figure that matters. Against an invoice it is not.

## Install

Copy `agent_spawn_budget.py` anywhere and register it as a `PreToolUse` hook, in
`.claude/settings.json` or `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Agent|Task",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/agent_spawn_budget.py --hook"
          }
        ]
      }
    ]
  }
}
```

The matcher names both because the spawn tool is called `Agent` on some builds
and `Task` on others. The hook accepts either and ignores every other tool, so
matching both is safe.

## What it denies

| Rule | Default | Why |
|---|---|---|
| `burst_max` in `burst_window_seconds` | 2 in 120s | Six at once is six conversations paid for, not one. `burst_max: 0` denies every spawn, so switch the rule off with a number above any real fan-out instead. |
| `require_explicit_model` | on | Where neither the agent definition nor a configured default names a model, an unset one inherits the parent session's, the priciest in play. |
| `session_max` | off | A lifetime ceiling for one session, if you want one. |
| `exempt_subagent_types` | none | Name the agents that must never be blocked, such as a review gate, or a `fork`, which always inherits its model and cannot satisfy the rule above. |
| `enforce` | on | Set false to print each would-be denial on stderr and block nothing. An allowed spawn stays silent. |

Put overrides in `$CLAUDE_PROJECT_DIR/.claude/agent-spawn-budget.json`, which
wins, or `~/.claude/agent-spawn-budget.json`. A key of the wrong type is
ignored, its default used, and a line printed on stderr saying so. A file that
will not parse is skipped, so a broken project config falls through to the home
one rather than hiding it.

A denial is not a wall. It is a question, and it prints the way through:

```
agent_spawn_budget.py --allow "six independent read-only file sweeps" --spawns 6 --minutes 15
```

The grant expires, covers a fixed number of spawns, and leaves the reason on
disk. It binds to the first session that uses it, so a grant made for one
fan-out cannot be split across the other sessions you have open; `--session <id>`
binds it up front. Fanning out stays possible. Fanning out by accident does not.

## Other runs

```
python3 agent_spawn_budget.py --report    # measure your own spawn history and its cost
python3 agent_spawn_budget.py --status    # config, per-session counters, any live grant
python3 agent_spawn_budget.py --revoke    # cancel a grant early
python3 test_agent_spawn_budget.py        # 125 self-tests, no network, throwaway HOME
```

`--report` reads `~/.claude/projects/**/*.jsonl` on your own machine and prints
the tables above for your own history. Nothing leaves the machine. It has no
date floor, so it covers everything you still have on disk and the exact digits
move as you work.

## How it behaves when things go wrong

Several sessions and several hooks can fire in the same instant, so every
read-modify-write holds an exclusive lock. Without one, six hooks all read the
same pre-burst state and all allow, which is the exact case the tool exists for;
the test suite starts six at once and checks that a budget of two lets two
through.

A malformed payload, an unreadable state file, a broken config, a read-only
home and a full disk all allow the spawn and print a line on stderr. The hook
exits 0 on every path, a denial included, so it can never block your work by
crashing. It can stop enforcing, on a disk it cannot write, and when it does it
says so in that line rather than going quiet.

A denied spawn is not counted against the budget, because it never ran.

Two limits worth knowing. On a filesystem where `flock` is a no-op, which some
network and FUSE mounts are, the lock is not real and the race above returns
with no signal; keep the state on a local disk. And the hook sees only the
`model` on the spawn itself, so it denies an absent one whether or not an agent
definition or a configured default would have supplied it.

## Licence

MIT. See `LICENSE` at the repository root.
