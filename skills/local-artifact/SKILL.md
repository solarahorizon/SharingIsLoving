---
name: local-artifact
description: Render a self-contained HTML "artifact" to a local file in your repo instead of publishing it to a vendor's servers via a hosted Artifact tool. Use whenever a visual page — a run wrap-up, status board, decision gallery, review summary, before/after comparison — would communicate better than terminal text, AND the content should stay private / on-disk / version-controlled. Output: one standalone .html file (all assets embedded as data: URIs), opened locally. Invoke this instead of a hosted Artifact tool whenever a visual page is warranted and you want it to live in the repo rather than off-device.
disable-model-invocation: false
allowed-tools: Read Write Edit Glob Grep Bash Skill
---

# Local Artifact Skill

Produce a polished, **fully self-contained** HTML page **as a local file** — never published to a vendor's servers. This is a local-first, privacy-preserving counterpart to Claude Code's built-in **`Artifact` tool** (which publishes each page to a hosted `claude.ai/code/artifact/<uuid>` URL on Anthropic's servers): it reuses Anthropic's **`artifact-design`** craft for the *look* and only swaps the *delivery* — `Write` to disk instead of upload.

## Why this exists

Some agent harnesses ship a built-in *Artifact* tool that **publishes the page to a hosted URL** — the page lives on the vendor's infrastructure, default-private but off-device. If your standing preference is to keep generated pages **on your own disk, version-controlled, and viewable offline** (wrap-ups, status boards, decision galleries are internal working artifacts, not things to hand to a third party), this skill is the alternative.

**Convention: when a visual page is warranted, invoke THIS skill and write to disk. Do NOT call a hosted Artifact tool** — unless the user explicitly asks, in the moment, to publish a specific page to a shareable hosted URL (e.g. "share this with the team via a link").

## When to invoke

- Any "give me a visual picture so I can decide" moment — a decision gallery with real screenshots.
- End-of-run wrap-ups, status boards, review summaries, before/after device-matrix comparisons.
- Any time terminal markdown is too flat for the content AND the page should stay private / on-disk.

Do NOT invoke for a one-line status — plain markdown in the reply is better. Calibrate the treatment to the request (see §Design craft).

## Output contract

1. A single `.html` file written with the `Write` tool — no hosted-Artifact call, no network, no publish.
2. **Default location: a version-controlled docs directory** (this skill's author uses `docs/session/`; pick the folder that fits your repo, or honor any explicit path the user gives). A sensible convention: name recurring wrap-ups predictably, e.g. `RUN_WRAP_<YYYY-MM-DD>.html`; give other pages a short descriptive kebab-case name.
3. **Fully self-contained** — every image embedded as a `data:` URI, all CSS/JS inline. No `src="./foo.png"`, no CDN links, no webfont URLs. This makes the file portable, commit-safe, and viewable offline. (Verification gate below.)
4. Opened at the end so the user can see it. On macOS, `open <path>`; on Linux, `xdg-open <path>`. Also print the re-open command so they can reopen it themselves.
5. Committed to the repo like any other doc artifact (it's a durable record).

## How to build one

### 1. Load design craft first

Before writing the page, if your harness has a built-in **`artifact-design`** skill, invoke it via the `Skill` tool to calibrate treatment (palette, type, layout, honesty rules). We reuse its *craft* guidance and only change the *delivery* — write-to-disk instead of publish-to-a-host. If no such skill exists, apply the craft notes in §Design craft directly. Everything about grounding in the subject, real content (never lorem), honest screenshots, and avoiding templated AI-design still applies.

### 2. Gather REAL assets

For wrap-ups / decision galleries, use **real screenshots** (from a simulator/emulator via its screenshot command, from a headless browser, or any real capture) — not hand-drawn mockups.

**Postmortem behind this rule:** a hand-drawn placeholder that *resembled* the real feature once diverged from what the user had actually signed off, and caused confusion about what shipped. So: **never hand-draw a placeholder that mimics a real feature.** If a real screenshot doesn't exist yet, capture one, or omit the card and say so in text.

### 3. Embed every image as a data URI

Even though a local `file://` page has no strict content-security policy, still embed everything so the file is a single portable, commit-safe artifact. Resize large PNGs first (screenshots are multi-MB) so the HTML stays reasonable — target ≤ ~1600px on the long edge.

Resize + base64 in one Python call (avoids brittle shell pipe chains and command substitution):

```bash
python3 - <<'PY'
from PIL import Image
import base64, io, pathlib
SRC = "/abs/path/screenshot.png"
img = Image.open(SRC).convert("RGB")
img.thumbnail((1600, 1600))
buf = io.BytesIO(); img.save(buf, format="JPEG", quality=82)
b64 = base64.b64encode(buf.getvalue()).decode()
pathlib.Path("/abs/path/tmp/shot.b64").write_text("data:image/jpeg;base64," + b64)
print("wrote", len(b64), "chars")
PY
```

Then inject the `.b64` contents into the HTML `src` (read the file, string-replace a placeholder). Keep the resize/base64 temp files in a scratch dir, not the repo. (`PIL` = the Pillow package: `pip install Pillow`.)

### 4. Verify self-containment (BLOCKING gate)

Before opening/committing, confirm zero external references:

```bash
grep -oE 'src="[^"]*"|href="[^"]*"|@import|url\(https?' <file.html> | grep -vE 'data:|#' | head
```

Empty output = self-contained. Any hit = fix it (inline the asset) before proceeding.

### 5. Open + record

```bash
open <abs-path-to-html>       # macOS
# xdg-open <abs-path-to-html> # Linux
```

Tell the user the path + the re-open command. Commit the file (it's a durable doc artifact).

## Screenshot presentation defaults

Real device/app screenshots are the point of a wrap-up gallery — size them so they read, don't cram them into a thumbnail.

- **Give the shot real room.** A portrait phone screenshot capped at ~224px in a 280px column renders as a thin sliver. Use a wider media column (~360px) and let the image scale to ~`max-width:300px; max-height:600px; object-fit:contain` so phone and tablet shots stay consistent.
- **Frame it like a device.** A few px of dark padding + `border-radius` reads as a bezel and separates the screenshot from the card background.
- **Tap-to-zoom.** Screenshots carry detail worth inspecting (scaling, clipping). Make them clickable to open full-size — a tiny inline `<script>` that opens `img.src` in a new window (don't wrap in `<a href>` — that duplicates the huge data URI).
- **Emit a proper standalone document.** Write a real `<!doctype html><html><head>…</head><body>…</body></html>` with `<meta charset>` + `<meta viewport>` + `<title>` — not a bare fragment.

## Design craft

If a built-in design skill is loaded in step 1 it carries the full guidance; the load-bearing bits for these pages:

- **Calibrate treatment.** A wrap-up/status board is utilitarian-polished, not an editorial hero: real typographic hierarchy, considered spacing, a chosen (not defaulted) neutral palette. Don't over-design.
- **Honesty is the whole point** for a decision gallery. Real screenshots, one card per shipped unit, a clear **needs-your-eyes vs done** split. Say plainly what's unverified.
- **Inline the type.** Don't link a webfont URL and risk a silent fallback — inline a `@font-face` data URI, or use a considered system-font stack.
- **Structure encodes truth.** Numbered markers only for real sequences; state pills (merged / parked / needs-review) for status. Semantic color (good/warn/critical) separate from accent.
- **Build cleanly.** Wide content (tables, screenshots) gets its own `overflow-x: auto`; the body never scrolls sideways. Respect `prefers-reduced-motion`. Give images `max-width: 100%`.

## Anti-patterns this skill prevents

| Anti-pattern | Why it's wrong | Fix |
|---|---|---|
| Calling a hosted Artifact tool for an internal page | Publishes to a vendor's servers; off-device | Use this skill — write to disk |
| `src="./shot.png"` relative link | File breaks when moved/committed; not portable | Embed as `data:` URI |
| Hand-drawn placeholder resembling the real feature | Diverges from what was signed off; misleads | Real screenshot or omit + say so |
| Multi-MB raw PNGs inline | Bloats the committed file | Resize to ≤1600px, JPEG q≈82 |
| Leaving it only in a scratch dir | Throwaway; lost on session end | Save to a docs dir, commit |

## Adapting this skill to your setup

- **Default output folder** — this skill writes to a docs directory (author's default `docs/session/`); change the default in §Output contract to wherever your repo keeps durable docs.
- **Install location** — drop this folder at `.claude/skills/local-artifact/` in a project, or in your user-level skills dir to load it in every session.
- **Design skill** — the step-1 `artifact-design` call is optional; if your harness has no such skill, the §Design craft notes stand alone.
- **No hard dependency** beyond Python + Pillow (for the image resize/embed) and a shell to open a file.
- **Tool use is narrow.** `Bash` is used for exactly three things — the Python image-embed (§3), the self-containment `grep` gate (§4), and opening the finished file (§5). No network calls; the whole point is that nothing leaves your disk.
