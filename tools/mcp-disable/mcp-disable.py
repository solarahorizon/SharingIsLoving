#!/usr/bin/env python3
"""Disable (or re-enable) MCP servers across ALL Claude Code projects at once.

Default run (no arguments): discovers every MCP server known to ~/.claude.json
(local mcpServers + any name appearing in any project's enable/disable lists)
and disables ALL of them in EVERY project.

Claude Code persists per-project MCP disable state in ~/.claude.json under
projects/<dir>/disabledMcpServers. The /mcp slash command only edits the
current project's entry; this script applies the toggle to every project.

Usage:
  mcp-disable.py                       # discover all servers, disable everywhere
  mcp-disable.py --list                # show discovered servers + per-project state
  mcp-disable.py --dry-run             # preview the disable-all without writing
  mcp-disable.py "claude.ai Gmail"     # ALSO disable these names (added to discovery)
  mcp-disable.py --enable              # re-enable all discovered servers everywhere
  mcp-disable.py --enable blender      # re-enable just these names everywhere

Notes:
- A timestamped backup of ~/.claude.json is written next to it before any change.
- claude.ai account connectors (e.g. "claude.ai Gmail") are only visible to this
  script once they've been disabled somewhere at least once OR are passed by the
  exact name shown in /mcp. Account-wide disconnection lives at claude.ai ->
  Settings -> Connectors.
- Already-running sessions keep their loaded tools until restarted, and a live
  session may rewrite ~/.claude.json on exit and clobber this edit. Best run
  with no other Claude Code sessions open; new sessions pick the state up at launch.
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

CONFIG = Path.home() / ".claude.json"


def discover_servers(data):
    names = set(data.get("mcpServers", {}))
    for entry in data.get("projects", {}).values():
        if isinstance(entry, dict):
            names |= set(entry.get("mcpServers", {}) or {})
            names |= set(entry.get("disabledMcpServers", []) or [])
            names |= set(entry.get("enabledMcpjsonServers", []) or [])
            names |= set(entry.get("disabledMcpjsonServers", []) or [])
    return sorted(names)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("servers", nargs="*", help="extra server names beyond auto-discovery (exact names as shown in /mcp)")
    parser.add_argument("--enable", action="store_true", help="re-enable instead of disable")
    parser.add_argument("--list", action="store_true", help="show discovered servers + per-project disabled state, then exit")
    parser.add_argument("--dry-run", action="store_true", help="preview changes without writing")
    args = parser.parse_args()

    with open(CONFIG) as f:
        data = json.load(f)
    projects = data.get("projects", {})
    if not projects:
        sys.exit("No projects found in ~/.claude.json")

    discovered = discover_servers(data)

    if args.list:
        print(f"Discovered servers: {', '.join(discovered) or '(none)'}")
        print("\nPer-project disabled state (projects with nothing disabled omitted):")
        for path, entry in sorted(projects.items()):
            disabled = entry.get("disabledMcpServers", []) if isinstance(entry, dict) else []
            if disabled:
                print(f"  {path}: {', '.join(disabled)}")
        print("\nNote: never-disabled claude.ai connectors are invisible here — pass their /mcp names explicitly.")
        return

    targets = sorted(set(discovered) | set(args.servers)) if not (args.enable and args.servers) else sorted(set(args.servers))
    if not targets:
        sys.exit("No servers discovered and none provided — nothing to do.")

    changed = []
    for path, entry in projects.items():
        if not isinstance(entry, dict):
            continue
        disabled = entry.get("disabledMcpServers", []) or []
        before = list(disabled)
        if args.enable:
            disabled = [s for s in disabled if s not in targets]
        else:
            disabled = disabled + [s for s in targets if s not in disabled]
        if disabled != before:
            entry["disabledMcpServers"] = disabled
            changed.append((path, before, disabled))

    verb = "re-enable" if args.enable else "disable"
    print(f"Targets to {verb}: {', '.join(targets)}\n")
    if not changed:
        print(f"Nothing to change — all {len(projects)} projects already in the requested state.")
        return

    for path, before, after in changed:
        print(f"{path}\n  {before} -> {after}")

    if args.dry_run:
        print(f"\nDry run: {len(changed)} project(s) would change. No write performed.")
        return

    backup = CONFIG.with_name(f".claude.json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(CONFIG, backup)
    tmp = CONFIG.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    tmp.replace(CONFIG)
    print(f"\nUpdated {len(changed)} project(s). Backup: {backup}")
    print("Restart any open Claude Code sessions to apply (a live session may overwrite this on exit).")


if __name__ == "__main__":
    main()
