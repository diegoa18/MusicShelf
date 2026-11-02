from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from musicshelf.exceptions import MusicShelfError, ValidationError
from musicshelf.models import Song
from musicshelf.providers.base import MusicProvider, UrlType

_YTDLP_OPTIONS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
}


def _sanitize_ext(ext: str | None) -> str:
    _SAFE = {"mp3", "opus", "m4a", "ogg", "flac", "wav"}
    if ext and ext.lower() in _SAFE:
        return ext.lower()
    return "mp3"


class BandcampProvider(MusicProvider):
    """Provider implementation for Bandcamp."""

    @property
    def name(self) -> str:
        return "Bandcamp"

    @property
    def supported_hosts(self) -> set[str]:
        return {"bandcamp.com"}

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        # Intercepts both bandcamp.com and any subdomain like artist.bandcamp.com
        return (
            parsed.hostname.endswith(".bandcamp.com")
            or parsed.hostname == "bandcamp.com"
        )

    def detect_url_type(self, url: str) -> UrlType:
        if not self.can_handle(url):
            return UrlType.UNKNOWN

        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]

        if not path_parts:
            return UrlType.CHANNEL

        if path_parts[0] == "track":
            return UrlType.SONG

        if path_parts[0] == "album":
            return UrlType.ALBUM

        return UrlType.UNKNOWN

    def validate_url(self, url: str) -> UrlType:
        url_type = self.detect_url_type(url)

        if url_type == UrlType.CHANNEL:
            raise ValidationError(
                "Bandcamp artist profiles are not supported. Use a specific track or album URL."
            )

        if url_type == UrlType.UNKNOWN:
            raise ValidationError("Unrecognized Bandcamp URL format.")

        return url_type

    def _extract_info(self, url: str) -> dict[str, Any]:
        try:
            with YoutubeDL(_YTDLP_OPTIONS) as ydl:
                info = ydl.extract_info(url, download=False)
                if not isinstance(info, dict):
                    raise MusicShelfError(
                        "Failed to extract valid metadata from Bandcamp."
                    )
                return info
        except DownloadError as e:
            raise MusicShelfError(
                f"Connection or metadata extraction failure: {e.msg}"
            ) from None

    def _build_song(self, info: dict[str, Any], url: str) -> Song:
        title = info.get("track") or info.get("title", "Unknown")
        artist = info.get("artist") or info.get("uploader", "Unknown")
        album = info.get("album") or "Bandcamp Singles"

        upload_date = info.get("release_date") or info.get("upload_date")
        year = info.get("release_year")
        if not year and upload_date and len(upload_date) >= 4:
            year = int(upload_date[:4])

        return Song(
            title=title,
            artist=artist,
            album=album,
            source_id=info.get("id"),
            track=info.get("track_number"),
            year=year,
            duration=info.get("duration"),
            cover_url=info.get("thumbnail"),
            source_url=url,
        )

    def inspect_song(self, url: str) -> Song:
        info = self._extract_info(url)
        song = self._build_song(info, url)

        if not song.source_id:
            raise ValidationError("Invalid or missing track identifier from Bandcamp.")

        return song

    def inspect_album(self, url: str) -> list[Song]:
        info = self._extract_info(url)

        entries = list(info.get("entries") or [])
        if not entries:
            raise ValidationError("No tracks found in Bandcamp album.")

        songs: list[Song] = []

        for entry in entries:
            if not entry:
                continue

            track_url = entry.get("webpage_url") or entry.get("url") or url
            songs.append(self._build_song(entry, track_url))

        if not songs:
            raise ValidationError("No valid tracks found in Bandcamp album.")

        return songs

    def download_track(self, song: Song, temp_dir: Path) -> Song:
        song.download_path = None
        if not song.source_url or not song.source_id:
            return song

        options = {
            **_YTDLP_OPTIONS,
            "format": "bestaudio/best",
            "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
        }

        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(song.source_url, download=True)
            raw_ext = info.get("ext") if isinstance(info, dict) else None
            ext = _sanitize_ext(raw_ext)
            song.download_path = temp_dir / f"{song.source_id}.{ext}"
        except DownloadError as e:
            raise MusicShelfError(f"Connection or download failure: {e.msg}") from None

        return song
