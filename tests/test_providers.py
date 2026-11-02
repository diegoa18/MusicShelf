import threading
from pathlib import Path

import pytest

from musicshelf.exceptions import MusicShelfError, ValidationError
from musicshelf.models import Song
from musicshelf.providers import (
    MusicProvider,
    UrlType,
    YouTubeMusicProvider,
    get_provider,
)


@pytest.fixture
def yt_provider() -> YouTubeMusicProvider:
    return YouTubeMusicProvider()


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://music.youtube.com/watch?v=v-YQ6Idf3qU", UrlType.SONG),
        ("https://music.youtube.com/watch?v=v-YQ6Idf3qU&si=xyz", UrlType.SONG),
        ("https://music.youtube.com/watch?si=xyz&v=v-YQ6Idf3qU", UrlType.SONG),
        ("https://music.youtube.com/playlist?list=OLAK5uy_abc123", UrlType.ALBUM),
        ("https://music.youtube.com/playlist?list=PL123456", UrlType.PLAYLIST),
        ("https://music.youtube.com/@artista", UrlType.CHANNEL),
        ("https://youtube.com/watch?v=v-YQ6Idf3qU", UrlType.UNKNOWN),
        ("https://evil.example/music.youtube.com/watch?v=abc", UrlType.UNKNOWN),
        ("https://music.youtube.com/watch", UrlType.UNKNOWN),
    ],
)
def test_youtube_detect_url_type(
    yt_provider: YouTubeMusicProvider, url: str, expected: UrlType
) -> None:
    assert yt_provider.detect_url_type(url) == expected


def test_get_provider_resolves_youtube() -> None:
    provider = get_provider("https://music.youtube.com/watch?v=v-YQ6Idf3qU")
    assert isinstance(provider, YouTubeMusicProvider)
    assert provider.name == "YouTube Music"


@pytest.mark.parametrize(
    "unsupported_url",
    [
        "https://youtube.com/watch?v=v-YQ6Idf3qU",
        "https://evil.example/music.youtube.com/watch?v=abc",
        "ftp://music.youtube.com/watch?v=abc",
    ],
)
def test_get_provider_rejects_unsupported_domains(unsupported_url: str) -> None:
    with pytest.raises(ValidationError, match="Unsupported URL or provider"):
        get_provider(unsupported_url)


@pytest.mark.parametrize(
    "invalid_url, expected_message",
    [
        (
            "https://music.youtube.com/@artista",
            "Channel URLs are not supported",
        ),
        (
            "https://music.youtube.com/playlist?list=PL123456",
            "User playlists are not supported",
        ),
        (
            "https://music.youtube.com/watch",
            "Unrecognized YouTube Music URL",
        ),
    ],
)
def test_youtube_validate_url_rejects_invalid_types(
    yt_provider: YouTubeMusicProvider, invalid_url: str, expected_message: str
) -> None:
    with pytest.raises(ValidationError, match=expected_message):
        yt_provider.validate_url(invalid_url)


class RecordingProvider(MusicProvider):
    """Minimal provider used to exercise the base batch orchestration."""

    def __init__(
        self,
        barrier: threading.Barrier | None = None,
        failing: set[str] | None = None,
    ) -> None:
        self.barrier = barrier
        self.failing = failing or set()

    @property
    def name(self) -> str:
        return "Recording"

    @property
    def supported_hosts(self) -> set[str]:
        return {"example.com"}

    def detect_url_type(self, url: str) -> UrlType:
        return UrlType.UNKNOWN

    def validate_url(self, url: str) -> UrlType:
        raise ValidationError("Not supported in this fake provider.")

    def inspect_song(self, url: str) -> Song:
        raise ValidationError("Not supported in this fake provider.")

    def inspect_album(self, url: str) -> list[Song]:
        return []

    def download_track(self, song: Song, temp_dir: Path) -> Song:
        if self.barrier is not None:
            self.barrier.wait(timeout=3)
        if song.title in self.failing:
            raise RuntimeError(f"failed to download {song.title}")
        song.download_path = temp_dir / f"{song.title}.webm"
        return song


def _provider_song(title: str) -> Song:
    return Song(title=title, artist="Artist", album="Album")


def test_download_tracks_runs_in_parallel_and_keeps_input_order(
    tmp_path: Path,
) -> None:
    songs = [_provider_song("First"), _provider_song("Second")]
    provider = RecordingProvider(barrier=threading.Barrier(len(songs), timeout=3))
    completed: list[str] = []

    result = provider.download_tracks(
        songs, tmp_path, on_progress=lambda song: completed.append(song.title)
    )

    assert [song.title for song in result] == ["First", "Second"]
    assert [song.download_path for song in result] == [
        tmp_path / "First.webm",
        tmp_path / "Second.webm",
    ]
    assert sorted(completed) == ["First", "Second"]


def test_download_tracks_isolates_a_track_failure(tmp_path: Path) -> None:
    songs = [
        _provider_song("First"),
        _provider_song("Second"),
        _provider_song("Third"),
    ]
    provider = RecordingProvider(failing={"Second"})
    songs[1].download_path = tmp_path / "stale.webm"
    completed: list[str] = []

    result = provider.download_tracks(
        songs, tmp_path, on_progress=lambda song: completed.append(song.title)
    )

    assert [song.title for song in result] == ["First", "Second", "Third"]
    assert result[0].download_path == tmp_path / "First.webm"
    assert result[1].download_path is None
    assert result[2].download_path == tmp_path / "Third.webm"
    assert sorted(completed) == ["First", "Second", "Third"]


def test_download_tracks_raises_when_every_track_fails(tmp_path: Path) -> None:
    songs = [_provider_song("First"), _provider_song("Second")]
    provider = RecordingProvider(failing={"First", "Second"})
    completed: list[str] = []

    with pytest.raises(MusicShelfError, match="No tracks could be downloaded"):
        provider.download_tracks(
            songs, tmp_path, on_progress=lambda song: completed.append(song.title)
        )

    assert sorted(completed) == ["First", "Second"]
    assert all(song.download_path is None for song in songs)


def test_download_tracks_empty_batch_returns_empty() -> None:
    assert RecordingProvider().download_tracks([], Path("/tmp")) == []


class NoPathProvider(RecordingProvider):
    """Provider that resolves nothing, without raising."""

    def download_track(self, song: Song, temp_dir: Path) -> Song:
        return song


def test_download_tracks_raises_when_none_return_paths(tmp_path: Path) -> None:
    songs = [_provider_song("First"), _provider_song("Second")]
    completed: list[str] = []

    with pytest.raises(MusicShelfError, match="No tracks could be downloaded"):
        NoPathProvider().download_tracks(
            songs, tmp_path, on_progress=lambda song: completed.append(song.title)
        )

    assert sorted(completed) == ["First", "Second"]
    assert all(song.download_path is None for song in songs)
