#!/usr/bin/env python3
"""Claude Code PreToolUse hook that puts a budget on subagent spawns.

Claude Code will start several subagents when it judges work parallelisable.
Each one runs its own conversation and re-reads its own context on every turn,
so a cluster of six is six conversations paid for, not one.

Run as a hook (reads a hook payload on stdin, writes a decision on stdout):
    agent_spawn_budget.py --hook
Register it three times: under PreToolUse on the spawn tool, where it decides;
under SubagentStart, where it records a started agent by its agent_id; and under
SubagentStop, where it removes that same agent_id. The in-flight rule is on only
while both SubagentStart and SubagentStop register it in a settings file this
script can read, because a count with no removal could only grow.

Run as a tool:
    agent_spawn_budget.py --report            measure your own spawn history
    agent_spawn_budget.py --status            config, counters and any grant
    agent_spawn_budget.py --allow "reason" --spawns 6 --minutes 15
    agent_spawn_budget.py --revoke

Config, first file that parses into an object wins:
    <project>/.claude/agent-spawn-budget.json
      (<project> is $CLAUDE_PROJECT_DIR, or the working directory when unset)
    ~/.claude/agent-spawn-budget.json
Keys, types and defaults are in DEFAULTS below. A key of the wrong type is
ignored and its default is used.

State lives in ~/.claude/agent-spawn-budget/, one file per session plus the
grant, and two lock files that are created once and never removed. Every
read-modify-write holds an exclusive lock, because several sessions and several
hooks can run in the same moment and an unlocked counter would let a whole
fan-out through while recording one spawn.

The hook exits 0 on every path, a denial included: a deny is expressed in the
JSON decision, never by failing the hook. A malformed payload, an unreadable
state file and an unwritable state directory all allow the spawn and say so on
stderr, so enforcement can stop but never silently.

Three invariants hold across the whole file. Check a change against these, not
against the example that prompted it.

1. Any cap compared against the recent-stamp list must be reachable given how
   that list is trimmed. The trim is a function of the cap, never a constant
   that can sit below it.
2. Every path that reads then writes state or the grant holds that file's lock,
   and the deciding read and the recording write happen under one acquisition.
   A lock is its path, so no lock file is ever removed and no name a caller
   supplies can resolve to one.
3. Every accepted combination of flags either does what was asked or errors. No
   flag is discarded in silence.
"""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shlex
import sys
import time
from pathlib import Path

# Each default also fixes the type a config file must supply for that key.
DEFAULTS = {
    # Deny a spawn once this many have started inside burst_window_seconds.
    # 0 denies every spawn; to switch the rule off, set it far above any real
    # fan-out rather than to 0.
    "burst_max": 2,
    "burst_window_seconds": 120,
    # Deny once a session has spawned this many agents in total. 0 disables.
    "session_max": 0,
    # Deny a spawn that does not name a model. Where neither the agent
    # definition nor a configured default supplies one, an unset model inherits
    # the parent session's, which is the priciest model in play.
    "require_explicit_model": True,
    # Spawns of these subagent types are never counted and never denied.
    "exempt_subagent_types": [],
    # Set false to print a would-be denial on stderr and block nothing.
    "enforce": True,
    # Deny a spawn while this many agents of the session are still running.
    # Spacing spawns out passes the burst rule; this one it does not. 0 disables.
    "inflight_max": 1,
    # Any running agent stops counting after this long, whether it is still
    # working or its stop was lost. 0 counts nothing, so the rule is off.
    "inflight_ttl_minutes": 30,
    # Session files untouched for this long are removed on the next hook run.
    "state_retention_days": 30,
}

