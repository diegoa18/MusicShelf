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


def _extract_year_from_html(html: str) -> int | None:
    match = re.search(r'<meta\s+property=["\']music:release_date["\']\s+content=["\'](\d{4})', html, re.IGNORECASE)
    if match:
        return int(match.group(1))

    match = re.search(r'"datePublished"\s*:\s*"(\d{4})', html)
    if match:
        return int(match.group(1))

    match = re.search(r'content=["\'](\d{4})-\d{2}-\d{2}', html)
    if match:
        return int(match.group(1))

    return None


def _fetch_entity_and_year(kind: str, item_id: str) -> tuple[dict[str, Any], int | None]:
    url = f"https://open.spotify.com/{kind}/{item_id}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    html = ""
    year = None

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            year = _extract_year_from_html(html)
    except URLError:
        pass

    embed_url = f"https://open.spotify.com/embed/{kind}/{item_id}"
    embed_req = urllib.request.Request(embed_url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(embed_req, timeout=15) as resp:
            embed_html = resp.read().decode("utf-8", errors="replace")
            match = _NEXT_DATA_RE.search(embed_html)
            if match:
                payload = json.loads(match.group(1))
                entity = payload["props"]["pageProps"]["state"]["data"]["entity"]
                if isinstance(entity, dict):
                    if not year:
                        # Deep search in embed entity if HTML meta didn't catch it
                        year = _extract_year_fallback(entity)
                    return entity, year
    except Exception:
        pass

    if not html:
        raise MusicShelfError("Could not reach Spotify endpoint.")

    return {}, year


def _extract_year_fallback(entity: dict[str, Any]) -> int | None:
    targets = [entity]
    if isinstance(entity.get("album"), dict):
        targets.append(entity["album"])

    for target in targets:
        for key in ("releaseDate", "release_date", "date", "year", "originalReleaseDate", "release"):
            val = target.get(key)
            if isinstance(val, dict):
                for sub_val in val.values():
                    if isinstance(sub_val, str):
                        match = re.search(r"\b(19\d{2}|20\d{2})\b", sub_val)
                        if match:
                            return int(match.group(1))
            elif isinstance(val, str):
                match = re.search(r"\b(19\d{2}|20\d{2})\b", val)
                if match:
                    return int(match.group(1))
            elif isinstance(val, int) and 1900 <= val <= 2100:
                return val

    return None


def _extract_cover_url(entity: dict[str, Any]) -> str | None:
    visual = entity.get("visualIdentity") or {}
    cover_art = entity.get("coverArt") or {}
    sources = visual.get("image") or cover_art.get("sources") or []
    if isinstance(sources, list) and sources:
        last = sources[-1]
        if isinstance(last, dict):
            return last.get("url")
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
        entity, year_val = _fetch_entity_and_year("track", track_id)

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
            year=year_val,
            date=str(year_val) if year_val else None,
            duration=duration_ms // 1000 if duration_ms else None,
            cover_url=_extract_cover_url(entity),
            source_url=url,
        )

    def inspect_album(self, url: str) -> list[Song]:
        album_id = self._extract_id(url)
        entity, album_year = _fetch_entity_and_year("album", album_id)

        album_name = entity.get("title") or entity.get("name") or "Unknown Album"
        album_artist = entity.get("subtitle") or "Unknown"
        cover_url = _extract_cover_url(entity)

        track_list = entity.get("trackList") or []
        if not track_list:
            raise ValidationError("No tracks found in Spotify album.")

        if not album_year and track_list:
            first_item = track_list[0]
            uri = first_item.get("uri") or ""
            if ":" in uri:
                first_track_id = uri.split(":")[-1]
                try:
                    track_entity, track_year = _fetch_entity_and_year("track", first_track_id)
                    if track_year:
                        album_year = track_year
                except Exception:
                    pass

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
                    year=album_year,
                    date=str(album_year) if album_year else None,
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
