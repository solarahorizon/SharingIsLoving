#!/usr/bin/env python3
"""Composite several images side-by-side into one comparison strip.

Each input is scaled to a common height and laid out left-to-right with a gap —
handy for "generated vs. reference" or before/after comparisons in one glance.
(For grid/tile layouts, ImageMagick's `magick montage` is the heavier-duty option;
this is a zero-config one-liner.)

Usage:
  montage.py a.png b.png c.png out.png [--height 720] [--gap 16] [--bg 20,16,34]
"""
import argparse
from PIL import Image


def main():
    ap = argparse.ArgumentParser(description="Tile images side-by-side at equal height.")
    ap.add_argument("images", nargs="+", help="input images, then the output path last")
    ap.add_argument("--height", type=int, default=720, help="row height in px (default 720)")
    ap.add_argument("--gap", type=int, default=16, help="gap between images in px")
    ap.add_argument("--bg", default="20,16,34", help="background 'R,G,B' (default 20,16,34)")
    args = ap.parse_args()

    if len(args.images) < 2:
        ap.error("need at least one input image and an output path")
    *inputs, out_path = args.images
    bg = tuple(int(c) for c in args.bg.split(","))

    scaled = []
    for p in inputs:
        im = Image.open(p).convert("RGB")
        w = max(1, int(im.width * args.height / im.height))
        scaled.append(im.resize((w, args.height)))

    total_w = sum(s.width for s in scaled) + args.gap * (len(scaled) - 1)
    out = Image.new("RGB", (total_w, args.height), bg)
    x = 0
    for s in scaled:
        out.paste(s, (x, 0))
        x += s.width + args.gap
    out.save(out_path)
    print(f"wrote {out_path}  {out.size}  ({len(scaled)} images)")


if __name__ == "__main__":
    main()
