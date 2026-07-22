# MusicShelf

Build and organize your local music library from YouTube Music.

## Requirements

- Python >= 3.13
- [uv](https://docs.astral.sh/uv/)
- [FFmpeg](https://ffmpeg.org/) (in PATH)

## Install

```bash
git clone <repo-url>
cd MusicShelf
uv sync
```

## Usage

```bash
uv run musicshelf <URL> [OPTIONS]
```

> `uv run` requires you to be inside the project directory.

### Options

| Flag | Description |
|------|-------------|
| `-f`, `--format` | Output format: `flac`, `mp3`, `opus`, `wav`, `m4a`, `ogg` |
| `-d`, `--directory` | Output directory (default: current directory) |

### Examples

```bash
# Single song
uv run musicshelf "https://music.youtube.com/watch?v=..." -f flac

# Song organized in directory
uv run musicshelf "https://music.youtube.com/watch?v=..." -f mp3 -d ~/Music

# Full album
uv run musicshelf "https://music.youtube.com/playlist?list=OLAK5uy_..." -f flac -d ~/Music
```

## Install globally

To run `musicshelf` from any directory without `uv run`:

```bash
uv pip install .
musicshelf "URL" -f flac -d ~/Music
```

> Use `uv pip install .` (not `-e .`) so the package is self-contained and independent of the project directory.

## Supported URLs

- Songs: `music.youtube.com/watch?v=...`
- Albums: `music.youtube.com/playlist?list=OLAK5uy_...`

User playlists and channels are not supported.
