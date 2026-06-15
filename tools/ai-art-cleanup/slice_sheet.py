#!/usr/bin/env python3
"""Slice a transparent sprite sheet into individual asset PNGs.

Finds connected clusters of non-transparent pixels (with a dilation pass so
near-touching pieces like rope-bridge segments stay together), crops each to
its own PNG, and writes an index.html gallery for review.

Usage:
  slice_sheet.py input.png output_dir [--dilate 6] [--min-size 12] [--pad 4]
"""
import argparse, sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("outdir")
    ap.add_argument("--dilate", type=int, default=6,
                    help="merge pieces closer than ~this many px")
    ap.add_argument("--min-size", type=int, default=12,
                    help="drop blobs smaller than this in both dimensions")
    ap.add_argument("--pad", type=int, default=4, help="padding around each crop")
    ap.add_argument("--alpha-thresh", type=int, default=8)
    args = ap.parse_args()

    img = Image.open(args.input).convert("RGBA")
    rgba = np.asarray(img)
    h, w = rgba.shape[:2]
    mask = rgba[:, :, 3] > args.alpha_thresh
    if not mask.any():
        sys.exit("No non-transparent pixels found — is this a real-alpha sheet?")

    merged = ndimage.binary_dilation(mask, iterations=args.dilate)
    labels, n = ndimage.label(merged, structure=np.ones((3, 3)))
    print(f"{Path(args.input).name}: {w}x{h}, {n} raw blobs")

    boxes = []
    for sl in ndimage.find_objects(labels):
        if sl is None:
            continue
        sub = mask[sl]
        if not sub.any():
            continue
        ys, xs = np.where(sub)
        y0 = sl[0].start + ys.min(); y1 = sl[0].start + ys.max() + 1
        x0 = sl[1].start + xs.min(); x1 = sl[1].start + xs.max() + 1
        bw, bh = x1 - x0, y1 - y0
        if bw < args.min_size and bh < args.min_size:
            continue
        boxes.append((x0, y0, x1, y1))

    # reading order: row bands (by y center, banded), then x
    boxes.sort(key=lambda b: ((b[1] + b[3]) // 2 // 120, b[0]))

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.input).stem.replace("_transparent", "")
    rows_html = []
    for i, (x0, y0, x1, y1) in enumerate(boxes, 1):
        px0 = max(0, x0 - args.pad); py0 = max(0, y0 - args.pad)
        px1 = min(w, x1 + args.pad); py1 = min(h, y1 + args.pad)
        crop = img.crop((px0, py0, px1, py1))
        name = f"{stem}_{i:03d}.png"
        crop.save(outdir / name)
        rows_html.append(
            f'<figure><img src="{name}" loading="lazy">'
            f'<figcaption>{name}<br>{px1-px0}x{py1-py0}</figcaption></figure>')

    gallery = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{stem} — {len(boxes)} assets</title><style>
body{{background:#241c4a;color:#eee;font-family:sans-serif;padding:16px}}
main{{display:flex;flex-wrap:wrap;gap:12px}}
figure{{margin:0;background:#3b2a6e;border-radius:8px;padding:10px;text-align:center}}
img{{max-width:220px;max-height:160px;image-rendering:pixelated;
background:repeating-conic-gradient(#444 0% 25%, #555 0% 50%) 0 0/16px 16px}}
figcaption{{font-size:11px;margin-top:6px;color:#cdb9e8}}
</style></head><body><h2>{stem} — {len(boxes)} assets</h2><main>
{''.join(rows_html)}
</main></body></html>"""
    (outdir / "index.html").write_text(gallery)
    print(f"wrote {len(boxes)} assets + index.html -> {outdir}")


if __name__ == "__main__":
    main()
