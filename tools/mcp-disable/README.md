# mcp-disable — turn off every MCP server, in every project, in one run

A ~120-line stdlib-only Python script that discovers all MCP servers known to
your Claude Code config (`~/.claude.json`) and disables them across **all** your
projects at once. Reversible (`--enable`), previewable (`--dry-run`), and it
backs up the config before every write.

## The failure behind it

During a mid-week context audit (45% of the weekly token quota already burned),
we measured what every Claude Code session was loading before any work started.
Two MCP connectors — an image-generation service and Blender — were injecting
**89 tool definitions plus instruction blobs (~2-3K tokens) into every single
session, in every project**. The image connector had been used in exactly one
session, ever. Blender had never been used at all.

That's a tax on every session start *and* on every prompt-cache expiry, paid
silently, forever, in every project on the machine.

The catch that motivated the script: Claude Code's `/mcp` command persists the
disable **per project directory** (`projects/<dir>/disabledMcpServers` in
`~/.claude.json`). Disabling a connector in one project leaves it fully loaded
in every other project. With 13 project directories, the manual fix is 13
rounds of `/mcp` — so it doesn't happen, and the tax stays.

## What it does

- **Discovers** every server name the config knows about: local `mcpServers`
  entries plus any name appearing in any project's enable/disable lists.
- **Disables them everywhere** (default), or **re-enables** with `--enable`.
- **Backs up** `~/.claude.json` (timestamped) and writes atomically.

```
./mcp-disable.py              # discover all, disable in every project
./mcp-disable.py --dry-run    # preview without writing
./mcp-disable.py --list       # show discovered servers + per-project state
./mcp-disable.py --enable     # reverse it everywhere
./mcp-disable.py --enable blender          # re-enable one server
./mcp-disable.py "claude.ai Gmail"         # also disable a name discovery can't see
```

## Caveats (honest ones)

- **Account-level connectors that have never been disabled anywhere are
  invisible** to the local config, so discovery can't find them. Disable one
  once via `/mcp` in any project (or pass its exact `/mcp` name as an
  argument) and it becomes discoverable forever after.
- **Run it with no Claude Code sessions open.** Live sessions keep their
  already-loaded tools until restarted, and a live session may rewrite
  `~/.claude.json` on exit, clobbering the edit.
- This is the local per-project layer. Account-wide disconnection of claude.ai
  connectors lives at claude.ai → Settings → Connectors.

## Requirements

Python 3.8+. Standard library only — no installs (`requirements.txt` is empty
on purpose).

## The principle

Don't load it until you need it. Connectors take seconds to re-enable when a
task actually calls for them; until then they're pure context weight in every
session. The same lazy-load discipline applies to CLAUDE.md files and memory
indexes — the connector tax is just the easiest 2-3K tokens to claw back.
