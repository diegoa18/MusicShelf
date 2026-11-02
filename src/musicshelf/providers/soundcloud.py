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


class SoundCloudProvider(MusicProvider):
    """Provider implementation for SoundCloud."""

    @property
    def name(self) -> str:
        return "SoundCloud"

    @property
    def supported_hosts(self) -> set[str]:
        return {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"}

    def detect_url_type(self, url: str) -> UrlType:
        if not self.can_handle(url):
            return UrlType.UNKNOWN

        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]

        if not path_parts:
            return UrlType.UNKNOWN

        if len(path_parts) == 1:
            return UrlType.CHANNEL  # e.g., soundcloud.com/artist

        if len(path_parts) >= 3 and path_parts[1] == "sets":
            return UrlType.ALBUM  # e.g., soundcloud.com/artist/sets/playlist

        if len(path_parts) == 2:
            return UrlType.SONG  # e.g., soundcloud.com/artist/track

        return UrlType.UNKNOWN

    def validate_url(self, url: str) -> UrlType:
        url_type = self.detect_url_type(url)

        if url_type == UrlType.CHANNEL:
            raise ValidationError(
                "SoundCloud profiles/channels are not supported. Use a track or set URL."
            )

        if url_type == UrlType.UNKNOWN:
            raise ValidationError("Unrecognized SoundCloud URL format.")

        return url_type

    def _extract_info(self, url: str) -> dict[str, Any]:
        try:
            with YoutubeDL(_YTDLP_OPTIONS) as ydl:
                info = ydl.extract_info(url, download=False)
                if not isinstance(info, dict):
                    raise MusicShelfError(
                        "Failed to extract valid metadata from SoundCloud."
                    )
                return info
        except DownloadError as e:
            raise MusicShelfError(
                f"Connection or metadata extraction failure: {e.msg}"
            ) from None

    def _build_song(self, info: dict[str, Any], url: str) -> Song:
        # SoundCloud relies heavily on upload dates and uploader names
        title = info.get("track") or info.get("title", "Unknown")
        artist = info.get("artist") or info.get("uploader", "Unknown")

        # If there's no album, we group them into a logical singles folder
        album = info.get("album") or info.get("playlist_title") or "SoundCloud Singles"

        upload_date = info.get("upload_date")
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
            raise ValidationError(
                "Invalid or missing track identifier from SoundCloud."
            )

        return song

    def inspect_album(self, url: str) -> list[Song]:
        info = self._extract_info(url)

        entries = list(info.get("entries") or [])
        if not entries:
            raise ValidationError("No tracks found in SoundCloud set.")

        album_name = info.get("title", "Unknown Set")
        songs: list[Song] = []

        for idx, entry in enumerate(entries, start=1):
            if not entry:
                continue

            # Inject playlist context to force album grouping
            if not entry.get("album"):
                entry["album"] = album_name
            if not entry.get("track_number"):
                entry["track_number"] = idx

            track_url = entry.get("webpage_url") or entry.get("url") or url
            songs.append(self._build_song(entry, track_url))

        if not songs:
            raise ValidationError("No valid tracks found in SoundCloud set.")

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
