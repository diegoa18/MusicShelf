from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL

from musicshelf.exceptions import ValidationError
from musicshelf.models import Song
from musicshelf.validators import validate_song_metadata

_YTDLP_OPTIONS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
}

_WATCH_URL = "https://music.youtube.com/watch?v={}"
_SAFE_VIDEO_ID = re.compile(r"^[a-zA-Z0-9_-]{1,20}$")
_SAFE_EXTENSIONS = {"webm", "opus", "m4a", "mp3", "ogg", "flac", "wav", "mkv"}

def _sanitize_video_id(video_id: str | None) -> str | None:
    if not video_id:
        return None
    return video_id if _SAFE_VIDEO_ID.match(video_id) else None

def _sanitize_ext(ext: str | None) -> str:
    if ext and ext.lower() in _SAFE_EXTENSIONS:
        return ext.lower()
    return "webm"

def _extract_info(url: str) -> dict[str, Any]:
    with YoutubeDL(_YTDLP_OPTIONS) as ydl:
        return ydl.extract_info(url, download=False)

def _build_song(info: dict[str, Any], url: str) -> Song:
    return Song(
        title=info.get("track") or info.get("title", "Unknown"),
        artist=info.get("artist") or info.get("uploader", "Unknown"),
        album=info.get("album", "Unknown"),
        video_id=_sanitize_video_id(info.get("id")),
        track=info.get("track_number"),
        year=info.get("release_year"),
        duration=info.get("duration"),
        cover_url=info.get("thumbnail"),
        source_url=url,
    )

def _download(url: str, temp_dir: Path) -> dict[str, Any]:
    options = {
        **_YTDLP_OPTIONS,
        "format": "bestaudio/best",
        "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
    }

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        return info

def download_song(url: str, temp_dir: Path) -> Song:
    info = _extract_info(url)

    if not validate_song_metadata(info):
        raise ValidationError(
            "This video lacks formal metadata (artist, album, year). "
            "It may be a user-uploaded re-upload, not an official release."
        )

    _download(url, temp_dir)

    song = _build_song(info, url)
    ext = _sanitize_ext(info.get("ext"))
    song.download_path = temp_dir / f"{song.video_id}.{ext}"
    return song

def download_album(url: str) -> list[Song]:
    info = _extract_info(url)

    entries = list(info.get("entries", []))
    if not entries:
        raise ValidationError("No tracks found in album playlist.")

    album_name = None
    songs: list[Song] = []

    for entry in entries:
        if not validate_song_metadata(entry):
            continue

        entry_album = entry.get("album", "Unknown")
        if album_name is None:
            album_name = entry_album
        elif entry_album != album_name:
            raise ValidationError(
                f"Track '{entry.get('track')}' has album '{entry_album}', "
                f"expected '{album_name}'. Not a consistent album."
            )

        entry_id = entry.get("id")
        watch_url = _WATCH_URL.format(entry_id)
        songs.append(_build_song(entry, watch_url))

    if not songs:
        raise ValidationError("No formal tracks found in album.")

    return songs

def download_tracks(songs: list[Song], temp_dir: Path) -> list[Song]:
    options = {
        **_YTDLP_OPTIONS,
        "format": "bestaudio/best",
        "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
    }

    with YoutubeDL(options) as ydl:
        for song in songs:
            if not song.source_url or not song.video_id:
                continue
            info = ydl.extract_info(song.source_url, download=True)
            ext = _sanitize_ext(info.get("ext"))
            song.download_path = temp_dir / f"{song.video_id}.{ext}"

    return songs
