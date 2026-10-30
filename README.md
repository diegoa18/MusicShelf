# MusicShelf

Build and organize your local music library from supported streaming music providers.

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

### Options

| Flag | Description |
|------|-------------|
| `-f`, `--format` | Output format: `flac`, `mp3`, `opus`, `wav`, `m4a`, `ogg` (default: `m4a`) |
| `-d`, `--directory` | Output directory for organized library (default: current directory) |
| `--dry-run` | Preview changes without downloading or modifying files |
| `--overwrite` | Force overwrite of existing files (existing files are skipped by default) |
| `--audit` | Audit the current library for misplaced, corrupted, or tagless files |

### Examples

```bash
uv run musicshelf "https://music.youtube.com/watch?v=..." -f flac
uv run musicshelf --audit -d ~/Music
```

## Supported Providers & URLs

- **YouTube Music**: 
  - Songs: `music.youtube.com/watch?v=...`
  - Albums: `music.youtube.com/playlist?list=OLAK5uy_...`
  *(User playlists and channels are not supported)*.

- **SoundCloud**:
  - Tracks: `soundcloud.com/artist/track`
  - Sets/Albums: `soundcloud.com/artist/sets/...`

- **Bandcamp**:
  - Tracks: `artist.bandcamp.com/track/...`
  - Albums: `artist.bandcamp.com/album/...`

- **Spotify (Hybrid)**:
  - Tracks: `open.spotify.com/track/...`
  - Albums: `open.spotify.com/album/...`
