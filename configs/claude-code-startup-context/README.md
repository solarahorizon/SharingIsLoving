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
linear across an 18x size range, with zero run-to-run variation. Tool definitions are part
JSON schema, which packs more tokens into each byte than prose, so measure your own block
rather than borrowing a ratio.

**Two caveats that cost real time:**

1. **A one-shot `-p` run cannot measure `Artifact`.** With nothing denying it, adding
   `--disallowedTools Artifact` changes the floor by exactly zero, because `-p` never offers
   the tool in the first place. Per-tool figures for it have to come from byte counts or an
   interactive session.
2. **Compare only within one probe.** Baselines shift with the working directory, the
   project's `CLAUDE.md`, and the skill and agent catalogues. A figure from one setup is not
   comparable to a figure from another.

## What was turned off, and what replaced it

| Denied | Why it was safe **on that machine** |
|---|---|
| `Artifact` | Publishes pages to claude.ai. A local skill renders the same page to a file in the repo instead. See [`skills/local-artifact/`](../../skills/local-artifact/). |
| `SendFeedback` | Drafts bug reports to the vendor. Nothing depended on it. |
| `Workflow` | A two-leg review gate already ran on every commit. **0 calls in 125,338 tool calls across 1,287 session transcripts.** |
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
in that machine's own `CLAUDE.md` used the word "monitor" for a different job, and once a
tool with that name shipped, agents read the word as the tool. The rule's wording
manufactured the demand. A Bash call
with `run_in_background` does the same job for nothing. **Check whether your own
instructions are generating the usage before you read a count as a requirement.**

## Applying it

Merge the two blocks in `settings.deny-unused-tools.json` into `~/.claude/settings.json`.
It takes effect in the **next** session, not the running one. To undo, delete the lines.

To confirm a tool is gone, start a new session and check that its name is absent from the
tool list in that session's `.jsonl` under `~/.claude/projects/`.

`CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS=1` is included because that machine's own `CLAUDE.md`
already carried its git rules. It removed **2,011 tokens** from a `-p` run. **When you test it,
unset it in the shell first:** a child `claude -p` inherits environment variables from the
shell that launched it, so if your shell already exports the variable, the "without" run is
not without it and the two runs read the same.
