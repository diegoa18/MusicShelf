from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse

from musicshelf.models import Song


class UrlType(StrEnum):
    SONG = "song"
    ALBUM = "album"
    PLAYLIST = "playlist"
    CHANNEL = "channel"
    UNKNOWN = "unknown"


class MusicProvider(ABC):
    """Abstract base contract for external music providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of the provider."""

    @property
    @abstractmethod
    def supported_hosts(self) -> set[str]:
        """Exact domain hostnames supported by this provider."""

    def can_handle(self, url: str) -> bool:
        """Return True if this provider handles the given URL's domain."""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        return parsed.hostname.lower() in self.supported_hosts

    @abstractmethod
    def detect_url_type(self, url: str) -> UrlType:
        """Classify the URL without performing network requests."""

    @abstractmethod
    def validate_url(self, url: str) -> UrlType:
        """Validate the URL and return its UrlType, or raise ValidationError."""

    @abstractmethod
    def inspect_song(self, url: str) -> Song:
        """Extract and validate formal metadata for a single track."""

    @abstractmethod
    def inspect_album(self, url: str) -> list[Song]:
        """Extract and validate formal metadata for an entire album."""

    @abstractmethod
    def download_tracks(self, songs: list[Song], temp_dir: Path) -> list[Song]:
        """Download audio streams for the given songs into temp_dir."""

    def download_track(self, song: Song, temp_dir: Path) -> Song:
        """Download audio stream for a single already-inspected song."""
        self.download_tracks([song], temp_dir)
        return song
