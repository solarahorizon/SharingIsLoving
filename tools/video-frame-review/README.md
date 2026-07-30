# video-frame-review

**When the AI agent you're working with can't watch video, this is the tool for
you.** It turns a recording into one image the agent can read: sampled frames
tiled onto a grid, with the timestamp printed on every tile.

So instead of "what do you make of this frame", you can ask "where does the
stride break" and get an answer that points at a time.

![Contact sheet: 26 frames of a walk cycle, each labelled with its timestamp](example-sheet.jpg)

Useful for a bug you can only reproduce in motion, a screen capture, an
animation that reads wrong, or a YouTube talk where the slides are the part you
need. Some models take video directly now. This is for the setups that don't.

## Run it

Needs Python and `ffmpeg`:

```bash
brew install ffmpeg          # macOS. apt/dnf install ffmpeg on Linux, winget install Gyan.FFmpeg on Windows
pip install Pillow
python3 video_frame_review.py your-video.mp4
```

Output lands in `your-video_review_1p0fps/`: the `frames/` it sampled, and the
`sheets/` you hand to the agent.

Any format `ffmpeg` reads works. Point it at a **directory** instead and it
sheets images already on disk, no ffmpeg needed.

## The example above

Both the clip and the sheet are committed here, so you can reproduce it:

```bash
python3 video_frame_review.py example-clip.gif --fps 4
```

This is the input, 6.5 seconds of a walk cycle from a game I never finished:

![The source clip: a character walking left to right across a scrolling scene](example-clip.gif)

That's the problem in one image. You can watch it. The agent couldn't. The sheet
gives up smoothness and gains 26 moments in order, each stamped with when it
happened.

## Options worth knowing

```bash
python3 video_frame_review.py in.mp4 --fps 4              # more detail for motion
python3 video_frame_review.py in.mp4 --fps 0.2            # long talk, one sheet per 3 min
python3 video_frame_review.py in.mp4 --columns 4 --rows 3 # bigger tiles for small text
python3 video_frame_review.py in.mp4 --gif                # also write a shareable GIF
```

`--fps` is the knob you'll actually tune. 1/sec answers "what changed and roughly
when". Raise it for motion, drop it for anything long: a 40 minute talk at 1 fps
is 2,400 frames and 67 sheets. `--help` has the rest (output paths, frame width,
tile sizing, frame caps).

## Two things to know

- **A sheet is a sampled view, not the video.** It gives sequence and timing, not
  what happened between two samples.
- **36 tiles per sheet stays legible** after an agent downscales it, verified not
  assumed. Blank space costs you real resolution, so short sheets get trimmed to
  the rows they fill.

Tiles follow your footage's aspect ratio, so portrait and landscape both fill
properly without flags.

MIT. Adapt freely.
