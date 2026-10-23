from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from musicshelf.exceptions import MusicShelfError, ValidationError
from musicshelf.models import Song
from musicshelf.providers.base import MusicProvider, UrlType

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


def _has_formal_metadata(info: dict[str, Any]) -> bool:
    album = info.get("album")
    year = info.get("release_year")
    artist = info.get("artist") or info.get("uploader")
    return bool(album and year and artist)


class YouTubeMusicProvider(MusicProvider):
    """Provider implementation for YouTube Music."""

    @property
    def name(self) -> str:
        return "YouTube Music"

    @property
    def supported_hosts(self) -> set[str]:
        return {"music.youtube.com"}

    def detect_url_type(self, url: str) -> UrlType:
        if not self.can_handle(url):
            return UrlType.UNKNOWN

        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        if parsed.path == "/watch" and "v" in query:
            return UrlType.SONG

        if parsed.path == "/playlist" and "list" in query:
            playlist_id = query["list"][0]
            if playlist_id.startswith("OLAK5uy_"):
                return UrlType.ALBUM
            if playlist_id.startswith("PL"):
                return UrlType.PLAYLIST
            return UrlType.UNKNOWN

        if parsed.path.startswith("/@"):
            return UrlType.CHANNEL

        return UrlType.UNKNOWN

    def validate_url(self, url: str) -> UrlType:
        url_type = self.detect_url_type(url)

        if url_type == UrlType.CHANNEL:
            raise ValidationError(
                "Channel URLs are not supported. Use a song or album URL instead."
            )

        if url_type == UrlType.PLAYLIST:
            raise ValidationError(
                "User playlists are not supported. Use an official album URL instead."
            )

        if url_type == UrlType.UNKNOWN:
            raise ValidationError("Unrecognized YouTube Music URL.")

        return url_type

    def _extract_info(self, url: str) -> dict[str, Any]:
        try:
            with YoutubeDL(_YTDLP_OPTIONS) as ydl:
                info = ydl.extract_info(url, download=False)
                if not isinstance(info, dict):
                    raise MusicShelfError(
                        "Failed to extract valid metadata from YouTube Music."
                    )
                return info
        except DownloadError as e:
            raise MusicShelfError(
                f"Connection or metadata extraction failure: {e.msg}"
            ) from None

    def _build_song(self, info: dict[str, Any], url: str) -> Song:
        return Song(
            title=info.get("track") or info.get("title", "Unknown"),
            artist=info.get("artist") or info.get("uploader", "Unknown"),
            album=info.get("album", "Unknown"),
            source_id=_sanitize_video_id(info.get("id")),
            track=info.get("track_number"),
            year=info.get("release_year"),
            duration=info.get("duration"),
            cover_url=info.get("thumbnail"),
            source_url=url,
        )

    def inspect_song(self, url: str) -> Song:
        info = self._extract_info(url)

        if not _has_formal_metadata(info):
            raise ValidationError(
                "This video lacks formal metadata (artist, album, year). "
                "It may be a user-uploaded re-upload, not an official release."
            )

        song = self._build_song(info, url)
        if not song.source_id:
            raise ValidationError(
                "Invalid or missing track identifier from YouTube Music."
            )
        return song

    def inspect_album(self, url: str) -> list[Song]:
        info = self._extract_info(url)

        entries = list(info.get("entries") or [])
        if not entries:
            raise ValidationError("No tracks found in album playlist.")

        album_name: str | None = None
        songs: list[Song] = []

        for entry in entries:
            if not entry or not _has_formal_metadata(entry):
                continue

            entry_album = entry.get("album", "Unknown")
            if album_name is None:
                album_name = entry_album
            elif entry_album != album_name:
                raise ValidationError(
                    f"Track '{entry.get('track')}' has album '{entry_album}', "
                    f"expected '{album_name}'. Not a consistent album."
                )

            video_id = _sanitize_video_id(entry.get("id"))
            if not video_id:
                continue

            watch_url = _WATCH_URL.format(video_id)
            songs.append(self._build_song(entry, watch_url))

        if not songs:
            raise ValidationError("No formal tracks found in album.")

        return songs

    def download_tracks(self, songs: list[Song], temp_dir: Path) -> list[Song]:
        options = {
            **_YTDLP_OPTIONS,
            "format": "bestaudio/best",
            "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
        }

        try:
            with YoutubeDL(options) as ydl:
                for song in songs:
                    if not song.source_url or not song.source_id:
                        continue
                    info = ydl.extract_info(song.source_url, download=True)
                    raw_ext = info.get("ext") if isinstance(info, dict) else None
                    ext = _sanitize_ext(raw_ext)
                    song.download_path = temp_dir / f"{song.source_id}.{ext}"
        except DownloadError as e:
            raise MusicShelfError(
                f"Connection or download failure: {e.msg}"
            ) from None

        return songs
