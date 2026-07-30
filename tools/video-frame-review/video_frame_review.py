#!/usr/bin/env python3
"""Slice a video into review frames and labelled contact sheets.

Lets an agent "watch" a recording: sampled frames are tiled onto sheets with a
timestamp burned into each tile, so one image read covers dozens of seconds.

Requires ffmpeg on PATH (ffprobe optional) and Pillow. MIT licensed.
"""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LABEL_BAND = 30
TILE_PAD = 10


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"Missing required command: {name}")


def run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        rendered = " ".join(command)
        raise SystemExit(f"Command failed: {rendered}") from exc


def probe_duration(video: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def extract_frames(
    video: Path,
    frames_dir: Path,
    fps: float,
    image_width: int,
    max_frames: int | None,
    overwrite: bool,
) -> list[Path]:
    if frames_dir.exists() and overwrite:
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)

    output_pattern = frames_dir / "frame_%04d.jpg"
    vf = f"fps={fps},scale={image_width}:-1"
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video),
        "-vf",
        vf,
    ]
    if max_frames is not None:
        command.extend(["-frames:v", str(max_frames)])
    command.append(str(output_pattern))
    run(command)

    frames = sorted(frames_dir.glob("frame_*.jpg"))
    if not frames:
        raise SystemExit(f"No frames were written to {frames_dir}")
    return frames


def write_gif(video: Path, gif_path: Path, image_width: int, fps: float) -> None:
    """Animated GIF alongside the frames, for devlogs and sharing."""
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-vf",
            f"fps={fps},scale={image_width}:-1:flags=lanczos",
            str(gif_path),
        ]
    )


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def collect_images(folder: Path) -> list[Path]:
    """Sheet a folder of stills instead of sampling a video.

    The same review problem one step earlier: a directory of generated frames or
    screenshots costs one image read each until they are on a single grid. Tiles
    get labelled with filenames, since there is no timeline to stamp.
    """
    images = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        raise SystemExit(f"No images found in {folder}")
    return images


def timestamp_label(index: int, fps: float) -> str:
    """Wall-clock position of a frame. Tenths shown only when sampling above 1 fps."""
    seconds = (index - 1) / fps
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    decimals = 1 if fps > 1 else 0
    if minutes:
        width = 4 if decimals else 2
        return f"{minutes:02d}:{remainder:0{width}.{decimals}f}"
    return f"{remainder:.{decimals}f}s"


def tile_size(frame: Path, tile_width: int, tile_height: int | None) -> tuple[int, int]:
    """Derive tile height from the frame's own aspect unless it was given.

    Fixed portrait-shaped tiles leave a landscape clip as a stamp in a sea of
    white space, so the default follows the footage instead of assuming 9:16.
    """
    if tile_height is not None:
        return tile_width, tile_height
    with Image.open(frame) as probe:
        width, height = probe.size
    content_width = tile_width - 2 * TILE_PAD
    content_height = max(1, round(content_width * height / width))
    return tile_width, LABEL_BAND + content_height + TILE_PAD


def load_label_font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow older than 10.1
        return ImageFont.load_default()


