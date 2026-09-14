#!/usr/bin/env python3
"""Self-test for agent_spawn_budget.py. Stdlib only:

    python3 test_agent_spawn_budget.py

Each case runs the hook as a subprocess against a throwaway HOME, so the real
~/.claude state is never touched. The concurrency case starts several hooks at
the same instant and checks that a budget of two lets exactly two through.
"""

import json
import subprocess
import sys
import os
import stat
import tempfile
import time
from pathlib import Path

HOOK = Path(__file__).with_name("agent_spawn_budget.py")
FAILURES = []


def run(home, payload=None, *args, wait=True):
    proc = subprocess.Popen(
        [sys.executable, str(HOOK)] + list(args),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, cwd=str(home),
    )
    if not wait:
        return proc
    out, err = proc.communicate(json.dumps(payload) if payload is not None else "")
    proc.stdout_text, proc.stderr_text = out, err
    return proc


def decision(proc):
    """The permissionDecision the hook printed, or None when it allowed."""
    if not proc.stdout_text.strip():
        return None
    return json.loads(proc.stdout_text)["hookSpecificOutput"]["permissionDecision"]


def check(name, got, want):
    if got == want:
        print("  ok    %s" % name)
    else:
        print("  FAIL  %s: got %r, want %r" % (name, got, want))
        FAILURES.append(name)


def payload_for(model="haiku", session="s1", subagent_type=None):
    tool_input = {"prompt": "do a thing"}
    if model:
        tool_input["model"] = model
    if subagent_type:
        tool_input["subagent_type"] = subagent_type
    return {"session_id": session, "tool_name": "Agent", "tool_input": tool_input}


def spawn(home, **kwargs):
    return run(home, payload_for(**kwargs), "--hook")


def set_config(home, mapping):
    (home / ".claude" / "agent-spawn-budget.json").write_text(json.dumps(mapping))


def state_of(home, session):
    path = home / ".claude" / "agent-spawn-budget" / ("s-" + session + ".json")
    return json.loads(path.read_text())


def test_defaults(home):
    print("default config")
    check("a spawn with no model is denied", decision(spawn(home, model=None)), "deny")
    check("first spawn passes", decision(spawn(home)), None)
    check("second spawn passes", decision(spawn(home)), None)
    check("third spawn in the window is denied", decision(spawn(home)), "deny")
    check("a different session has its own budget",
          decision(spawn(home, session="s2")), None)
    check("a non-Agent tool is untouched",
          decision(run(home, {"session_id": "s1", "tool_name": "Bash",
                              "tool_input": {"command": "ls"}}, "--hook")), None)
    check("the Task tool is treated as a spawn",
          decision(run(home, {"session_id": "s9", "tool_name": "Task",
                              "tool_input": {"prompt": "x"}}, "--hook")), "deny")
    check("a denied spawn does not consume budget",
          state_of(home, "s1")["count"], 2)


def test_grant(home):
    print("written grant")
    run(home, None, "--allow", "six read-only backlog reads", "--spawns", "2",
        "--minutes", "15")
    check("a granted spawn passes", decision(spawn(home)), None)
    check("the grant covers a second spawn", decision(spawn(home)), None)
    check("the grant is spent and the budget returns", decision(spawn(home)), "deny")

    # sA must exhaust its own budget first, or it is allowed outright and
    # never touches the grant.
    spawn(home, session="sA")
    spawn(home, session="sA")
    run(home, None, "--allow", "bound to one session", "--spawns", "2",
        "--minutes", "15")
    check("an unbound grant is claimed by the first session to use it",
          decision(spawn(home, session="sA")), None)
    check("another session cannot spend the bound grant",
          decision(spawn(home, session="s1")), "deny")

    run(home, None, "--allow", "explicit session", "--spawns", "1",
        "--minutes", "15", "--session", "sB")
    check("a grant bound to sB is refused to s1", decision(spawn(home)), "deny")
    check("a grant bound to sB is honoured for sB",
          decision(spawn(home, session="sB")), None)

    run(home, None, "--revoke")
    proc = run(home, None, "--allow", "   ", "--spawns", "3")
    check("an empty reason is refused", proc.returncode != 0, True)
    check("an empty reason writes no grant",
          (home / ".claude" / "agent-spawn-budget" / "allow.json").exists(), False)
    proc = run(home, None, "--allow", "fine", "--spawns", "0")
    check("a zero-spawn grant is refused", proc.returncode != 0, True)


