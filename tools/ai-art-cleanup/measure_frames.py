#!/usr/bin/env python3
"""Measure per-frame position + size of an animation, to detect drift.

For each PNG in a directory it prints the colour-mass bounding box, the centroid
(alpha-weighted-ish), and the fully-transparent %, then summarises the centroid
DRIFT and the height range. Use it to confirm an exported walk/idle cycle stays in
place (centroid drift ≈ 0) — or to see how far it drifts before fixing it with
`align_walk.py`.

The character body is detected by SATURATION (colourful pixels), which ignores both
a white background and a grey drop-shadow.

Usage:
  measure_frames.py <frames_dir> [--sat 35] [--alpha 24]
"""
import argparse, glob, os
import numpy as np
from PIL import Image


def main():
    ap = argparse.ArgumentParser(description="Report per-frame bbox/centroid/drift for an animation.")
    ap.add_argument("dir", help="directory of PNG frames")
    ap.add_argument("--sat", type=int, default=35, help="min saturation to count as character (default 35)")
    ap.add_argument("--alpha", type=int, default=24, help="min alpha to count a pixel (default 24)")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.dir, "*.png")))
    if not files:
        raise SystemExit(f"no PNG frames in {args.dir}")

    hdr = f"{'frame':>10} {'x0':>4} {'x1':>4} {'y0':>4} {'y1':>4} {'w':>4} {'h':>4} {'cx':>5} {'cy':>5} {'cxw':>6} {'transp%':>8}"
    print(hdr)
    rows = []
    for f in files:
        arr = np.array(Image.open(f).convert("RGBA")).astype(int)
        r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
        sat = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
        mask = (a > args.alpha) & (sat > args.sat)
        ys, xs = np.where(mask)
        if len(xs) == 0:
            continue
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        cxw = xs.mean()
        transp = 100.0 * (a == 0).sum() / a.size
        rows.append((x1 - x0, y1 - y0, cxw, y1))
        print(f"{os.path.basename(f):>10} {x0:4d} {x1:4d} {y0:4d} {y1:4d} "
              f"{x1-x0:4d} {y1-y0:4d} {(x0+x1)//2:5d} {(y0+y1)//2:5d} {cxw:6.1f} {transp:7.1f}")
    if rows:
        cxw = [r[2] for r in rows]; hs = [r[1] for r in rows]
        print(f"\ncentroid x: min {min(cxw):.0f} max {max(cxw):.0f}  DRIFT {max(cxw)-min(cxw):.0f}px")
        print(f"height:     min {min(hs):.0f} max {max(hs):.0f}  range {max(hs)-min(hs):.0f}px")


if __name__ == "__main__":
    main()
