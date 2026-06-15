# ai-art-cleanup

Small, single-purpose Python tools for turning **AI-generated / exported art into game-ready
sprites**. These solve the unglamorous problems you hit the moment you try to *use* generated
art in an actual 2D game — drift, baked-in backgrounds, sprite sheets, and "is this animation
actually looping?" — that image editors and prompt tricks don't fix cleanly.

Earned in production on a chibi-platformer art pipeline (generate → clean → slice → use).

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

All tools take real CLI args; run any with `--help`.

## Tools

### `align_walk.py` — de-drift a looping animation + knock out its white background
The standout. AI tools love to author a walk/idle cycle that **drifts across the frame** (so the
loop visibly jerks back on repeat) on an **opaque white background**. This:
1. **De-drifts** — re-anchors every frame to a constant colour-mass *centroid* so the body stays
   put while the legs move (a true in-place loop). Smooth because the centroid drift is monotonic.
2. **Removes the white background → alpha 0** by flood-filling from the *borders* — so interior
   whites (eyes, teeth, glints) survive instead of getting punched into holes. Keeps only the
   largest blob to drop stray specks.
3. **Common-crops** all frames to one box → identical size + anchor, drop-in sprite frames.

```bash
.venv/bin/python align_walk.py frames_in/ frames_out/        # de-drift X only (keeps vertical bob)
.venv/bin/python align_walk.py frames_in/ frames_out/ --axis xy --white 232
```

### `measure_frames.py` — detect / quantify animation drift
Prints each frame's bbox + centroid + transparent-%, then the **centroid drift** and height range.
Run it before (see the drift) and after `align_walk` (drift ≈ 0) to verify.

```bash
.venv/bin/python measure_frames.py frames_out/
```

### `slice_sheet.py` — sprite sheet → individual PNGs + a review gallery
Finds connected clusters of non-transparent pixels (with a dilation pass so near-touching pieces
stay together), crops each to its own PNG, and writes an `index.html` contact gallery.

```bash
.venv/bin/python slice_sheet.py sheet_transparent.png out_dir/ [--dilate 6] [--min-size 12]
```

### `montage.py` — side-by-side comparison strip
Scales inputs to a common height and lays them out left-to-right. For quick "generated vs.
reference" or before/after comparisons. (For tiled grids, ImageMagick's `magick montage` is the
heavier tool; this is the zero-config one-liner.)

```bash
.venv/bin/python montage.py generated.png reference.png out.png [--height 720] [--gap 16]
```

## Notes
- `align_walk` / `measure_frames` detect the character by **saturation**, which ignores both a
  white background and a grey drop-shadow — no chroma-key colour needed.
- Output is real-alpha PNG; if your engine already keys white at load, the transparency is a bonus.
- MIT — adapt freely.