def test_config(home):
    print("config file")
    set_config(home, {"enforce": False})
    check("enforce false never denies", decision(spawn(home, session="e1")), None)
    check("enforce false still denies nothing on the third",
          decision(spawn(home, session="e1")) or decision(spawn(home, session="e1")),
          None)
    run(home, None, "--allow", "should not be touched", "--spawns", "3",
        "--minutes", "15")
    proc = spawn(home, session="e1")
    check("enforce false reports on stderr", "report only" in proc.stderr_text, True)
    grant = json.loads((home / ".claude" / "agent-spawn-budget"
                        / "allow.json").read_text())
    check("enforce false does not spend the grant", grant["spawns"], 3)
    run(home, None, "--revoke")

    set_config(home, {"require_explicit_model": False, "burst_max": 99})
    check("require_explicit_model false allows an unset model",
          decision(spawn(home, model=None, session="s3")), None)

    set_config(home, {"burst_max": 0, "exempt_subagent_types": ["dev-reviewer"]})
    check("an exempt type passes a zero budget",
          decision(spawn(home, session="s4", subagent_type="dev-reviewer")), None)
    check("a non-exempt type does not", decision(spawn(home, session="s4")), "deny")

    set_config(home, {"session_max": 1, "burst_window_seconds": 0})
    check("session_max is counted outside the burst window",
          decision(spawn(home, session="s5")), None)
    check("session_max denies the next one", decision(spawn(home, session="s5")), "deny")

    # The timestamp list is trimmed to 200, so session_max must not read it.
    set_config(home, {"session_max": 250, "burst_window_seconds": 0})
    path = home / ".claude" / "agent-spawn-budget" / "s-big.json"
    path.write_text(json.dumps({"count": 249, "stamps": []}))
    check("session_max 250 allows spawn 250", decision(spawn(home, session="big")), None)
    check("session_max 250 denies spawn 251",
          decision(spawn(home, session="big")), "deny")
    path.write_text(json.dumps({"count": 600, "stamps": []}))
    check("the durable count survives above the 200-stamp trim",
          decision(spawn(home, session="big")), "deny")


