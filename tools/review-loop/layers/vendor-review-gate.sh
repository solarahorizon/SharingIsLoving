#!/usr/bin/env bash
# vendor-review-gate — the cross-vendor review RUNNER (writes the sentinel the
# commit gate checks). Runs a different-vendor AI on the staged diff and writes
# docs/dev-review/last-vendor-review-sha.txt ONLY on a no-[P1] pass.
#
# Config-aware: reads `vendor` + `vendor_fallback` from the project's
# .claude/review-loop.json (via config.py). If the primary vendor is
# rate-limited / unavailable, it AUTO-FALLS-BACK to the fallback vendor so the
# review never silently skips. Env overrides win: VENDOR=..., VENDOR_FALLBACK=...
#
# Vendor runners (bring your own):
#   codex    — OpenAI's `codex` CLI on PATH (`codex exec ...`).
#   deepseek — a runner script that reads a diff file arg + $DEEPSEEK_SYS and
#              prints the review. Defaults to ~/.config/deepseek/deepseek-review.sh;
#              point $DEEPSEEK_RUNNER elsewhere to override.
#
#   bash vendor-review-gate.sh          # uses the project's configured vendor(+fallback)
#   VENDOR=codex bash vendor-review-gate.sh
#
# The sentinel is the SHA-256 of the staged diff, so it can't be reused for a
# different diff. Written by THIS gate on a genuine PASS — never hand-write it.
# (Battle-tested behaviours kept from the original: memoize, hard timeout, one
# retry, [P1]-as-line-marker detection to avoid CLEAN-verdict false FAILs.)
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"; RLDIR="$(dirname "$SRC")"
ROOT="$(git rev-parse --show-toplevel)"
SENTINEL="$ROOT/docs/dev-review/last-vendor-review-sha.txt"
VENDOR_TIMEOUT="${VENDOR_TIMEOUT:-200}"
TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"

cfg() { python3 "$RLDIR/config.py" "$ROOT" 2>/dev/null | python3 -c "import json,sys;print(json.load(sys.stdin).get('$1') or '')" 2>/dev/null || true; }
VENDOR="${VENDOR:-$(cfg vendor)}";        VENDOR="${VENDOR:-codex}"
FALLBACK="${VENDOR_FALLBACK-$(cfg vendor_fallback)}"

DIFF="$(mktemp -t vendor-review.XXXXXX)"; trap 'rm -f "$DIFF"' EXIT
git -C "$ROOT" diff --cached > "$DIFF"
[ -s "$DIFF" ] || { echo "vendor-review-gate: no staged changes — nothing to review."; exit 1; }
# THE staged-diff identity — computed by gatecore so it always matches the gate
# (never a second hasher; shell shasum can differ on large diffs).
HASH="$(python3 -c "import sys;sys.path.insert(0,'$SRC');import gatecore;print(gatecore.staged_sha('$ROOT') or '')")"
[ -n "$HASH" ] || { echo "vendor-review-gate: could not compute staged-diff hash."; exit 1; }

# MEMOIZE — this exact staged diff already passed.
if [ -f "$SENTINEL" ] && [ "$(awk 'NR==1{print;exit}' "$SENTINEL")" = "$HASH" ]; then
  echo "vendor-review-gate: PASS (memoized) — staged-diff $HASH already reviewed; API skipped."; exit 0
fi

SYS="You are a SECOND-VENDOR code reviewer (different model family from Claude) gating a commit. Review the diff for correctness bugs, security (esp. secret/key leakage), data-safety/fabrication risk, and resource issues. Tag every finding [P1] critical / [P2] important / [P3] minor with a location. If nothing is critical, say CLEAN and do not invent findings. Be concise."

# One invocation of a given vendor, hard-bounded, never trips `set -e`; always
# resolves to text (a VENDOR ERROR marker on failure) so the caller can decide.
run_one() {
  local v="$1" rc=0 tb=(); [ -n "$TIMEOUT_BIN" ] && tb=("$TIMEOUT_BIN" "$VENDOR_TIMEOUT")
  case "$v" in
    codex)    "${tb[@]}" codex exec "Review the code diff in the file $DIFF. $SYS" 2>&1 || rc=$?
              [ "$rc" -eq 0 ] || echo "VENDOR ERROR: codex unavailable/rate-limited/timed-out (exit $rc)." ;;
    deepseek) DEEPSEEK_SYS="$SYS" "${tb[@]}" bash "${DEEPSEEK_RUNNER:-$HOME/.config/deepseek/deepseek-review.sh}" "$DIFF" 2>&1 || rc=$?
              [ "$rc" -eq 0 ] || echo "VENDOR ERROR: deepseek call failed/timed-out (exit $rc)." ;;
    *)        echo "VENDOR ERROR: unknown vendor '$v'." ;;
  esac
}
bad() { [ -z "${1//[[:space:]]/}" ] || printf '%s' "$1" | grep -qiE 'VENDOR ERROR|DEEPSEEK ERROR|missing.*key'; }

echo "vendor-review-gate: running '$VENDOR' on the staged diff ($(wc -l < "$DIFF" | tr -d ' ') lines; ${VENDOR_TIMEOUT}s ceiling)…"
OUT="$(run_one "$VENDOR")"
if bad "$OUT" && [ -n "$FALLBACK" ] && [ "$FALLBACK" != "$VENDOR" ]; then
  echo "vendor-review-gate: '$VENDOR' unavailable — falling back to '$FALLBACK'…"
  OUT="$(run_one "$FALLBACK")"; USED="$FALLBACK"
else USED="$VENDOR"; fi
bad "$OUT" && { echo "vendor-review-gate: retry '$USED' once…"; OUT="$(run_one "$USED")"; }

echo "----------------------------------------------------------------------"
echo "$OUT"
echo "----------------------------------------------------------------------"

if bad "$OUT"; then
  echo "vendor-review-gate: FAIL — no usable verdict from '$VENDOR'${FALLBACK:+/'$FALLBACK'} (rate-limited/hung). Sentinel NOT written."; exit 1
fi
# [P1] only as a FINDING marker (line start, after markdown lead-ins) — not inside
# prose like "no [P1] issues" or an echoed "Tag [P1]/[P2]/[P3]" instruction.
if printf '%s' "$OUT" | grep -qE '^[[:space:]*#_>-]*\[P1\]'; then
  echo "vendor-review-gate: FAIL — [P1] finding(s) present. Fix, re-stage, re-run. Sentinel NOT written."; exit 1
fi

python3 "$SRC/write-sentinel.py" last-vendor-review-sha.txt >/dev/null
echo "vendor-review-gate: PASS ($USED) — sentinel written for staged-diff $HASH"
echo "(now ensure the dev-review sentinel is written too, then commit.)"
