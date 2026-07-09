#!/usr/bin/env bash
# review-loop installer — wire the enabled layers of a project's review loop.
#
# Reads <project>/.claude/review-loop.json (resolved through config.py) and wires
# exactly the layers it turns on. Idempotent: re-run any time; it replaces its own
# managed entries rather than duplicating them.
#
# Usage:
#   install.sh <project-dir>            # wire the enabled layers
#   install.sh <project-dir> --list     # show the resolved config, wire nothing
#   install.sh <project-dir> --dry-run  # print what WOULD change
#   install.sh <project-dir> --uninstall# remove review-loop's managed entries
#
# Missing <project>/.claude/review-loop.json is created from the example (preset
# "standard") so you can edit it and re-run.
#
# Layers wired here: commit gate (dev_review / cross_vendor_commit) + merge_gate
# as PreToolUse hooks; native_git_hook as a .git/hooks/pre-commit shim.
# ci_backstop is intentionally NOT wired here — it's a server-side CI job (out of
# band); the installer only reports whether the config asks for it.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
HOME_REL="${SRC_DIR/#$HOME/\$HOME}"            # literal $HOME so paths resolve per-machine
COMMIT_CMD="python3 \"$HOME_REL/layers/pre-commit-check.py\""
MERGE_CMD="python3 \"$HOME_REL/layers/pre-merge-check.py\""
NATIVE_SCRIPT="$HOME_REL/layers/native-pre-commit.py"
MANAGED_MARK="review-loop/layers/"            # any settings.json entry we manage contains this
SHIM_MARK="# review-loop native hook"          # marks our .git/hooks/pre-commit shim

PROJECT="${1:-}"
MODE="${2:-install}"
[ -n "$PROJECT" ] || { echo "usage: install.sh <project-dir> [--list|--dry-run|--uninstall]" >&2; exit 1; }
PROJECT="$(cd "$PROJECT" && pwd)" || { echo "✗ no such dir: $1" >&2; exit 1; }

CFG="$PROJECT/.claude/review-loop.json"
if [ ! -f "$CFG" ] && [ "$MODE" != "--uninstall" ]; then
  mkdir -p "$PROJECT/.claude"
  cp "$SRC_DIR/review-loop.example.json" "$CFG"
  echo "· created $CFG (from example — edit + re-run)"
fi

if [ "$MODE" = "--list" ]; then
  python3 "$SRC_DIR/config.py" "$PROJECT" --list
  exit 0
fi

field() { python3 "$SRC_DIR/config.py" "$PROJECT" | python3 -c "import json,sys;d=json.load(sys.stdin);print($1)"; }
DEV="$(field "d['layers']['dev_review']")"
VENDOR="$(field "d['layers']['cross_vendor_commit']")"
MERGE="$(field "d['layers']['merge_gate']")"
NATIVE="$(field "d['layers']['native_git_hook']")"
CI="$(field "d['layers']['ci_backstop']")"
PRESET="$(field "d['profile']")"; BASE="$(field "d['merge_base']")"; VEND="$(field "d['vendor']")"

want_commit="no"; { [ "$DEV" = "True" ] || [ "$VENDOR" = "True" ]; } && want_commit="yes"
UNINSTALL="no"; [ "$MODE" = "--uninstall" ] && UNINSTALL="yes"

echo "review-loop · $PROJECT"
echo "  preset=$PRESET  merge_base=$BASE  vendor=$VEND"
echo "  commit-gate=$want_commit  merge_gate=$MERGE  native_git_hook=$NATIVE  ci_backstop=$CI"

