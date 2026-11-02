from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse

from musicshelf.exceptions import MusicShelfError, ValidationError
from musicshelf.models import Song

_DOWNLOAD_WORKERS = 4

logger = logging.getLogger(__name__)


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

    def inspect_playlist(self, url: str) -> list[Song]:
        """Extract and validate formal metadata for every track in a playlist."""
        raise ValidationError("Playlists are not supported by this provider.")

    @abstractmethod
    def download_track(self, song: Song, temp_dir: Path) -> Song:
        """Resolve and download one already-inspected song into temp_dir."""

    def download_tracks(
        self,
        songs: list[Song],
        temp_dir: Path,
        on_progress: Callable[[Song], None] | None = None,
    ) -> list[Song]:
        """Download a batch concurrently, preserving the input order.

        Each track is handled by its own :meth:`download_track` worker. An
        individual failure is isolated: the failed song is left without a
        download path and the rest of the batch continues. ``on_progress`` is
        called once per song as its worker finishes, whether it succeeded or
        failed.
        """
        if not songs:
            return []

        results: list[Song] = list(songs)
        errors: list[tuple[Song, Exception]] = []
        workers = min(_DOWNLOAD_WORKERS, len(songs))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_index = {
                executor.submit(self.download_track, song, temp_dir): index
                for index, song in enumerate(songs)
            }
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                song = songs[index]
                try:
                    downloaded = future.result()
                except Exception as error:  # noqa: BLE001 - isolate per-track failures
                    song.download_path = None
                    errors.append((song, error))
                    logger.warning(
                        "Failed to download %r by %r: %s",
                        song.title,
                        song.artist,
                        error,
                    )
                else:
                    if downloaded is not None:
                        results[index] = downloaded

                if on_progress is not None:
                    on_progress(results[index])

        if not any(song.download_path is not None for song in results):
            if errors:
                first_error = errors[0][1]
                raise MusicShelfError(
                    f"No tracks could be downloaded ({len(errors)} failed): "
                    f"{first_error}"
                ) from first_error
            raise MusicShelfError("No tracks could be downloaded.")

        return results