def test_malformed(home):
    print("malformed input")
    set_config(home, {})
    for label, body in [("a JSON list", "[]"), ("a JSON string", '"hello"'),
                        ("a JSON number", "42"), ("empty stdin", "")]:
        proc = subprocess.run([sys.executable, str(HOOK), "--hook"], input=body,
                              capture_output=True, text=True,
                              env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
                              cwd=str(home))
        check("%s does not crash" % label, proc.returncode, 0)
        check("%s allows the spawn" % label, proc.stdout.strip(), "")

    proc = run(home, {"session_id": "m1", "tool_name": "Agent",
                      "tool_input": "not an object"}, "--hook")
    check("a string tool_input does not crash", proc.returncode, 0)
    check("a string tool_input allows the spawn", decision(proc), None)

    for bad in [{"burst_max": "two"}, {"session_max": "5"},
                {"exempt_subagent_types": None}, {"exempt_subagent_types": 7},
                {"burst_max": True}, {"enforce": 1}]:
        set_config(home, bad)
        proc = spawn(home, session="m2")
        check("config %r does not crash" % bad, proc.returncode, 0)
    set_config(home, {"burst_max": "two"})
    check("a bad burst_max falls back to the default of 2",
          [decision(spawn(home, session="m3")) for _ in range(3)],
          [None, None, "deny"])

    set_config(home, {})
    state = home / ".claude" / "agent-spawn-budget" / "s-m4.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    for junk in ["5", "{ not json", '{"count": "x", "stamps": 3}', '["a"]']:
        state.write_text(junk)
        proc = spawn(home, session="m4")
        check("state file %r does not crash" % junk, proc.returncode, 0)

    allow = home / ".claude" / "agent-spawn-budget" / "allow.json"
    for junk in ['{"spawns": "three", "expires": 99999999999}', "[]", "oops"]:
        allow.write_text(junk)
        proc = spawn(home, session="m5")
        check("grant file %r does not crash" % junk, proc.returncode, 0)

    (home / ".claude" / "agent-spawn-budget.json").write_text("{ not json")
    proc = spawn(home, session="m6")
    check("a broken config does not crash", proc.returncode, 0)
    check("a broken config falls back to defaults",
          decision(spawn(home, model=None, session="m7")), "deny")


def test_concurrency(home):
    print("concurrency")
    set_config(home, {})
    for trial in range(4):
        session = "race%d" % trial
        procs = [run(home, None, "--hook", wait=False) for _ in range(6)]
        body = json.dumps(payload_for(session=session))
        results = []
        for proc in procs:
            out, _ = proc.communicate(body)
            results.append(out.strip())
        allowed = sum(1 for r in results if not r)
        stored = state_of(home, session)
        check("trial %d: a budget of 2 allows exactly 2 of 6" % trial, allowed, 2)
        check("trial %d: the state file records both" % trial, stored["count"], 2)


def test_status(home):
    print("status and help")
    set_config(home, {})
    proc = run(home, None, "--status")
    check("--status prints the config", "burst_max" in proc.stdout_text, True)
    check("--status exits 0", proc.returncode, 0)
    proc = run(home, None)
    check("no argument prints the status page", "burst_max" in proc.stdout_text, True)
    proc = run(home, None, "--help")
    check("--help exits 0", proc.returncode, 0)




def test_filesystem_failure(home):
    print("filesystem failure")
    set_config(home, {})
    state_dir = home / ".claude" / "agent-spawn-budget"
    state_dir.mkdir(parents=True, exist_ok=True)
    original = stat.S_IMODE(state_dir.stat().st_mode)
    os.chmod(state_dir, 0o500)
    try:
        proc = spawn(home, session="ro1")
        check("an unwritable state dir does not crash the hook", proc.returncode, 0)
        check("an unwritable state dir allows the spawn", decision(proc), None)
        check("an unwritable state dir says enforcement stopped",
              "not being enforced" in proc.stderr_text, True)
    finally:
        os.chmod(state_dir, original)
    check("the hook works again once the directory is writable",
          decision(spawn(home, session="ro2")), None)


def test_future_stamp(home):
    print("clock steps")
    set_config(home, {})
    state = home / ".claude" / "agent-spawn-budget" / "s-clock.json"
    ahead = time.time() + 86400
    state.write_text(json.dumps({"count": 0, "stamps": [ahead, ahead]}))
    check("a stamp dated in the future does not deny",
          decision(spawn(home, session="clock")), None)
    check("a future stamp is dropped rather than kept forever",
          [t for t in state_of(home, "clock")["stamps"] if t >= ahead], [])


def test_prune_keeps_live_locks(home):
    print("pruning")
    set_config(home, {"state_retention_days": 1})
    spawn(home, session="prune")
    state_dir = home / ".claude" / "agent-spawn-budget"
    lock = state_dir / "sessions.lock"
    check("the shared session lock exists", lock.exists(), True)
    old = time.time() - 5 * 86400
    os.utime(lock, (old, old))
    spawn(home, session="other")
    check("an ancient lock file is never pruned", lock.exists(), True)
    check("a live session's state survives pruning",
          (state_dir / "s-prune.json").exists(), True)
    stale = state_dir / "s-stale.json"
    stale.write_text(json.dumps({"count": 1, "stamps": []}))
    os.utime(stale, (old, old))
    spawn(home, session="other2")
    check("a stale session's state is pruned", stale.exists(), False)
    check("the shared lock still survives", lock.exists(), True)
    check("the grant lock is never pruned",
          (state_dir / "allow.json.lock").exists(), True)
    stray = state_dir / "not-a-session.json"
    stray.write_text("{}")
    os.utime(stray, (old, old))
    spawn(home, session="other3")
    check("a file that is not session state is left alone", stray.exists(), True)
    stray.unlink()


def test_reserved_session_ids(home):
    print("reserved session ids")
    set_config(home, {})
    state_dir = home / ".claude" / "agent-spawn-budget"
    run(home, None, "--allow", "a reason", "--spawns", "5", "--minutes", "15")
    for name in ["allow", "prune", "sessions"]:
        proc = spawn(home, session=name, model=None)
        check("a session called %r does not crash" % name, proc.returncode, 0)
    # The denied spawns spend the grant, which is the design. What must not
    # happen is a session writing its own counters over the grant file.
    grant = json.loads((state_dir / "allow.json").read_text())
    check("the grant file still holds a grant, not session state",
          sorted(grant)[:3], ["expires", "granted_at", "reason"])
    # Only the first spender claims it, so one of the three was let through.
    check("the grant was spent, not overwritten", grant["spawns"], 4)
    check("the grant bound to the session id", grant["session"], "allow")
    check("the shared lock is still a lock, not session state",
          (state_dir / "sessions.lock").read_text(), "")
    check("a session called allow gets its own prefixed file",
          (state_dir / "s-allow.json").exists(), True)
    run(home, None, "--revoke")

def test_config_fallback(home):
    print("config fallback")
    project = home / "project"
    (project / ".claude").mkdir(parents=True, exist_ok=True)
    (project / ".claude" / "agent-spawn-budget.json").write_text("{ not json")
    set_config(home, {"burst_max": 5})
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin",
           "CLAUDE_PROJECT_DIR": str(project)}
    results = []
    for _ in range(6):
        proc = subprocess.run(
            [sys.executable, str(HOOK), "--hook"],
            input=json.dumps(payload_for(session="fallback")),
            capture_output=True, text=True, env=env, cwd=str(home))
        results.append("deny" if proc.stdout.strip() else None)
    check("a broken project config falls through to the home config",
          results, [None] * 5 + ["deny"])


