from __future__ import annotations

import re
from enum import StrEnum
from typing import Any


class UrlType(StrEnum):
    SONG = "song"
    ALBUM = "album"
    PLAYLIST = "playlist"
    CHANNEL = "channel"
    UNKNOWN = "unknown"

_PATTERNS: dict[UrlType, re.Pattern[str]] = {
    UrlType.SONG: re.compile(r"^https?://music\.youtube\.com/watch\?v="),
    UrlType.ALBUM: re.compile(r"^https?://music\.youtube\.com/playlist\?list=OLAK5uy_"),
    UrlType.PLAYLIST: re.compile(r"^https?://music\.youtube\.com/playlist\?list=PL"),
    UrlType.CHANNEL: re.compile(r"^https?://music\.youtube\.com/@"),
}

def detect_url_type(url: str) -> UrlType:
    for url_type, pattern in _PATTERNS.items():
        if pattern.search(url):
            return url_type
    return UrlType.UNKNOWN

def validate_song_metadata(info: dict[str, Any]) -> bool:
    album = info.get("album")
    year = info.get("release_year")
    artist = info.get("artist") or info.get("uploader")

    return bool(album and year and artist)