STATE_DIR = Path.home() / ".claude" / "agent-spawn-budget"
ALLOW_FILE = STATE_DIR / "allow.json"
# One lock covers every session's state and the pruning of it, and is never
# deleted: a lock is its path, so unlinking one lets the next process create a
# second file there and hold it while the first holder still has the original.
SESSION_LOCK = STATE_DIR / "sessions"
# Every session state file starts with this, so no session id can name the
# grant file or a lock, and pruning can tell state from everything else.
SESSION_PREFIX = "s-"
SPAWN_TOOLS = ("Agent", "Task")
START_EVENT = "SubagentStart"
STOP_EVENT = "SubagentStop"
# The agent type Claude Code runs when a spawn names none, and the type
# SubagentStart then reports, so exemption compares one name at both events.
DEFAULT_AGENT_TYPE = "general-purpose"
# A running agent whose stop was lost stopped counting at its TTL; its entry is
# dropped from disk after this long. An agent still running keeps its entry.
INFLIGHT_KEEP_SECONDS = 24 * 3600
# Lower bound on how many recent timestamps a session keeps. The burst rule
# counts this list, so the real bound is whatever burst_max needs; see
# stamps_to_keep.
MIN_STAMPS_KEPT = 200
# A grant is a deliberate exception, so it is bounded in both size and life.
DEFAULT_GRANT_SPAWNS = 6
DEFAULT_GRANT_MINUTES = 15
MAX_GRANT_SPAWNS = 100
MAX_GRANT_MINUTES = 7 * 24 * 60


def warn(message):
    sys.stderr.write("agent-spawn-budget: %s\n" % message)


def project_candidates(*names):
    """<project>/.claude/<name> for each name, or [] when there is no project.

    The project is $CLAUDE_PROJECT_DIR, set for hooks, or the working directory
    from a terminal. A working directory that was deleted means no project.
    """
    try:
        project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    except OSError:
        return []
    return [project / ".claude" / name for name in names]


def load_config():
    """Merge the first readable config file over DEFAULTS, by key and by type."""
    cfg = dict(DEFAULTS)
    candidates = (project_candidates("agent-spawn-budget.json")
                  + [Path.home() / ".claude" / "agent-spawn-budget.json"])
    for path in candidates:
        try:
            loaded = json.loads(path.read_text())
        except OSError:
            continue
        except ValueError:
            warn("%s is not valid JSON; skipping it" % path)
            continue
        if not isinstance(loaded, dict):
            warn("%s is not a JSON object; skipping it" % path)
            continue
        for key, value in loaded.items():
            if key not in DEFAULTS:
                warn("%s: unknown key %r, ignored" % (path, key))
                continue
            wanted = type(DEFAULTS[key])
            # bool subclasses int, so an int key must reject a bool and vice versa.
            is_bool = isinstance(value, bool)
            if wanted is bool and is_bool:
                cfg[key] = value
            elif wanted is int and isinstance(value, int) and not is_bool and value >= 0:
                cfg[key] = value
            elif wanted is list and isinstance(value, list):
                cfg[key] = [item for item in value if isinstance(item, str)]
            else:
                warn("%s: %r has the wrong type or range, using default %r"
                     % (path, key, DEFAULTS[key]))
        break
    return cfg


@contextlib.contextmanager
def locked(path):
    """Hold an exclusive lock named by path, over one whole read-modify-write.

    Locks the sentinel `<path>.lock`, not path itself, so the data file can be
    replaced by rename without moving the lock. Callers must never remove a
    lock file: two processes at one path must mean one lock.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(str(path) + ".lock", "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def in_window(stamp, now, window_seconds):
    """True for a stamp inside the window that ends now.

    The lower bound matters: a clock step or a suspended VM can leave a stamp
    dated ahead of now, which would otherwise sit inside every future window
    and deny the session forever.
    """
    age = now - stamp
    return 0 <= age < window_seconds


def write_json(path, obj):
    """Replace path atomically. The temp name carries the pid, so two writers
    never share a temp file and truncate each other's."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("%s.%d.tmp" % (path.name, os.getpid()))
    tmp.write_text(json.dumps(obj))
    tmp.replace(path)