def test_flag_misuse(home):
    print("flag misuse")
    proc = run(home, None, "--session", "abc")
    check("--session without --allow is refused", proc.returncode != 0, True)


def test_large_burst_max(home):
    print("a burst_max above the retained window")
    set_config(home, {"burst_max": 205, "burst_window_seconds": 3600})
    results = []
    for _ in range(210):
        results.append(decision(spawn(home, session="wide")))
    allowed = sum(1 for r in results if r is None)
    check("a burst_max of 205 allows exactly 205", allowed, 205)
    check("a burst_max of 205 denies the 206th", results[205], "deny")
    check("the retained window grew to hold the cap",
          len(state_of(home, "wide")["stamps"]) >= 205, True)


def test_one_action_per_run(home):
    print("one action per run")
    set_config(home, {})
    run(home, None, "--revoke")
    proc = run(home, None, "--allow", "a real reason", "--status")
    check("--allow with --status is refused", proc.returncode != 0, True)
    check("--allow with --status writes no grant",
          (home / ".claude" / "agent-spawn-budget" / "allow.json").exists(), False)
    proc = run(home, None, "--spawns", "9")
    check("--spawns without --allow is refused", proc.returncode != 0, True)
    proc = run(home, None, "--minutes", "9")
    check("--minutes without --allow is refused", proc.returncode != 0, True)
    proc = run(home, None, "--revoke", "--status")
    check("--revoke with --status is refused", proc.returncode != 0, True)
    proc = run(home, None, "--allow", "still fine", "--spawns", "2")
    check("--allow on its own still works", proc.returncode, 0)
    run(home, None, "--revoke")


def test_every_flag_spelling(home):
    print("every flag spelling")
    set_config(home, {})
    run(home, None, "--revoke")
    for args in (("--status", "--spawns=6"), ("--status", "--spa", "6"),
                 ("--hook", "--spawns=6"), ("--status", "--minutes=9"),
                 ("--status", "--min", "9"), ("--revoke", "--spawns=6"),
                 ("--report", "--minutes=1"), ("--status", "--sess", "abc")):
        proc = run(home, None, *args)
        check("%s is refused" % " ".join(args), proc.returncode != 0, True)
    proc = run(home, None, "--allow", "fine", "--spawns=3", "--minutes=5")
    check("--allow with = spellings works", proc.returncode, 0)
    grant = json.loads((home / ".claude" / "agent-spawn-budget"
                        / "allow.json").read_text())
    check("the = spellings carry their values", (grant["spawns"],), (3,))
    run(home, None, "--revoke")


