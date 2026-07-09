#!/usr/bin/env python3
"""review-loop config resolver — the single source of truth for defaults + profiles.

Reads a project's .claude/review-loop.json (if present), applies a named profile,
folds in per-project overrides, and prints the fully-resolved config as JSON. The
installer and the gate scripts both call this so there is ONE definition of what a
project's review loop looks like — no per-project drift.

Usage:
  config.py <project-dir>            # print resolved config JSON
  config.py <project-dir> --list     # human-readable summary (which layers are on)

Resolution order (last wins): DEFAULTS  ->  profile's layer set  ->  explicit "layers"
overrides  ->  explicit top-level keys (merge_base / vendor / vendor_fallback).
A project with NO review-loop.json resolves to the DEFAULTS below (profile "standard").
"""
import json
import os
import sys

# ---- defaults (change a project by overriding these in .claude/review-loop.json) ----
DEFAULTS = {
    "merge_base": "main",        # default branch PRs merge into; override per project (e.g. "develop")
    "vendor": "codex",           # primary cross-model reviewer: "codex" | "deepseek"
    "vendor_fallback": "deepseek",  # used when the primary is rate-limited/unavailable; null to disable
}

# ---- the five review layers (each independently on/off per project) ----
# NOTE: shell-hygiene ("clean shell") is deliberately NOT here — it's a run-reliability
# primitive that keeps an UNATTENDED run from stalling, not a code-review gate. It is
# packaged with the autonomous-block skill (the "keep the agent alive" side), not the
# review loop (the "keep the agent honest" side).
LAYERS = [
    "dev_review",           # separate-agent review, diff-bound sentinel; blocks git commit
    "cross_vendor_commit",  # codex/deepseek 2nd leg on the staged diff; blocks git commit
    "merge_gate",           # cross-model review of the PR head; blocks gh pr merge
    "native_git_hook",      # HARD git-layer gate (sub-agents, `add && commit` one-liners)
    "ci_backstop",          # server-side build/audit (documented; wired outside this installer)
]

# ---- named profiles: pick one, override individual layers as needed ----
PROFILES = {
    # lightest — just the separate-agent review
    "minimal": {"dev_review": True},
    # the common case — 2-leg commit gate + PR merge gate
    "standard": {"dev_review": True, "cross_vendor_commit": True, "merge_gate": True},
    # highest assurance — adds the un-bypassable git hook + CI
    "strict": {"dev_review": True, "cross_vendor_commit": True, "merge_gate": True,
               "native_git_hook": True, "ci_backstop": True},
}
DEFAULT_PROFILE = "standard"


def resolve(project_dir):
    cfg_path = os.path.join(project_dir, ".claude", "review-loop.json")
    raw = {}
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            raw = json.load(f)

    profile = raw.get("profile", DEFAULT_PROFILE)
    if profile not in PROFILES:
        raise SystemExit(f"unknown profile {profile!r} (choose one of: {', '.join(PROFILES)})")

    layers = {name: False for name in LAYERS}
    layers.update(PROFILES[profile])          # profile turns some on
    layers.update(raw.get("layers", {}))      # explicit per-project overrides win

    out = dict(DEFAULTS)
    for key in ("merge_base", "vendor", "vendor_fallback"):
        if key in raw:
            out[key] = raw[key]
    out["profile"] = profile
    out["layers"] = layers
    out["config_present"] = os.path.exists(cfg_path)
    return out


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    project = sys.argv[1]
    r = resolve(project)
    if "--list" in sys.argv[2:]:
        on = [n for n in LAYERS if r["layers"][n]]
        off = [n for n in LAYERS if not r["layers"][n]]
        src = "review-loop.json" if r["config_present"] else "DEFAULTS (no review-loop.json)"
        print(f"project      : {project}")
        print(f"config source: {src}")
        print(f"profile      : {r['profile']}")
        print(f"merge_base   : {r['merge_base']}")
        print(f"vendor       : {r['vendor']}  (fallback: {r['vendor_fallback']})")
        print(f"layers ON    : {', '.join(on) or '(none)'}")
        print(f"layers OFF   : {', '.join(off) or '(none)'}")
    else:
        print(json.dumps(r, indent=2))


if __name__ == "__main__":
    main()
