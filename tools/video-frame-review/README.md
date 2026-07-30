# video-frame-review

Turn a video into sampled JPEG frames plus **labelled contact sheets**, so an AI
agent can inspect a recording without playing it back.

The sheets are the point. Frames get tiled onto a grid with the wall-clock
timestamp burned into each tile, so **one image covers 36 seconds** instead of
one image per moment. An agent reading a sheet can tell you the button goes grey
at 00:22. It has the timeline, not just a still.

## Why this exists

It started as a game-art problem. I was building a small 2D platformer and kept
hitting the same wall: I could *see* that a jump felt wrong, but I could not hand
that to an agent. Video is the honest record of how something moves, and the
agent I was working with could not open one. So the conversation degenerated into
me exporting stills one at a time and describing what happened between them.

The first version just dumped frames to PNGs. It helped, but reviewing a clip
still cost one image read per frame, and every frame arrived with no idea *when*
it was. That is exactly the information you need when the bug is "it stutters
about a third of the way in."

Tiling the frames and printing the timestamp on each one fixed both at once.

That game did not end up continuing. The tool outlived it, because the underlying
problem was not specific to games: **any time the evidence is a recording and
your agent cannot take it in that form, you are stuck narrating it.** Screen
recordings of a bug, a simulator capture, an animation review, a clip someone
sent you, a YouTube talk or tutorial you want an agent to go through with you.
Same fix every time.

Agent video support varies by vendor and keeps moving, so this is not a claim
about what any particular model can do. Frames on a labelled grid work
everywhere, which is the point: it is one image read, in a format nothing has
trouble with.

## Prerequisites

Two things: **Python 3.9+** and **`ffmpeg`**. Check what you already have:

```bash
python3 --version
ffmpeg -version
```

If `ffmpeg -version` prints a version, you are done. If it prints
`command not found`, install it:

```bash
# macOS (Homebrew)
brew install ffmpeg

# Debian / Ubuntu
sudo apt update && sudo apt install ffmpeg

# Fedora
sudo dnf install ffmpeg

# Windows (winget, in PowerShell)
winget install Gyan.FFmpeg
```

`ffprobe` ships with `ffmpeg`, so the same install covers both. It is optional
anyway: it only prints an estimated frame count before the run starts.

### If ffmpeg is installed but "not found"

That means it is on disk but not on your `PATH`, so the shell cannot see it.
Find it, then add the folder that contains it:

```bash
# macOS / Linux: locate the binary
ls /opt/homebrew/bin/ffmpeg /usr/local/bin/ffmpeg /usr/bin/ffmpeg 2>/dev/null
```

Add that folder to your shell profile (`~/.zshrc` for zsh, the macOS default;
`~/.bashrc` for bash), then reload:

```bash
echo 'export PATH="/opt/homebrew/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
ffmpeg -version    # should print a version now
```

On Windows, search "Edit the system environment variables" → Environment
Variables → select `Path` → Edit → New → paste the folder holding `ffmpeg.exe`,
then open a **new** terminal.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

That installs Pillow, the only Python dependency. Run the tool with the venv's
interpreter (`.venv/bin/python3`) so it can see it:

```bash
.venv/bin/python3 video_frame_review.py "recording.mp4"
```

The examples below say `python3` for brevity. If you did not use a venv and get
`ModuleNotFoundError: No module named 'PIL'`, run `python3 -m pip install Pillow`.

## Usage

```bash
python3 video_frame_review.py "recording.mp4"
```

Output goes to a sibling folder named after the video:

```text
recording_review_1p0fps/
  frames/     frame_0001.jpg, frame_0002.jpg, ...
  sheets/     sheet_0001_0036.jpg, sheet_0037_0072.jpg, ...
```

Hand the agent the **sheets**. Reach for individual `frames/` only when you need
one moment at full resolution.

There is no format restriction. The input goes straight to `ffmpeg -i`, so
`.mov`, `.mp4`, `.m4v`, `.webm`, `.mkv`, `.avi`, `.gif` and PNG sequences all
work.

## A YouTube video you want an agent to go through with you