def test_grant_bounds(home):
    print("grant bounds")
    run(home, None, "--revoke")
    proc = run(home, None, "--allow", "empty session", "--session", "")
    check("an empty --session is refused", proc.returncode != 0, True)
    proc = run(home, None, "--allow", "too long", "--minutes", "999999999")
    check("an absurd --minutes is refused", proc.returncode != 0, True)
    proc = run(home, None, "--allow", "too many", "--spawns", "100000")
    check("an absurd --spawns is refused", proc.returncode != 0, True)
    check("none of those wrote a grant",
          (home / ".claude" / "agent-spawn-budget" / "allow.json").exists(), False)
    proc = run(home, None, "--allow", "no qualifiers")
    check("--allow alone uses the defaults", proc.returncode, 0)
    grant = json.loads((home / ".claude" / "agent-spawn-budget"
                        / "allow.json").read_text())
    check("the default grant is 6 spawns", grant["spawns"], 6)
    run(home, None, "--revoke")


def test_prune_holds_the_lock(home):
    print("pruning under a lock")
    set_config(home, {"state_retention_days": 1})
    spawn(home, session="live")
    state_dir = home / ".claude" / "agent-spawn-budget"
    old = time.time() - 5 * 86400
    lock = state_dir / "sessions.lock"
    # A denied first spawn records nothing, so a session can hold the lock with
    # no state file of its own. Pruning must not read that as an orphaned lock.
    check("a denied spawn writes no state",
          decision(spawn(home, session="nostate", model=None)), "deny")
    check("and leaves no state file",
          (state_dir / "s-nostate.json").exists(), False)
    os.utime(lock, (old, old))
    stale_state = state_dir / "s-gone.json"
    stale_state.write_text(json.dumps({"count": 1, "stamps": []}))
    os.utime(stale_state, (old, old))
    spawn(home, session="trigger")
    check("a stale session's state is pruned", stale_state.exists(), False)
    check("the lock every session shares is never unlinked", lock.exists(), True)
    check("the live session's state survives",
          (state_dir / "s-live.json").exists(), True)
    orphan = state_dir / "s-dead.json.999.tmp"
    orphan.write_text("{}")
    os.utime(orphan, (old, old))
    spawn(home, session="trigger3")
    check("an orphaned temp file is reclaimed", orphan.exists(), False)
    # Pruning runs on every hook, so the lock must still work afterwards.
    set_config(home, {"state_retention_days": 1, "burst_window_seconds": 3600})
    check("the budget still enforces after a prune",
          [decision(spawn(home, session="afterprune")) for _ in range(3)],
          [None, None, "deny"])

def test_status_survives_a_vanishing_entry(home):
    print("status robustness")
    set_config(home, {})
    state_dir = home / ".claude" / "agent-spawn-budget"
    broken = state_dir / "s-broken.json"
    broken.symlink_to(state_dir / "s-nothing-here.json")
    proc = run(home, None, "--status")
    check("--status survives a broken entry", proc.returncode, 0)
    check("--status still prints the config", "burst_max" in proc.stdout_text, True)
    broken.unlink()


def hook_entry(command="python3 /x/agent_spawn_budget.py --hook"):
    return [{"hooks": [{"type": "command", "command": command}]}]


INFLIGHT_SETTINGS = {"hooks": {"SubagentStart": hook_entry(), "SubagentStop": hook_entry()}}


def register_inflight(home, settings=INFLIGHT_SETTINGS):
    path = home / ".claude" / "settings.json"
    if settings is None:
        if path.exists():
            path.unlink()
    else:
        path.write_text(json.dumps(settings))


def agent_event(home, event, agent_id, session="s1", agent_type="general-purpose"):
    body = {"session_id": session, "hook_event_name": event, "agent_type": agent_type}
    if agent_id is not None:
        body["agent_id"] = agent_id
    return run(home, body, "--hook")


def start(home, agent_id, **kwargs):
    return agent_event(home, "SubagentStart", agent_id, **kwargs)


def stop(home, agent_id, **kwargs):
    return agent_event(home, "SubagentStop", agent_id, **kwargs)


