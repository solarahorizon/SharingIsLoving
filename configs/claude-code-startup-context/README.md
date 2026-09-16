# Trimming Claude Code's startup context

Every tool definition Claude Code loads is re-sent on **every turn**, not once at launch. A
tool you never call still costs its full description each time the model is asked anything.

This folder holds the settings that removed five always-loaded tools from one machine, the
method used to measure them, and the reasons each one was safe to remove **there**.

> **Read this before you copy `settings.deny-unused-tools.json`.**
> Every entry is off because a replacement was already running. Deny a tool you actually
> use and you do not get an error, you get a Claude that quietly cannot do that thing.

## Deferred vs always loaded

Claude Code already has the fix for tool-definition bloat, and it does not apply to
everything.

- **Deferred tools** cost only their **name** in the prompt. The full schema arrives when
  something calls the tool, through `ToolSearch`. Since **2.1.69** most built-in tools work
  this way, which cut the built-in tool text from roughly 15,000 tokens to about 968.
- **Always-loaded tools** carry their entire description on every turn.

`Artifact` is always loaded, and it is the largest single item in the prompt. That is the
whole reason this folder exists: the expensive tools are the ones the deferred mechanism
does not cover.

## How to measure it yourself

The floor is `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`.
Reading `cache_creation_input_tokens` alone returns 0 on a warm-cache run, which makes a
change look free when it is not.

```bash
claude -p "say ok" --model haiku --output-format json --setting-sources project \
  | python3 -c 'import json,sys; u=json.load(sys.stdin)["usage"]; \
      print(u["input_tokens"]+u["cache_read_input_tokens"]+u["cache_creation_input_tokens"])'
```

To convert bytes of prompt text into tokens, append a block of known size and take the
difference:

```bash
claude -p "say ok" --model haiku --output-format json --setting-sources project \
  --append-system-prompt-file ./some-known-block.txt
```

Measured on Anthropic's own tool-description prose, three blocks of 3,468, 20,459 and
61,377 bytes cost 810, 4,863 and 14,579 tokens: **4.28, 4.21 and 4.21 bytes per token**,
linear across an 18x size range, with zero run-to-run variation.

**The ratio depends on what you are weighing, so do not reuse one number for everything.**
A tool definition is roughly one third description prose and two thirds JSON parameter
schema, and the schema tokenizes denser:

| Material | bytes per token |
|---|---|
| description prose | 4.21 |
| JSON parameter schema | 3.74 |
| a full tool definition | 3.86 |

Better still, skip the divisor. Append the **real** definition and read the meter.

**Two caveats that cost real time:**

1. **A one-shot `-p` run cannot measure `Artifact`.** With nothing denying it, adding
   `--disallowedTools Artifact` changes the floor by exactly zero, because `-p` never offers
   the tool in the first place. Per-tool figures for it have to come from byte counts or an
   interactive session.
2. **Compare only within one probe.** Baselines shift with the working directory, the
   project's `CLAUDE.md`, and the skill and agent catalogues. A figure from one setup is not
   comparable to a figure from another.

## Where the real definitions are, and the trap in them

Every `prompt_snapshot` record in `~/.claude/projects/**/*.jsonl` carries the tool
definitions the server was sent. That is ground truth, and it is better than any estimate.

```python
import json, glob, os
for f in glob.glob(os.path.expanduser('~/.claude/projects/**/*.jsonl'), recursive=True):
    for line in open(f, errors='ignore'):
        if '"attachment"' not in line or '"tools"' not in line:
            continue
        try:
            tools = (json.loads(line).get('attachment') or {}).get('tools') or []
        except ValueError:
            continue
        for t in tools:
            spec = t.get('schema') or {}
            if 'input_schema' in spec:
                print(t['name'], len(json.dumps(spec, separators=(',', ':'))))
```

**Measure `.schema` and nothing else.** The record stores each description **twice**, once
loose on the entry and again inside `.schema`, which is the real wire spec
(`name` + `description` + `input_schema`). Serialising the whole entry double-counts the
description and can overstate a large tool by more than 60%.

**Sizes change between releases, in both directions.** One tool measured across 415
snapshots: 41,336 bytes on 2.1.266, 37,409 on 2.1.267, 38,527 on 2.1.268, 46,651 on 2.1.270.
Two different sizes shipped under 2.1.273 on the same day. None of that is in the changelog,
which is why this is worth re-running after an update rather than measuring once.

## What was turned off, and what replaced it

| Denied | Why it was safe **on that machine** |
|---|---|
| `Artifact` | Publishes pages to claude.ai. A local skill renders the same page to a file in the repo instead. See [`skills/local-artifact/`](../../skills/local-artifact/). |
| `SendFeedback` | Drafts bug reports to the vendor. Nothing depended on it. |
| `Workflow` | A two-leg review gate already ran on every commit. **0 calls in 127,325 tool calls across 1,311 session transcripts.** |
| `ReportFindings` | Same gate, which writes its own records. **0 calls** in the same sweep. |
| `ScheduleWakeup` | Long waits run on a cron heartbeat instead. |

**Keep `ReportFindings` if you use `/code-review`.** **Keep `Workflow` if you use the
Workflow tool.** Both are cheap next to `Artifact`.

### Count your own usage first

Do not trust the table above, and do not trust a call count on its own either. Count what
your own machine actually called:

```bash
python3 - <<'PY'
import json, glob, os, collections
root = os.path.expanduser('~/.claude/projects')
c = collections.Counter()
for f in glob.glob(os.path.join(root, '**', '*.jsonl'), recursive=True):
    for line in open(f, errors='ignore'):
        if '"tool_use"' not in line:
            continue
        try:
            msg = json.loads(line).get('message') or {}
        except ValueError:
            continue
        for b in msg.get('content') or []:
            if isinstance(b, dict) and b.get('type') == 'tool_use':
                c[b['name']] += 1
for name, n in c.most_common():
    print(f'{name:24} {n:8,}')
PY
```

**A high count is not proof that you need a tool.** On the machine this came from,
`Monitor` showed 519 calls across 104 sessions, which looks essential. It was not: a rule
in that machine's own `CLAUDE.md` said never to poll in bash and to use `Monitor` instead,
so every agent read the line and complied. The rule manufactured the demand. A Bash call
with `run_in_background` does the same job for nothing. **Check whether your own
instructions are generating the usage before you read a count as a requirement.**

## Applying it

Merge the two blocks in `settings.deny-unused-tools.json` into `~/.claude/settings.json`.
It takes effect in the **next** session, not the running one. To undo, delete the lines.

To confirm a tool is gone, start a new session and check that its name is absent from the
tool list in that session's `.jsonl` under `~/.claude/projects/`.

`CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS=1` is included because that machine's own `CLAUDE.md`
already carried its git rules. **It did not reproduce as a saving under a controlled probe**
(35,092 tokens with and without), so treat it as a de-duplication of instructions rather
than as a measured win.