Common case: a talk, tutorial, or conference recording you would rather have an
agent walk you through than sit through. It takes a **local file**, so download
first with [`yt-dlp`](https://github.com/yt-dlp/yt-dlp), then sheet it:

```bash
brew install yt-dlp                      # or: pipx install yt-dlp
yt-dlp -f mp4 -o talk.mp4 "<video url>"
python3 video_frame_review.py talk.mp4 --fps 0.2
```

**Turn the frame rate down for anything long.** At the default 1 fps a 40-minute
talk is 2,400 frames and 67 sheets, which is worse than the problem. `--fps 0.2`
is one frame every 5 seconds, so 3 minutes of video lands on a single sheet:

```text
talk.mp4: 180.0s, extracting about 36 frames
frames: 36 -> talk_review_0p2fps/frames
sheets: 1 -> talk_review_0p2fps/sheets  (tile 280x186)
```

Timestamps switch to `mm:ss` past the first minute, so an agent can tell you the
architecture diagram is up at `01:35` and you can jump straight there.

Slides, terminals and diagrams are where this pays off most, and they are also
where text is smallest. If labels come out too fine to read, give the tiles more
room with `--columns 4 --rows 3`. What it will **not** do is capture speech, so
pair the sheets with the transcript (`yt-dlp --write-auto-subs --skip-download`)
when the words matter as much as what is on screen.

## Worked example

A 6.5-second clip of a walk cycle from that platformer. The exact kind of thing
that is impossible to describe in words and obvious in a grid.

```bash
python3 video_frame_review.py walkcycle.mp4 --fps 4
```

```text
walkcycle.mp4: 6.5s, extracting about 26 frames
frames: 26 -> walkcycle_review_4p0fps/frames
sheets: 1 -> walkcycle_review_4p0fps/sheets  (tile 280x186)
walkcycle_review_4p0fps/sheets/sheet_0001_0026.jpg
```

That one sheet is the whole clip:

![Contact sheet: 26 frames of a walk cycle, each labelled with its timestamp](example-sheet.jpg)

Now paste that single image into your agent and ask a real question. Because the
timestamps sit on the tiles, the answers come back anchored to the clip: you can
see the character cross the scene left to right, watch the background scroll with
it, and point at the exact tile where the stride stops looking right. Getting to
that same observation used to mean 26 separate image pastes and me narrating the
gaps between them.

Note the tiles are landscape here because the footage is. Feed it a phone
recording and they come out portrait, no flags needed.

## Already have the stills?

Point it at a **directory** instead of a video and it sheets what's on disk, no
ffmpeg needed:

```bash
python3 video_frame_review.py ./screenshots/
```

Tiles get labelled with filenames rather than timestamps, since a folder has no
timeline. Useful for a batch of generated images, a screenshot run, or frames
some other tool already exported. Same reason as the video case: a folder of 40
images costs 40 image reads until they're on one grid.

### Useful options

```bash
python3 video_frame_review.py input.mp4 --fps 2 --max-frames 120
python3 video_frame_review.py input.mp4 --out-dir review --columns 5 --rows 5
python3 video_frame_review.py input.mp4 --width 720 --tile-width 320
python3 video_frame_review.py input.mp4 --gif        # also write a shareable GIF
```

- `--fps` (default `1`): samples per second. Raise it for motion detail; timestamps
  gain tenths automatically above 1 fps. This is the knob you'll actually tune.
- `--max-frames`: stop early. Worth setting on a long recording before you find out
  how many sheets it wanted to write.
- `--columns` / `--rows` (default `6`x`6`): tiles per sheet. Fewer, larger tiles read
  more clearly if the detail you care about is small text.
- `--tile-height`: normally leave it alone. Tile height follows the footage's own
  aspect ratio, so portrait and landscape both fill their tiles.
- `--gif`: animated GIF alongside the frames, for a devlog or a message thread.

## Notes

- **A short final sheet is trimmed to the rows it fills.** Blank rows are not free:
  most agents downscale a large image before reading it, so empty space costs you
  the resolution you wanted spent on pixels.
- **36 tiles per sheet stays legible** after that downscale, including burned-in
  video captions. Verified, not assumed. If your subject is finer than that (small
  UI labels, code in a screen recording), drop to `--columns 4 --rows 3`.
- **1 fps is a deliberate default.** Most review questions are "what changed and
  roughly when", and one frame per second answers that at a thirtieth of the frames.
  Motion questions ("does this loop cleanly?") want `--fps 4` or higher.
- Frames are JPEG, so a two-minute recording costs a few MB rather than hundreds.

MIT. Adapt freely.