def running_of(home, session):
    path = home / ".claude" / "agent-spawn-budget" / ("s-" + session + ".json")
    if not path.exists():
        return {}
    return state_of(home, session).get("inflight", {})


def spawn_and_start(home, agent_id, session, **kwargs):
    """A spawn the hook judges, then the start event Claude Code sends if it ran."""
    proc = spawn(home, session=session, **kwargs)
    if decision(proc) is None:
        start(home, agent_id, session=session,
              agent_type=kwargs.get("subagent_type") or "general-purpose")
    return decision(proc)


def test_inflight(home):
    print("agents in flight")
    # A burst window of 0 switches the burst rule off, which is exactly the
    # spaced-out fan-out the in-flight rule exists for.
    set_config(home, {"burst_window_seconds": 0, "inflight_max": 1})

    register_inflight(home, None)
    check("with no registration, spaced spawns all pass",
          [spawn_and_start(home, "a%d" % i, "f0") for i in range(3)], [None] * 3)
    check("and nothing is recorded as running", running_of(home, "f0"), {})
    register_inflight(home, {"hooks": {"SubagentStop": hook_entry()}})
    check("SubagentStop alone does not turn the rule on",
          [spawn_and_start(home, "b%d" % i, "f0b") for i in range(2)], [None, None])
    check("--status names the missing event",
          "under SubagentStart to turn it on" in run(home, None, "--status").stdout_text,
          True)

    register_inflight(home)
    check("the first spawn passes", spawn_and_start(home, "A", "f1"), None)
    check("its start is recorded by agent_id", list(running_of(home, "f1")), ["A"])
    proc = spawn(home, session="f1")
    check("a second spawn while A runs is denied", decision(proc), "deny")
    check("the denial says an agent is still running",
          "still running" in proc.stdout_text, True)
    check("the denial names this script's own path for --allow",
          "python3 %s --allow" % HOOK.absolute() in proc.stdout_text, True)
    proc = stop(home, "A", session="f1")
    check("a stop exits 0 and prints no decision",
          (proc.returncode, proc.stdout_text.strip()), (0, ""))
    check("the stop removes A", running_of(home, "f1"), {})
    check("the next spawn passes once A has finished",
          spawn_and_start(home, "B", "f1"), None)
    check("another session is not blocked by this one",
          spawn_and_start(home, "C", "f2"), None)

    check("a spawn that is allowed but never starts records nothing",
          decision(spawn(home, session="f3")), None)
    check("so the next spawn is not blocked by it",
          spawn_and_start(home, "D", "f3"), None)
    stop(home, "D", session="f3")
    check("and D's stop leaves nothing running", running_of(home, "f3"), {})

    set_config(home, {"burst_window_seconds": 0, "inflight_max": 2})
    spawn_and_start(home, "old", "f4")
    spawn_and_start(home, "new", "f4")
    stop(home, "new", session="f4")
    check("a stop removes its own agent, not the oldest", list(running_of(home, "f4")),
          ["old"])
    stop(home, "never-started", session="f4")
    check("a stop for an unknown agent_id changes nothing", list(running_of(home, "f4")),
          ["old"])
    stop(home, "x", session="never-spawned")
    check("a stop for a session with no state writes no file",
          (home / ".claude" / "agent-spawn-budget" / "s-never-spawned.json").exists(),
          False)
    for body in ({"hook_event_name": "SubagentStop", "session_id": "f4"},
                 {"hook_event_name": "SubagentStart", "session_id": "f4", "agent_id": 7},
                 {"hook_event_name": "SubagentStop", "session_id": ["x"], "agent_id": "a"}):
        proc = run(home, body, "--hook")
        check("an event payload %r does not crash" % body,
              (proc.returncode, proc.stdout_text.strip()), (0, ""))

    set_config(home, {"burst_window_seconds": 0, "inflight_max": 1, "inflight_ttl_minutes": 30})
    path = home / ".claude" / "agent-spawn-budget" / "s-f5.json"
    path.write_text(json.dumps({"count": 1, "stamps": [],
                                "inflight": {"long": time.time() - 31 * 60}}))
    check("an agent past the TTL no longer counts", spawn_and_start(home, "E", "f5"), None)
    check("its entry is kept until its own stop", sorted(running_of(home, "f5")),
          ["E", "long"])
    stop(home, "long", session="f5")
    check("the long agent's stop removes only its own entry",
          list(running_of(home, "f5")), ["E"])
    check("so E still blocks the next spawn", decision(spawn(home, session="f5")), "deny")
    path.write_text(json.dumps({"count": 1, "stamps": [],
                                "inflight": {"lost": time.time() - 25 * 3600}}))
    spawn(home, session="f5")
    check("an entry past the 24 h keep horizon is dropped on the next write",
          running_of(home, "f5"), {})
    for junk in ("junk", [time.time()], {"a": "x", "b": True}):
        path.write_text(json.dumps({"count": 1, "stamps": [], "inflight": junk}))
        check("a malformed inflight field %r reads as none running" % (junk,),
              decision(spawn(home, session="f5")), None)

    set_config(home, {"burst_window_seconds": 0, "inflight_max": 1,
                      "exempt_subagent_types": ["general-purpose"]})
    check("a spawn naming no type is exempt as general-purpose",
          [spawn_and_start(home, "g%d" % i, "f6") for i in range(2)], [None, None])
    check("and its start records nothing", running_of(home, "f6"), {})
    set_config(home, {"burst_max": 0, "exempt_subagent_types": ["general-purpose"]})
    check("an untyped spawn passes a zero burst budget when general-purpose is exempt",
          decision(spawn(home, session="f6b")), None)
    set_config(home, {"burst_window_seconds": 0, "inflight_max": 1, "exempt_subagent_types": ["reviewer"]})
    spawn_and_start(home, "H", "f7")
    check("an exempt type passes while another runs",
          spawn_and_start(home, "R", "f7", subagent_type="reviewer"), None)
    stop(home, "R", session="f7", agent_type="reviewer")
    check("the exempt agent's stop leaves H running", list(running_of(home, "f7")), ["H"])

    set_config(home, {"burst_window_seconds": 0, "inflight_max": 1, "enforce": False})
    spawn_and_start(home, "I", "f8")
    proc = spawn(home, session="f8")
    check("enforce false allows a spawn while one runs", decision(proc), None)
    check("enforce false reports the in-flight denial",
          "still running" in proc.stderr_text, True)

    set_config(home, {"burst_window_seconds": 0, "inflight_max": 1})
    spawn_and_start(home, "J", "f9")
    run(home, None, "--allow", "one reviewer beside the running sweep",
        "--spawns", "1", "--minutes", "15")
    check("a grant lets a spawn through while one runs",
          spawn_and_start(home, "K", "f9"), None)
    check("the granted agent counts as running too", sorted(running_of(home, "f9")),
          ["J", "K"])
    run(home, None, "--revoke")

    set_config(home, {"burst_window_seconds": 0, "inflight_ttl_minutes": 0})
    proc = spawn(home, session="f10")
    check("inflight_ttl_minutes 0 warns", "counts no running agent" in proc.stderr_text, True)
    check("inflight_ttl_minutes 0 turns the rule off",
          [spawn_and_start(home, "t%d" % i, "f10") for i in range(2)], [None, None])
    check("--status says so",
          "off (inflight_ttl_minutes is 0)" in run(home, None, "--status").stdout_text, True)

    set_config(home, {"burst_window_seconds": 0, "inflight_max": 0})
    check("inflight_max 0 switches the rule off",
          [spawn_and_start(home, "z%d" % i, "f11") for i in range(3)], [None] * 3)

    set_config(home, {"burst_window_seconds": 0})
    check("by default two run at once and the third is denied",
          [spawn_and_start(home, "m%d" % i, "f12") for i in range(3)],
          [None, None, "deny"])

    set_config(home, {"burst_window_seconds": 0, "inflight_max": 1})
    check("--status says the rule is on",
          "In-flight rule: on" in run(home, None, "--status").stdout_text, True)
    register_inflight(home, {"hooks": {
        "SubagentStart": [{"hooks": [{"type": "command", "command": "echo 'unclosed"},
                                     {"type": "command",
                                      "command": "python3 /x/agent_spawn_budget.py"}]}],
        "SubagentStop": hook_entry()}})
    check("an unparseable command does not hide a valid one beside it",
          "In-flight rule: on" in run(home, None, "--status").stdout_text, True)
    register_inflight(home, {"hooks": {"SubagentStart": hook_entry("python3 /x/test_agent_spawn_budget.py"),
                                       "SubagentStop": hook_entry()}})
    check("a command naming a different file does not count",
          [spawn_and_start(home, "n%d" % i, "f13") for i in range(2)], [None, None])
    (home / ".claude" / "settings.json").write_text("{ not json")
    check("a broken settings file turns the rule off, not the hook",
          [spawn_and_start(home, "o%d" % i, "f14") for i in range(2)], [None, None])
    register_inflight(home, None)

    local = home / ".claude" / "settings.local.json"
    local.write_text(json.dumps(INFLIGHT_SETTINGS))
    check("--status run from the project folder sees a project registration",
          "In-flight rule: on" in run(home, None, "--status").stdout_text, True)
    local.unlink()

    project = home / "inflight-project"
    (project / ".claude").mkdir(parents=True, exist_ok=True)
    (project / ".claude" / "settings.local.json").write_text(json.dumps(INFLIGHT_SETTINGS))
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(project)}

    def hook(body):
        proc = subprocess.run([sys.executable, str(HOOK), "--hook"], input=json.dumps(body),
                              capture_output=True, text=True, env=env, cwd=str(home))
        return "deny" if proc.stdout.strip() else None

    results = [hook(payload_for(session="f15"))]
    hook({"session_id": "f15", "hook_event_name": "SubagentStart", "agent_id": "P",
          "agent_type": "general-purpose"})
    results.append(hook(payload_for(session="f15")))
    check("a registration in the project's settings.local.json turns the rule on",
          results, [None, "deny"])
    set_config(home, {})