def build_sheets(
    frames: list[Path],
    sheets_dir: Path,
    fps: float | None,
    columns: int,
    rows: int,
    tile_width: int,
    tile_height: int,
    quality: int,
    overwrite: bool,
) -> list[Path]:
    if sheets_dir.exists() and overwrite:
        shutil.rmtree(sheets_dir)
    sheets_dir.mkdir(parents=True, exist_ok=True)

    font = load_label_font(16)
    per_sheet = columns * rows
    written: list[Path] = []

    for batch_start in range(0, len(frames), per_sheet):
        batch = frames[batch_start : batch_start + per_sheet]
        # Trim to the rows actually filled: blank rows on a short final sheet
        # only waste pixels, and pixels are the budget a reader downscales into.
        rows_used = math.ceil(len(batch) / columns)
        sheet = Image.new("RGB", (columns * tile_width, rows_used * tile_height), "white")
        for offset, frame_path in enumerate(batch):
            index = batch_start + offset + 1
            image = Image.open(frame_path).convert("RGB")
            image.thumbnail(
                (tile_width - 2 * TILE_PAD, tile_height - LABEL_BAND - TILE_PAD)
            )
            tile = Image.new("RGB", (tile_width, tile_height), "white")
            draw = ImageDraw.Draw(tile)
            # No fps means these are stills off disk: label with the filename,
            # which is the only handle a reader has to point back at one.
            label = timestamp_label(index, fps) if fps else frame_path.stem[-18:]
            draw.text((8, 6), label, fill=(0, 0, 0), font=font)
            image_x = (tile_width - image.width) // 2
            tile.paste(image, (image_x, LABEL_BAND))
            sheet_x = (offset % columns) * tile_width
            sheet_y = (offset // columns) * tile_height
            sheet.paste(tile, (sheet_x, sheet_y))

        first = batch_start + 1
        last = batch_start + len(batch)
        output = sheets_dir / f"sheet_{first:04d}_{last:04d}.jpg"
        sheet.save(output, quality=quality)
        written.append(output)

    return written


def default_output_dir(video: Path, fps: float) -> Path:
    safe_fps = str(fps).replace(".", "p")
    return video.with_name(f"{video.stem}_review_{safe_fps}fps")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract sampled video frames and make labelled contact sheets."
    )
    parser.add_argument(
        "video",
        type=Path,
        help="Input video (any format ffmpeg reads), OR a directory of stills to sheet as-is",
    )
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        help="Output directory. Defaults to <input>_review_<fps>fps (or <dir>_sheets)",
    )
    parser.add_argument("--fps", type=positive_float, default=1.0, help="Frames per second")
    parser.add_argument("--width", type=positive_int, default=590, help="Extracted frame width")
    parser.add_argument("--columns", type=positive_int, default=6, help="Sheet columns")
    parser.add_argument("--rows", type=positive_int, default=6, help="Sheet rows")
    parser.add_argument("--tile-width", type=positive_int, default=280, help="Sheet tile width")
    parser.add_argument(
        "--tile-height",
        type=positive_int,
        help="Sheet tile height. Defaults to the footage's own aspect ratio",
    )
    parser.add_argument("--quality", type=positive_int, default=90, help="JPEG quality")
    parser.add_argument("--max-frames", type=positive_int, help="Stop after this many frames")
    parser.add_argument(
        "--gif",
        action="store_true",
        help="Also write an animated GIF (12 fps) next to the frames",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Do not remove existing frames/sheets directories first",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    source = args.video.expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"Input not found: {source}")

    stills_mode = source.is_dir()
    if not stills_mode:
        require_tool("ffmpeg")

    if args.out_dir:
        out_dir = args.out_dir.expanduser().resolve()
    elif stills_mode:
        out_dir = source.with_name(f"{source.name}_sheets")
    else:
        out_dir = default_output_dir(source, args.fps)
    frames_dir = out_dir / "frames"
    sheets_dir = out_dir / "sheets"
    overwrite = not args.keep_existing

    if stills_mode:
        frames = collect_images(source)
        if args.max_frames is not None:
            frames = frames[: args.max_frames]
        sheet_fps = None
        print(f"{source.name}/: sheeting {len(frames)} stills already on disk")
    else:
        sheet_fps = args.fps
        duration = probe_duration(source)
        if duration is not None and args.max_frames is None:
            estimated = math.ceil(duration * args.fps)
            print(f"{source.name}: {duration:.1f}s, extracting about {estimated} frames")
        else:
            print(f"{source.name}: extracting frames")
        frames = extract_frames(
            source, frames_dir, args.fps, args.width, args.max_frames, overwrite
        )

    tile_width, tile_height = tile_size(frames[0], args.tile_width, args.tile_height)
    sheets = build_sheets(
        frames,
        sheets_dir,
        sheet_fps,
        args.columns,
        args.rows,
        tile_width,
        tile_height,
        args.quality,
        overwrite,
    )

    if stills_mode:
        print(f"stills: {len(frames)} read from {source}")
    else:
        print(f"frames: {len(frames)} -> {frames_dir}")
    print(f"sheets: {len(sheets)} -> {sheets_dir}  (tile {tile_width}x{tile_height})")
    for sheet in sheets:
        print(sheet)

    if args.gif:
        if stills_mode:
            print("note: --gif needs a video input; skipped for a stills directory")
        else:
            gif_path = out_dir / f"{source.stem}.gif"
            write_gif(source, gif_path, args.width, 12)
            print(f"gif -> {gif_path}")


if __name__ == "__main__":
    main()
