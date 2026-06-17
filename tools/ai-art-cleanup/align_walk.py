#!/usr/bin/env python3
"""Fix an exported / AI-generated looping animation (walk, idle, …) for a 2D game:
  1. DE-DRIFT — generators often author the character drifting across the frame, so the loop
     jerks back on repeat. Re-anchor every frame to a constant colour-mass centroid X (a clean
     in-place cycle that loops seamlessly).
  2. KNOCK OUT THE WHITE BACKGROUND -> alpha 0, via flood-fill from the borders so interior
     white highlights (eyes, teeth, fur glints) are preserved (not punched into holes).
  3. COMMON-CROP all frames to one box so they share size + anchor — drop-in sprite frames.
Outputs transparent, aligned RGBA frames. Horizontal de-drift only — natural vertical bob kept.

Usage: align_walk.py <src_dir> <dst_dir> [--axis x|xy] [--white 232]
"""
import sys, glob, os, argparse
import numpy as np
from PIL import Image
from scipy import ndimage

ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("dst")
ap.add_argument("--axis", default="x", choices=["x", "xy"])
ap.add_argument("--white", type=int, default=232, help="min RGB channel to count as background white")
args = ap.parse_args()
os.makedirs(args.dst, exist_ok=True)
files = sorted(glob.glob(os.path.join(args.src, "*.png")))
if not files:
    sys.exit(f"align_walk: no PNG frames found in {args.src}")

def centroid(arr):
    r, g, b, a = arr[:,:,0].astype(int), arr[:,:,1].astype(int), arr[:,:,2].astype(int), arr[:,:,3]
    sat = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    mask = (a > 24) & (sat > 35)                      # colourful character body
    ys, xs = np.where(mask)
    if len(xs) == 0:                                  # blank / fully-desaturated frame
        return arr.shape[1] / 2.0, arr.shape[0] / 2.0  # fall back to image centre (no NaN)
    return xs.mean(), ys.mean()

def knockout_white(arr):
    """Set border-connected near-white pixels to alpha 0; keep interior whites opaque."""
    r, g, b = arr[:,:,0], arr[:,:,1], arr[:,:,2]
    near_white = np.minimum(np.minimum(r, g), b) > args.white
    lbl, _ = ndimage.label(near_white)
    border = np.unique(np.concatenate([lbl[0,:], lbl[-1,:], lbl[:,0], lbl[:,-1]]))
    border = border[border != 0]
    bg = np.isin(lbl, border)
    out = arr.copy()
    out[bg, 3] = 0
    # 1px feather: soften the alpha just inside the cut so there's no hard white fringe
    opaque = out[:,:,3] > 0
    edge = opaque & ndimage.binary_dilation(bg) & (np.minimum(np.minimum(r, g), b) > args.white - 24)
    out[edge, 3] = 120
    # keep ONLY the largest opaque blob (the character) — drops stray edge specks/noise so
    # the game's alpha-bbox auto-crop locks onto the character, not scattered pixels
    solid = out[:,:,3] > 30
    lbl2, n2 = ndimage.label(solid)
    if n2 > 1:
        sizes = ndimage.sum(np.ones_like(lbl2), lbl2, index=range(1, n2 + 1))
        keep = int(np.argmax(sizes)) + 1
        out[(lbl2 != keep) & (lbl2 != 0), 3] = 0
    return out

cents = [centroid(np.array(Image.open(f).convert("RGBA")).astype(int)) for f in files]
cxs = np.array([c[0] for c in cents]); cys = np.array([c[1] for c in cents])
tx, ty = cxs.mean(), cys.mean()
maxdx = 0
frames = []                                           # (name, aligned RGBA array)
for f, (cx, cy) in zip(files, cents):
    arr = knockout_white(np.array(Image.open(f).convert("RGBA")))
    src = Image.fromarray(arr, "RGBA")
    dx = int(round(tx - cx)); dy = int(round(ty - cy)) if args.axis == "xy" else 0
    maxdx = max(maxdx, abs(dx))
    canvas = Image.new("RGBA", src.size, (0, 0, 0, 0))
    canvas.paste(src, (dx, dy), src)                  # shift onto transparent canvas
    frames.append((os.path.basename(f), np.array(canvas)))

# common crop: ONE box (union of every frame's alpha) so all frames share size + anchor →
# drop-in animation, identical placement, the loop can't drift no matter how it's drawn.
PAD = 8
ux0, uy0, ux1, uy1 = 1e9, 1e9, 0, 0
for _, a in frames:
    ys, xs = np.where(a[:, :, 3] > 20)
    ux0, uy0 = min(ux0, xs.min()), min(uy0, ys.min())
    ux1, uy1 = max(ux1, xs.max()), max(uy1, ys.max())
H, W = frames[0][1].shape[:2]
ux0, uy0 = max(0, ux0 - PAD), max(0, uy0 - PAD)
ux1, uy1 = min(W, ux1 + PAD), min(H, uy1 + PAD)
for name, a in frames:
    Image.fromarray(a[uy0:uy1, ux0:ux1], "RGBA").save(os.path.join(args.dst, name))
print(f"aligned + transparent + common-cropped: {len(files)} frames -> {args.dst}")
print(f"  centroid x target {tx:.1f}  (was {cxs.min():.0f}..{cxs.max():.0f}, drift {cxs.max()-cxs.min():.0f}px -> 0)")
print(f"  common frame size: {ux1-ux0}x{uy1-uy0}  (all frames identical, character anchored)")
print(f"  max shift {maxdx}px ({'safe' if maxdx < 60 else 'CHECK CLIPPING'})")
