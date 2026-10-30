from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from musicshelf.exceptions import MusicShelfError, ValidationError
from musicshelf.models import Song
from musicshelf.providers.base import MusicProvider, UrlType

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
)
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">([^<]+)</script>'
)


def _sanitize_ext(ext: str | None) -> str:
    _SAFE = {"webm", "opus", "m4a", "mp3", "ogg", "flac", "wav"}
    if ext and ext.lower() in _SAFE:
        return ext.lower()
    return "webm"


def _fetch_embed_entity(kind: str, item_id: str) -> dict[str, Any]:
    """Read public metadata from Spotify's standard embed widget."""
    url = f"https://open.spotify.com/embed/{kind}/{item_id}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise MusicShelfError(f"Failed to reach Spotify embed endpoint: {e}") from None

    match = _NEXT_DATA_RE.search(html)
    if not match:
        raise MusicShelfError("Could not parse public metadata from Spotify embed.")

    try:
        payload = json.loads(match.group(1))
        entity = payload["props"]["pageProps"]["state"]["data"]["entity"]
        if not isinstance(entity, dict):
            raise KeyError("Invalid entity structure")
        return entity
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise MusicShelfError(
            "Spotify embed data format changed or is unavailable."
        ) from e


def _extract_cover_url(entity: dict[str, Any]) -> str | None:
    visual = entity.get("visualIdentity") or {}
    cover_art = entity.get("coverArt") or {}
    sources = visual.get("image") or cover_art.get("sources") or []
    if isinstance(sources, list) and sources:
        last = sources[-1]
        if isinstance(last, dict):
            return last.get("url")
    return None


def _extract_year(entity: dict[str, Any]) -> int | None:
    release_date = entity.get("releaseDate")
    if isinstance(release_date, dict):
        iso = release_date.get("isoString") or ""
        if len(iso) >= 4 and iso[:4].isdigit():
            return int(iso[:4])
    elif isinstance(release_date, str) and len(release_date) >= 4 and release_date[:4].isdigit():
        return int(release_date[:4])
    return None


class SpotifyProvider(MusicProvider):
    """Hybrid Provider: Reads public Spotify embed metadata, resolves audio via YouTube."""

    @property
    def name(self) -> str:
        return "Spotify (Hybrid)"

    @property
    def supported_hosts(self) -> set[str]:
        return {"open.spotify.com", "spotify.com"}

    def detect_url_type(self, url: str) -> UrlType:
        if not self.can_handle(url):
            return UrlType.UNKNOWN

        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if parts and parts[0].startswith("intl-"):
            parts = parts[1:]

        if len(parts) < 2:
            return UrlType.UNKNOWN

        kind = parts[0]
        if kind == "track":
            return UrlType.SONG
        if kind == "album":
            return UrlType.ALBUM
        if kind == "playlist":
            return UrlType.PLAYLIST
        if kind == "artist":
            return UrlType.CHANNEL

        return UrlType.UNKNOWN

    def validate_url(self, url: str) -> UrlType:
        url_type = self.detect_url_type(url)

        if url_type == UrlType.CHANNEL:
            raise ValidationError("Spotify artist profiles are not supported.")
        if url_type == UrlType.PLAYLIST:
            raise ValidationError(
                "Spotify user playlists are not supported. Use an album or track URL."
            )
        if url_type == UrlType.UNKNOWN:
            raise ValidationError("Unrecognized Spotify URL format.")

        return url_type

    def _extract_id(self, url: str) -> str:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        return parts[-1]

    def inspect_song(self, url: str) -> Song:
        track_id = self._extract_id(url)
        entity = _fetch_embed_entity("track", track_id)

        title = entity.get("title") or entity.get("name") or "Unknown"
        artists = entity.get("artists") or []
        artist = (
            artists[0].get("name", "Unknown")
            if artists and isinstance(artists[0], dict)
            else (entity.get("subtitle") or "Unknown")
        )

        duration_ms = entity.get("duration") or 0

        return Song(
            title=title,
            artist=artist,
            album=entity.get("subtitle") or "Spotify Singles",
            source_id=entity.get("id") or track_id,
            track=1,
            year=_extract_year(entity),
            duration=duration_ms // 1000 if duration_ms else None,
            cover_url=_extract_cover_url(entity),
            source_url=url,
        )

    def inspect_album(self, url: str) -> list[Song]:
        album_id = self._extract_id(url)
        entity = _fetch_embed_entity("album", album_id)

        album_name = entity.get("title") or entity.get("name") or "Unknown Album"
        album_artist = entity.get("subtitle") or "Unknown"
        cover_url = _extract_cover_url(entity)
        year = _extract_year(entity)

        track_list = entity.get("trackList") or []
        if not track_list:
            raise ValidationError("No tracks found in Spotify album.")

        songs: list[Song] = []
        for idx, item in enumerate(track_list, start=1):
            if not isinstance(item, dict):
                continue
            uri = item.get("uri") or ""
            track_id = uri.split(":")[-1] if ":" in uri else f"{album_id}_{idx}"
            duration_ms = item.get("duration") or 0

            songs.append(
                Song(
                    title=item.get("title") or "Unknown",
                    artist=item.get("subtitle") or album_artist,
                    album=album_name,
                    source_id=track_id,
                    track=idx,
                    year=year,
                    duration=duration_ms // 1000 if duration_ms else None,
                    cover_url=cover_url,
                    source_url=f"https://open.spotify.com/track/{track_id}",
                )
            )

        return songs

    def download_tracks(self, songs: list[Song], temp_dir: Path) -> list[Song]:
        options = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio/best",
            "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
        }

        try:
            with YoutubeDL(options) as ydl:
                for song in songs:
                    if not song.title or not song.artist:
                        continue

                    query = f"ytsearch1:{song.artist} - {song.title} official audio"
                    info = ydl.extract_info(query, download=True)
                    if not info:
                        continue

                    entries = info.get("entries")
                    entry = entries[0] if entries else info
                    yt_id = entry.get("id")
                    ext = _sanitize_ext(entry.get("ext"))

                    if yt_id:
                        song.download_path = temp_dir / f"{yt_id}.{ext}"
        except DownloadError as e:
            raise MusicShelfError(
                f"Failed to resolve audio stream from YouTube: {e.msg}"
            ) from None

        return songs
