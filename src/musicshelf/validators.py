from __future__ import annotations

from enum import StrEnum
from typing import Any
from urllib.parse import parse_qs, urlparse


class UrlType(StrEnum):
    SONG = "song"
    ALBUM = "album"
    PLAYLIST = "playlist"
    CHANNEL = "channel"
    UNKNOWN = "unknown"


def detect_url_type(url: str) -> UrlType:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return UrlType.UNKNOWN

    if parsed.hostname != "music.youtube.com":
        return UrlType.UNKNOWN

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

def validate_song_metadata(info: dict[str, Any]) -> bool:
    album = info.get("album")
    year = info.get("release_year")
    artist = info.get("artist") or info.get("uploader")

    return bool(album and year and artist)