def session_file(session_id):
    """One state file per session.

    An id that is not a plain token is hashed rather than stripped, so a path
    separator cannot escape the directory. The prefix keeps every session out
    of the namespace the grant and the locks use. Ids that are equal as strings
    share a file, which is what a session id means.

    Limitation: a plain token spelled like a hashed name maps to that name's
    file, so the two sessions share one budget. Claude Code session ids are
    UUIDs and always take the plain branch, so no payload the hook receives can
    reach the hashed one.
    """
    raw = "" if session_id is None else str(session_id)
    if raw and len(raw) <= 120 and all(c.isalnum() or c in "-_" for c in raw):
        return STATE_DIR / (SESSION_PREFIX + raw + ".json")
    return STATE_DIR / (SESSION_PREFIX + "id-"
                        + hashlib.sha256(raw.encode()).hexdigest()[:32] + ".json")


def numbers(value):
    """The numeric entries of a list read from disk; anything else reads as []."""
    if not isinstance(value, list):
        return []
    return [t for t in value
            if isinstance(t, (int, float)) and not isinstance(t, bool)]


def agent_starts(value):
    """The {agent_id: start time} entries of a map read from disk; else {}."""
    if not isinstance(value, dict):
        return {}
    return {k: t for k, t in value.items() if isinstance(k, str)
            and isinstance(t, (int, float)) and not isinstance(t, bool)}


def read_state(path):
    """Return (spawns ever in this session, recent timestamps, running agents).

    Running agents map agent_id to start time for agents started and not yet
    stopped. Anything but the expected shape reads as empty and says so, because
    a budget that silently forgets its counter is worse than one that complains.
    """
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return 0, [], {}
    except (OSError, ValueError):
        warn("state file %s is unreadable; this session's count restarts" % path)
        return 0, [], {}
    if not isinstance(raw, dict):
        warn("state file %s has an unexpected shape; count restarts" % path)
        return 0, [], {}
    count = raw.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        count = 0
    return count, numbers(raw.get("stamps")), agent_starts(raw.get("inflight"))


def stamps_to_keep(burst_max):
    """How many recent timestamps a session keeps.

    Never below burst_max, because the burst rule denies on the LENGTH of this
    list: a trim under that number makes the rule unreachable and silent.
    """
    return max(MIN_STAMPS_KEPT, burst_max + 1)


def running_agents(inflight, now, cfg):
    """Start times of the session's agents that count against inflight_max, oldest first."""
    return sorted(t for t in inflight.values()
                  if in_window(t, now, cfg["inflight_ttl_minutes"] * 60))


def kept_agents(inflight, now):
    """The entries still inside INFLIGHT_KEEP_SECONDS, TTL not applied."""
    return {k: t for k, t in inflight.items()
            if in_window(t, now, INFLIGHT_KEEP_SECONDS)}


def write_state(path, count, stamps, inflight):
    write_json(path, {"count": count, "stamps": stamps, "inflight": inflight})


def record_spawn(path, count, stamps, inflight, now, cfg):
    """Add one spawn to the session's durable count and its recent window.

    The count is its own field rather than the length of the timestamp list,
    which is trimmed, so session_max stays true however long a session runs.
    The caller holds the lock and has already read the state.
    """
    kept = [t for t in stamps if in_window(t, now, cfg["burst_window_seconds"])]
    kept.append(now)
    write_state(path, count + 1, kept[-stamps_to_keep(cfg["burst_max"]):],
                kept_agents(inflight, now))


def start_agent(path, agent_id, now):
    """Record a started agent under its agent_id. The caller holds the lock."""
    count, stamps, inflight = read_state(path)
    inflight = kept_agents(inflight, now)
    inflight[agent_id] = now
    write_state(path, count, stamps, inflight)


def stop_agent(path, agent_id, now):
    """Remove a stopped agent by its agent_id. The caller holds the lock.

    A stop for an agent never recorded, such as an exempt one, changes nothing.
    """
    if not path.exists():
        return
    count, stamps, inflight = read_state(path)
    kept = kept_agents(inflight, now)
    kept.pop(agent_id, None)
    if kept != inflight:
        write_state(path, count, stamps, kept)