HOOKDIR="$(cd "$PROJECT" && git rev-parse --git-path hooks)"; case "$HOOKDIR" in /*) ;; *) HOOKDIR="$PROJECT/$HOOKDIR";; esac
# git invokes a DIFFERENT hook per commit-creating path — wire the shim into each:
#   pre-commit       — `git commit` (and `--amend`), cherry-pick, revert (modern git)
#   pre-merge-commit — `git merge` / `git pull` that create a merge commit
#   pre-applypatch   — `git am` (mailbox patches; does NOT fire pre-commit)
# Coverage note: plain `git rebase` replays already-committed (already-reviewed) commits
# and fires no per-pick hook — acceptable, as it lands no NEW content. Fast-forwards fire
# no hook at all (documented limitation above). The PreToolUse gate covers all these on
# the agent path regardless.
NATIVE_HOOKS="pre-commit pre-merge-commit pre-applypatch"

if [ "$MODE" = "--dry-run" ]; then
  echo "  [dry-run] commit-gate PreToolUse hook: $([ "$want_commit" = yes ] && echo wire || echo remove)"
  echo "  [dry-run] merge_gate PreToolUse hook:  $([ "$MERGE" = True ] && echo wire || echo remove)"
  echo "  [dry-run] native_git_hook shims ($NATIVE_HOOKS): $([ "$NATIVE" = True ] && echo install || echo remove)"
  [ "$CI" = "True" ] && echo "  [dry-run] ci_backstop: ON in config — wire a server-side CI job yourself (not installer-managed)"
  exit 0
fi

# --- settings.json: rebuild the review-loop-managed PreToolUse groups -----------
mkdir -p "$PROJECT/.claude"; SETTINGS="$PROJECT/.claude/settings.json"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
CG=""; MG=""
[ "$UNINSTALL" = no ] && [ "$want_commit" = yes ] && CG="$COMMIT_CMD"
[ "$UNINSTALL" = no ] && [ "$MERGE" = "True" ] && MG="$MERGE_CMD"
SETTINGS="$SETTINGS" MARK="$MANAGED_MARK" CG="$CG" MG="$MG" python3 - <<'PY'
import json, os
p=os.environ["SETTINGS"]; mark=os.environ["MARK"]; cg=os.environ["CG"]; mg=os.environ["MG"]
try: d=json.load(open(p))
except Exception: d={}
hooks=d.setdefault("hooks",{}); pre=hooks.setdefault("PreToolUse",[])
pre=[g for g in pre if not any(mark in h.get("command","") for h in g.get("hooks",[]))]  # drop ours
for cmd in (cg,mg):
    if cmd: pre.append({"matcher":"Bash","hooks":[{"type":"command","command":cmd}]})
hooks["PreToolUse"]=pre
if not pre: hooks.pop("PreToolUse",None)
if not hooks: d.pop("hooks",None)
json.dump(d,open(p,"w"),indent=2); open(p,"a").write("\n")
n=sum(1 for _ in (cg,mg) if _)
print(f"  settings.json: {n} review-loop PreToolUse hook(s) wired" if n else "  settings.json: review-loop hooks removed")
PY

# --- native git hook shims (pre-commit + pre-merge-commit) ----------------------
for HN in $NATIVE_HOOKS; do
  NATIVE_HOOK="$HOOKDIR/$HN"
  if [ "$UNINSTALL" = no ] && [ "$NATIVE" = "True" ]; then
    mkdir -p "$HOOKDIR"
    if [ -e "$NATIVE_HOOK" ] && ! grep -q "$SHIM_MARK" "$NATIVE_HOOK" 2>/dev/null; then
      mv "$NATIVE_HOOK" "$NATIVE_HOOK.pre-review-loop"; echo "  backed up existing $HN -> $HN.pre-review-loop"
    fi
    printf '#!/usr/bin/env bash\n%s\nexec python3 "%s" "$@"\n' "$SHIM_MARK" "$NATIVE_SCRIPT" > "$NATIVE_HOOK"
    chmod +x "$NATIVE_HOOK"; echo "  native_git_hook: installed shim -> $NATIVE_HOOK"
  else
    if [ -e "$NATIVE_HOOK" ] && grep -q "$SHIM_MARK" "$NATIVE_HOOK" 2>/dev/null; then
      rm -f "$NATIVE_HOOK"
      [ -e "$NATIVE_HOOK.pre-review-loop" ] && { mv "$NATIVE_HOOK.pre-review-loop" "$NATIVE_HOOK"; echo "  restored prior $HN hook"; } || echo "  native_git_hook: $HN shim removed"
    fi
  fi
done

# Git fires NO pre-hook on a fast-forward merge (neither pre-commit nor pre-merge-commit).
# merge.ff=false makes DEFAULT `git merge`/`git pull` create a merge commit (which DOES fire
# pre-merge-commit) — closing the common non-flag case. LIMITATION: an explicit
# `git merge --ff-only` / `git pull --ff-only` overrides merge.ff and still fast-forwards
# with no hook — git offers no hook that fires on a fast-forward, so the native (git-layer)
# gate cannot block it. The PreToolUse gate DOES block --ff-only merges (the agent path);
# a raw-terminal --ff-only outside the agent is the residual gap (like `git commit --no-verify`).
if [ "$NATIVE" = "True" ] && [ "$UNINSTALL" = no ]; then
  git -C "$PROJECT" config merge.ff false && echo "  set merge.ff=false (default merges create a reviewable commit; explicit --ff-only can't be hooked — git limitation)"
elif [ "$UNINSTALL" = yes ]; then
  git -C "$PROJECT" config --unset merge.ff 2>/dev/null && echo "  unset merge.ff" || true
fi

# --- sentinel dir + notes -------------------------------------------------------
if [ "$UNINSTALL" = no ] && { [ "$want_commit" = yes ] || [ "$NATIVE" = "True" ]; }; then
  mkdir -p "$PROJECT/docs/dev-review"
  GI="$PROJECT/docs/dev-review/.gitignore"; [ -f "$GI" ] || printf 'last-*-review-sha.txt\n' > "$GI"
  echo "  ensured docs/dev-review/ (+ gitignore for sentinels)"
fi
[ "$UNINSTALL" = no ] && [ "$CI" = "True" ] && echo "  note: ci_backstop is ON — add a server-side CI build/audit job (not installer-managed)"

echo "done."