def test_deleted_working_directory(home):
    print("a deleted working directory")
    set_config(home, {})
    gone = home / "gone"
    gone.mkdir()
    proc = subprocess.Popen([sys.executable, str(HOOK), "--hook"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, cwd=str(gone),
                            preexec_fn=lambda: os.rmdir(str(gone)))
    out, err = proc.communicate(json.dumps(payload_for(session="gone")))
    check("the hook exits 0 from a deleted working directory", proc.returncode, 0)
    check("and still judges the spawn by the home config",
          (out.strip(), "Traceback" in err), ("", False))


def test_inflight_concurrency(home):
    print("agents in flight, concurrently")
    register_inflight(home)
    set_config(home, {"burst_max": 99, "inflight_max": 99})
    procs = [run(home, None, "--hook", wait=False) for _ in range(8)]
    for i, proc in enumerate(procs):
        proc.communicate(json.dumps({"session_id": "land", "agent_id": "c%d" % i,
                                     "hook_event_name": "SubagentStart",
                                     "agent_type": "general-purpose"}))
    check("eight starts at once record all eight", len(running_of(home, "land")), 8)
    procs = [run(home, None, "--hook", wait=False) for _ in range(8)]
    for i, proc in enumerate(procs):
        proc.communicate(json.dumps({"session_id": "land", "agent_id": "c%d" % i,
                                     "hook_event_name": "SubagentStop"}))
    check("eight stops at once remove all eight", running_of(home, "land"), {})
    register_inflight(home, None)
    set_config(home, {})


def main():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / ".claude").mkdir()
        test_defaults(home)
        test_grant(home)
        test_config(home)
        test_malformed(home)
        test_concurrency(home)
        test_filesystem_failure(home)
        test_future_stamp(home)
        test_prune_keeps_live_locks(home)
        test_reserved_session_ids(home)
        test_config_fallback(home)
        test_flag_misuse(home)
        test_large_burst_max(home)
        test_one_action_per_run(home)
        test_every_flag_spelling(home)
        test_grant_bounds(home)
        test_prune_holds_the_lock(home)
        test_status_survives_a_vanishing_entry(home)
        test_inflight(home)
        test_inflight_concurrency(home)
        test_deleted_working_directory(home)
        test_status(home)

    if FAILURES:
        print("\n%d failed: %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("\nall passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