def agent_type_of(tool_input):
    """The agent type a spawn will run, as SubagentStart will report it."""
    return tool_input.get("subagent_type") or DEFAULT_AGENT_TYPE


def registered_events():
    """The hook events whose settings entries run this script.

    Reads the user settings, then the project's settings.json and
    settings.local.json (see project_candidates). A registration in any other settings
    source is not seen. A command matches when one of its words is a path to a
    file with this script's name; a command that will not parse is skipped alone.
    """
    me = Path(__file__).name
    found = set()
    for path in ([Path.home() / ".claude" / "settings.json"]
                 + project_candidates("settings.json", "settings.local.json")):
        try:
            hooks = json.loads(path.read_text()).get("hooks", {})
            events = [(name, hooks.get(name, [])) for name in (START_EVENT, STOP_EVENT)]
        except (OSError, ValueError, AttributeError):
            continue
        for name, entries in events:
            for entry in entries if isinstance(entries, list) else []:
                commands = entry.get("hooks", []) if isinstance(entry, dict) else []
                for hook in commands if isinstance(commands, list) else []:
                    try:
                        words = shlex.split(str(hook.get("command", "")))
                    except (ValueError, AttributeError):
                        continue
                    if any(Path(word).name == me for word in words):
                        found.add(name)
    return found


def inflight_rule_on(cfg):
    """True when the in-flight rule can both record agents and remove them."""
    return (cfg["inflight_max"] > 0 and cfg["inflight_ttl_minutes"] > 0
            and registered_events() == {START_EVENT, STOP_EVENT})


def prune_state(retention_days):
    """Remove state left by sessions that stopped, under the session lock.

    A live session rewrites its .json on every spawn, so a .json newer than the
    cutoff belongs to a live session and is left alone. Lock files are never
    removed: a lock is identified by its path, and unlinking one lets the next
    process create a second file at that path and hold the same lock at the
    same time as whoever still has the first.
    """
    if retention_days <= 0:
        return
    cutoff = time.time() - retention_days * 86400
    try:
        with locked(SESSION_LOCK):
            for entry in list(STATE_DIR.iterdir()):
                prunable = (entry.suffix == ".tmp"
                            or (entry.suffix == ".json"
                                and entry.name.startswith(SESSION_PREFIX)))
                if not prunable:
                    continue
                try:
                    if entry.stat().st_mtime < cutoff:
                        entry.unlink()
                except OSError:
                    continue
    except OSError:
        return


def read_grant(now):
    """The live grant, or None. An expired, spent or malformed one is removed."""
    try:
        grant = json.loads(ALLOW_FILE.read_text())
    except (OSError, ValueError):
        return None
    spawns = grant.get("spawns") if isinstance(grant, dict) else None
    expires = grant.get("expires") if isinstance(grant, dict) else None
    if not isinstance(spawns, int) or isinstance(spawns, bool) or spawns <= 0 \
            or not isinstance(expires, (int, float)) or isinstance(expires, bool) \
            or expires < now:
        with contextlib.suppress(OSError):
            ALLOW_FILE.unlink()
        return None
    return grant


def claim_grant(session_id, now):
    """Spend one spawn from the grant if it is live and open to this session.

    A grant naming no session binds to the first session that spends it, so one
    fan-out cannot be split across several sessions running at the same time.
    """
    with locked(ALLOW_FILE):
        grant = read_grant(now)
        if grant is None:
            return False
        owner = grant.get("session")
        if owner is not None and owner != session_id:
            return False
        grant["session"] = session_id
        grant["spawns"] -= 1
        if grant["spawns"] <= 0:
            with contextlib.suppress(OSError):
                ALLOW_FILE.unlink()
        else:
            write_json(ALLOW_FILE, grant)
        return True


