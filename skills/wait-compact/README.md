# wait-compact: compact the conversation while Claude Code waits

A Claude Code mod. When a main-loop turn ends with the conversation at 120,000
tokens or more, and then nothing happens for four minutes, it compacts: it swaps
the conversation for a summary while the prompt cache is still warm. Any new
turn inside those four minutes (you typed, a background job reported) cancels
it, so a short wait leaves the conversation alone.

The summary is told to keep the task, its plan and the next step, every
background job still running by id and what to do with its result, any
scheduled wake-up, and any question put to you that is still unanswered, word
for word.

## Why it exists

Every message re-sends the whole conversation. The prompt cache keeps a copy
that is cheap to read again, 0.05 times the input price, but only for five
minutes. After that the next message stores the whole conversation again, at
1.25 times the input price: 25 times what reading it would have cost.

Agents wait a lot. On a build, on a review agent, on you. Every wait past five
minutes pays that re-store on a conversation that by then is often well over
100,000 tokens.

Compacting costs something too: one cached read of the conversation and the
summary it writes. So it only pays when the wait that follows is long. The
first version compacted the moment a turn ended. Most of those waits were short,
it kept throwing away a warm cache for nothing, and it broke even. Waiting four
minutes first is what made it pay: a wait that has already lasted four minutes
is usually a long one, and the cache is still warm when the compaction reads it.

## What it saved

One Mac, 3 to 13 November 2026, list prices for the model in use, the official
five-minute cache line:

- 273 compactions priced; 10 of them too early (the next message came within five minutes)
- median wait after a compaction: 12 minutes
- the next message stored about 26,000 tokens instead of 148,000
- $143 saved against $2,011 of main-agent spend, about 7%

Priced per compaction as: with the mod, one cached read of the conversation,
the summary's output, and the next call as it really ran; without it, a full
re-store of the conversation if the gap was over five minutes, else a cached
read. Later messages in the same session are cheaper too, because the
conversation stays smaller. That is not counted. Neither is any work redone
because a summary dropped a detail.

## Install

Copy this folder to `~/.claude/skills/wait-compact/` (every project) or to a
project's `.claude/skills/wait-compact/`. It loads in the next session. Tested
on Claude Code 2.1.323.

```
claude plugin test ~/.claude/skills/wait-compact     # 18 tests
```

## Settings

Constants at the top of `hooks/register.ts`:

| Constant | Default | Meaning |
|---|---|---|
| `COMPACT_AT_TOKENS` | 120,000 | Only a conversation at least this large is compacted. A small one costs little to re-store. |
| `IDLE_BEFORE_COMPACT_MS` | 240,000 | The quiet period before compacting. Keep it under five minutes, so the compaction still reads a warm cache. |
| `MAX_TRIES` | 5 | Claude Code refuses a compaction while a turn runs; the mod tries again once a second, this many times. |

Each compaction is recorded in the mod's store, one key per firing, with the
time, session, folder, context size and number of jobs running, so you can count
and price your own:
`~/.claude/plugins/store/wait-compact_<source>.json`.

## Limits

- **Built for the five-minute cache.** If your sessions write the one-hour
  cache, a wait has to pass an hour before it costs anything, and this mod
  would mostly throw away a cache that was still good.
- **A compaction loses detail.** The summary instructions keep jobs, plans and
  open questions, but anything else the conversation held is gone.
- **It cannot see the future.** A reply that lands between four and five
  minutes finds a compacted conversation that did not need compacting. That
  was 10 of 273 here.
- **It also fires while you read.** A long reply you take six minutes over
  counts as a wait.

## Licence

MIT. See `LICENSE` at the repository root.