def deny(reason):
    json.dump({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, sys.stdout)
    sys.exit(0)


def find_problem(cfg, tool_input, count, window, running, now):
    """The reason to deny this spawn, or None. `running` is [] when the rule is off."""
    if cfg["require_explicit_model"] and not tool_input.get("model"):
        return (
            "This spawn does not set `model`. Unless the agent definition or a "
            "configured default supplies one, it inherits this session's model, "
            "which is the priciest model in play, and it pays that rate for "
            "every turn of its own conversation.\n"
            "Name one: haiku for mechanical sweeps and file legwork, sonnet for "
            "reading and routine edits, opus for judgment. A fork always "
            "inherits and ignores `model`, so exempt forks by subagent type "
            "rather than trying to fix them with a model name."
        )
    if cfg["inflight_max"] and len(running) >= cfg["inflight_max"]:
        return (
            "%d agent(s) from this session are still running, and the budget "
            "is %d at a time. The oldest started %d seconds ago.\n"
            "Starting agents a minute apart is still a fan-out: they all run "
            "at once and each one is paid for.\n"
            "Wait for the running agent's result, then decide the next spawn, "
            "or fold the next task into the running agent's brief next time. "
            "A running agent stops counting after %d minutes."
            % (len(running), cfg["inflight_max"], now - running[0],
               cfg["inflight_ttl_minutes"])
        )
    if len(window) >= cfg["burst_max"]:
        return (
            "%d agents already started in the last %d seconds, and the budget "
            "is %d.\n"
            "Each agent runs its own conversation and re-reads its own context "
            "on every turn, so six at once is six conversations paid for, not "
            "one. Parallel agents buy wall-clock time, not tokens.\n"
            "Do the work in this session, or start them one at a time and let "
            "each finish."
            % (len(window), cfg["burst_window_seconds"], cfg["burst_max"])
        )
    if cfg["session_max"] and count >= cfg["session_max"]:
        return (
            "This session has started %d agents and the cap is %d.\n"
            "Continue the work here instead of opening another conversation."
            % (count, cfg["session_max"])
        )
    return None


def run_hook(cfg):
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        if raw.strip():
            warn("stdin was not valid JSON; allowing the spawn")
        sys.exit(0)
    if not isinstance(payload, dict):
        warn("stdin was not a JSON object; allowing the spawn")
        sys.exit(0)
    event = payload.get("hook_event_name")
    if event in (START_EVENT, STOP_EVENT):
        agent_id = payload.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            warn("%s carried no agent_id; nothing recorded" % event)
            sys.exit(0)
        path = session_file(payload.get("session_id"))
        try:
            with locked(SESSION_LOCK):
                if event == STOP_EVENT:
                    stop_agent(path, agent_id, time.time())
                elif (payload.get("agent_type") not in cfg["exempt_subagent_types"]
                      and inflight_rule_on(cfg)):
                    start_agent(path, agent_id, time.time())
        except Exception as error:
            warn("FAILED (%s: %s) on %s. The in-flight count for this session "
                 "may be wrong until inflight_ttl_minutes runs out."
                 % (type(error).__name__, error, event))
        sys.exit(0)
    if payload.get("tool_name") not in SPAWN_TOOLS:
        sys.exit(0)

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        warn("tool_input was not an object; allowing the spawn")
        sys.exit(0)
    if agent_type_of(tool_input) in cfg["exempt_subagent_types"]:
        sys.exit(0)

    session_id = payload.get("session_id")
    now = time.time()
    path = session_file(session_id)
    count_running = inflight_rule_on(cfg)

    # Decide and record under one lock. Without it, several hooks firing in the
    # same instant all read the same pre-burst state and all allow.
    with locked(SESSION_LOCK):
        count, stamps, inflight = read_state(path)
        window = [t for t in stamps
                  if in_window(t, now, cfg["burst_window_seconds"])]
        running = running_agents(inflight, now, cfg) if count_running else []
        problem = find_problem(cfg, tool_input, count, window, running, now)
        # A denied spawn never runs, so it must not consume budget. Under
        # enforce:false it does run, so it must.
        if problem is None or not cfg["enforce"]:
            record_spawn(path, count, stamps, inflight, now, cfg)

    if problem is None:
        sys.exit(0)

    if not cfg["enforce"]:
        warn("report only: " + problem)
        sys.exit(0)

    if claim_grant(session_id, now):
        with locked(SESSION_LOCK):
            count, stamps, inflight = read_state(path)
            record_spawn(path, count, stamps, inflight, now, cfg)
        sys.exit(0)

    deny(problem + "\n\nIf this fan-out is genuinely worth it, put the reason "
         "on record and try again:\n"
         "  agent_spawn_budget.py --allow \"<why>\" --spawns <n> --minutes 15")


def read_records(path):
    """Yield each parsed JSON line of a transcript, skipping what will not parse."""
    try:
        handle = open(path, errors="replace")
    except OSError:
        warn("could not read %s" % path)
        return
    with handle:
        for line in handle:
            try:
                yield json.loads(line)
            except ValueError:
                continue


TOKEN_FIELDS = ("input_tokens", "output_tokens",
                "cache_creation_input_tokens", "cache_read_input_tokens")


def collect_spawns(root):
    """Spawn timestamps per main-session transcript."""
    import glob
    from datetime import datetime
    spawns = {}
    for path in glob.glob(str(root / "*" / "*.jsonl")):
        for record in read_records(path):
            if record.get("type") != "assistant" or not record.get("timestamp"):
                continue
            content = (record.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            moment = datetime.fromisoformat(
                record["timestamp"].replace("Z", "+00:00")).timestamp()
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use" \
                        and block.get("name") in SPAWN_TOOLS:
                    spawns.setdefault(path, []).append(moment)
    return spawns


def collect_costs(root):
    """Per subagent transcript: the first turn's context, and the whole life."""
    import glob
    from collections import Counter
    lifetimes, cold_starts, by_field = [], [], Counter()
    for path in glob.glob(str(root / "*" / "*" / "subagents" / "*.jsonl")):
        used, first = 0, None
        for record in read_records(path):
            if record.get("type") != "assistant":
                continue
            usage = (record.get("message") or {}).get("usage") or {}
            for name in TOKEN_FIELDS:
                by_field[name] += usage.get(name, 0)
            if first is None:
                # What the agent read before it had done anything. Output is
                # excluded here because the question is what it had to load.
                first = (usage.get("input_tokens", 0)
                         + usage.get("cache_creation_input_tokens", 0)
                         + usage.get("cache_read_input_tokens", 0))
            used += sum(usage.get(name, 0) for name in TOKEN_FIELDS)
        if used:
            lifetimes.append(used)
            cold_starts.append(first)
    return lifetimes, cold_starts, by_field


def transcript_report(cfg):
    """Measure how spawns arrive and what they cost, from the local transcripts."""
    import statistics
    from collections import Counter

    root = Path.home() / ".claude" / "projects"
    window_seconds = cfg["burst_window_seconds"]
    burst_max = cfg["burst_max"]

    spawns = collect_spawns(root)
    if not spawns:
        print("No Agent spawns found under %s" % root)
        return

    would_deny = 0
    total = 0
    clusters = Counter()
    widest = {}
    for stamps in spawns.values():
        stamps.sort()
        total += len(stamps)
        # Replay the hook's own sliding window, so this line measures the rule
        # the tool actually enforces.
        window = []
        for moment in stamps:
            window = [t for t in window if moment - t < window_seconds]
            if len(window) >= burst_max:
                would_deny += 1
            else:
                window.append(moment)
        # A cluster chains: each spawn within window_seconds of the PREVIOUS
        # one, so a cluster can span longer than the window.
        i = 0
        while i < len(stamps):
            j = i
            while j + 1 < len(stamps) and stamps[j + 1] - stamps[j] <= window_seconds:
                j += 1
            size = j - i + 1
            clusters[size] += 1
            widest[size] = max(widest.get(size, 0.0), stamps[j] - stamps[i])
            i = j + 1

    print("Spawns issued from main sessions: %d" % total)
    print("A spawn made BY a subagent lives in that subagent's transcript and "
          "is not counted here.")
    print("\nAt the current budget of %d per %ds, the hook would have denied "
          "%d of them (%.1f%%)."
          % (burst_max, window_seconds, would_deny, 100.0 * would_deny / total))
    print("\nClusters. Each spawn in a cluster is within %ds of the PREVIOUS "
          "one, so a\ncluster can span longer than the window, and the widest "
          "span says by how much." % window_seconds)
    print("   %-8s %9s %8s %8s %12s"
          % ("size", "clusters", "spawns", "share", "widest span"))
    for size in sorted(clusters):
        print("   %-8d %9d %8d %7.1f%% %11.0fs"
              % (size, clusters[size], size * clusters[size],
                 100.0 * size * clusters[size] / total, widest[size]))

    lifetimes, cold_starts, by_field = collect_costs(root)
    if not lifetimes:
        return
    grand = sum(by_field.values())
    median_life = statistics.median(lifetimes)

    print("\nWhat one agent costs, from %d subagent transcripts." % len(lifetimes))
    print("A different population from the spawns above: it includes agents "
          "started by\nother agents, which the spawn scan never sees.")
    print("   median first turn  %15s tokens  (the cold start, output excluded)"
          % f"{int(statistics.median(cold_starts)):,}")
    print("   median whole life  %15s tokens  (every field, every turn)"
          % f"{int(median_life):,}")
    print("   total              %15s tokens" % f"{sum(lifetimes):,}")
    print("\n   six median agents: %s tokens. That is arithmetic, not a "
          "measured cluster." % f"{int(6 * median_life):,}")
    print("\nWhat those tokens are. A cache read bills far below fresh input, "
          "so read this\nsplit before turning any total above into money. "
          "Against a subscription's usage\nlimit the raw token count is the "
          "figure that matters; against an invoice it is not.")
    for name in ("input_tokens", "cache_creation_input_tokens",
                 "cache_read_input_tokens", "output_tokens"):
        print("   %-30s %16s  %5.1f%%"
              % (name, f"{by_field[name]:,}", 100.0 * by_field[name] / grand))


def show_status(cfg):
    for key in sorted(DEFAULTS):
        print("%-24s %s" % (key, cfg[key]))
    # Under the lock: read_grant unlinks a spent or expired grant, which would
    # otherwise race a claim_grant running in another process.
    with locked(ALLOW_FILE):
        grant = read_grant(time.time())
    if grant:
        print("\nLive grant: %d spawns left, %d seconds remaining, session %s"
              % (grant["spawns"], grant["expires"] - time.time(),
                 grant.get("session") or "(unbound)"))
        print("  reason: %s" % grant.get("reason", ""))
    else:
        print("\nNo live grant.")
    sessions = []
    try:
        for entry in STATE_DIR.iterdir():
            if (entry.suffix != ".json"
                    or not entry.name.startswith(SESSION_PREFIX)):
                continue
            try:
                # Pruning can remove an entry between the listing and this
                # stat, so the timestamp is read once and carried.
                sessions.append((entry.stat().st_mtime, entry))
            except OSError:
                continue
    except OSError:
        pass
    if not cfg["inflight_max"]:
        print("\nIn-flight rule: off (inflight_max is 0).")
    elif not cfg["inflight_ttl_minutes"]:
        print("\nIn-flight rule: off (inflight_ttl_minutes is 0).")
    elif inflight_rule_on(cfg):
        print("\nIn-flight rule: on, %d agent(s) at a time per session."
              % cfg["inflight_max"])
    else:
        missing = sorted({START_EVENT, STOP_EVENT} - registered_events())
        print("\nIn-flight rule: OFF. Register %s under %s to turn it on."
              % (Path(__file__).name, " and ".join(missing)))
    now = time.time()
    print("\nSessions with state on disk: %d" % len(sessions))
    for _, path in sorted(sessions, reverse=True)[:5]:
        count, _, inflight = read_state(path)
        print("   %-40s %5d spawns %3d running"
              % (path.stem[len(SESSION_PREFIX):], count,
                 len(running_agents(inflight, now, cfg))))


def main():
    parser = argparse.ArgumentParser(
        add_help=True, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hook", action="store_true",
                        help="run as a PreToolUse hook (reads stdin)")
    parser.add_argument("--report", action="store_true",
                        help="measure spawn clusters and cost from local transcripts")
    parser.add_argument("--status", action="store_true",
                        help="show config, counters and any live grant")
    parser.add_argument("--allow", metavar="REASON",
                        help="put a reason on record and permit a fan-out")
    # default=None so a value the user typed is distinguishable from one they
    # did not; the real defaults are applied after the guard below.
    parser.add_argument("--spawns", type=int, default=None,
                        help="how many spawns the grant covers (default 6)")
    parser.add_argument("--minutes", type=int, default=None,
                        help="how long the grant lasts (default 15)")
    parser.add_argument("--session", metavar="ID",
                        help="bind the grant to one session id "
                             "(default: the first session that uses it)")
    parser.add_argument("--revoke", action="store_true", help="cancel a live grant")
    args = parser.parse_args()
    actions = [name for name, chosen in
               (("--hook", args.hook), ("--report", args.report),
                ("--status", args.status), ("--allow", args.allow is not None),
                ("--revoke", args.revoke)) if chosen]
    if len(actions) > 1:
        parser.error("%s do different things; pick one" % " and ".join(actions))
    if args.allow is None:
        stray = [flag for flag, value in
                 (("--session", args.session), ("--spawns", args.spawns),
                  ("--minutes", args.minutes)) if value is not None]
        if stray:
            parser.error("%s only mean something with --allow"
                         % " and ".join(stray))

    cfg = load_config()
    if cfg["burst_max"] == 0:
        warn("burst_max is 0, which denies every spawn")
    if cfg["inflight_max"] and cfg["inflight_ttl_minutes"] == 0:
        warn("inflight_ttl_minutes is 0, which counts no running agent")

    if args.hook:
        try:
            prune_state(cfg["state_retention_days"])
            run_hook(cfg)
        except SystemExit:
            raise
        except Exception as error:
            # A read-only home, a full disk or a mount whose flock is refused
            # all land here. Allow the spawn, but never let the budget go
            # quiet: this line is the only signal that it stopped counting.
            warn("FAILED (%s: %s). The spawn was ALLOWED and NOT counted, so "
                 "the budget is not being enforced right now."
                 % (type(error).__name__, error))
            sys.exit(0)
    elif args.status:
        show_status(cfg)
    elif args.report:
        transcript_report(cfg)
    elif args.allow is not None:
        if not args.allow.strip():
            parser.error("--allow needs a reason, which is the whole point of it")
        if args.session is not None and not args.session.strip():
            parser.error("--session needs a session id; omit it to leave the "
                         "grant open to the first session that uses it")
        spawns = DEFAULT_GRANT_SPAWNS if args.spawns is None else args.spawns
        minutes = DEFAULT_GRANT_MINUTES if args.minutes is None else args.minutes
        if not 1 <= spawns <= MAX_GRANT_SPAWNS:
            parser.error("--spawns must be between 1 and %d" % MAX_GRANT_SPAWNS)
        if not 1 <= minutes <= MAX_GRANT_MINUTES:
            parser.error("--minutes must be between 1 and %d, which is a week"
                         % MAX_GRANT_MINUTES)
        with locked(ALLOW_FILE):
            write_json(ALLOW_FILE, {
                "reason": args.allow,
                "spawns": spawns,
                "expires": time.time() + minutes * 60,
                "session": args.session,
                "granted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
        print("Granted %d spawns for %d minutes%s.\nReason on record: %s"
              % (spawns, minutes,
                 " in session %s" % args.session if args.session else "",
                 args.allow))
    elif args.revoke:
        with locked(ALLOW_FILE):
            try:
                ALLOW_FILE.unlink()
                print("Grant revoked.")
            except OSError:
                print("No grant to revoke.")
    else:
        show_status(cfg)


if __name__ == "__main__":
    main()
