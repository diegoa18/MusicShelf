from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Self

import pytest
from yt_dlp.utils import DownloadError

from musicshelf.exceptions import MusicShelfError
from musicshelf.models import Song
from musicshelf.providers import spotify
from musicshelf.providers.spotify import SpotifyProvider


class FakeYoutubeDL:
    entries: ClassVar[list[dict[str, Any]]] = []
    downloaded_id: ClassVar[str] = "chosen"
    calls: ClassVar[list[tuple[str, bool]]] = []
    downloads: ClassVar[list[str]] = []
    instances: ClassVar[list[object]] = []
    error: ClassVar[str | None] = None

    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options
        type(self).instances.append(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def extract_info(self, url: str, download: bool = False) -> dict[str, Any]:
        type(self).calls.append((url, download))
        if type(self).error is not None:
            raise DownloadError(type(self).error)
        if url.startswith("ytsearch"):
            assert download is False
            return {"entries": list(type(self).entries)}

        assert download is True
        type(self).downloads.append(url)
        return {"id": type(self).downloaded_id, "ext": "webm"}


@pytest.fixture
def fake_ytdlp(monkeypatch: pytest.MonkeyPatch) -> type[FakeYoutubeDL]:
    FakeYoutubeDL.entries = []
    FakeYoutubeDL.downloaded_id = "chosen"
    FakeYoutubeDL.calls = []
    FakeYoutubeDL.downloads = []
    FakeYoutubeDL.instances = []
    FakeYoutubeDL.error = None
    monkeypatch.setattr(spotify, "YoutubeDL", FakeYoutubeDL)
    return FakeYoutubeDL


def _song(duration: int | None) -> Song:
    return Song(
        title="Loser",
        artist="Tame Impala",
        album="Deadbeat",
        duration=duration,
    )


def test_selects_candidate_matching_song_duration(
    fake_ytdlp: type[FakeYoutubeDL], tmp_path: Path
) -> None:
    fake_ytdlp.entries = [
        {"id": "long-intro", "duration": 260},
        {"id": "matching", "duration": 203},
        {"id": "another-match", "duration": 199},
    ]
    fake_ytdlp.downloaded_id = "matching"

    song = _song(200)
    result = SpotifyProvider().download_track(song, tmp_path)

    assert result == song
    assert song.download_path == tmp_path / "matching.webm"
    assert fake_ytdlp.downloads == ["https://www.youtube.com/watch?v=matching"]
    assert fake_ytdlp.calls[0] == (
        "ytsearch5:Tame Impala - Loser official audio",
        False,
    )


def test_falls_back_to_first_candidate_when_none_matches(
    fake_ytdlp: type[FakeYoutubeDL], tmp_path: Path
) -> None:
    fake_ytdlp.entries = [
        {"id": "first", "duration": 100},
        {"id": "second", "duration": 200},
    ]
    fake_ytdlp.downloaded_id = "first"

    song = _song(150)
    SpotifyProvider().download_track(song, tmp_path)

    assert song.download_path == tmp_path / "first.webm"
    assert fake_ytdlp.downloads == ["https://www.youtube.com/watch?v=first"]


def test_falls_back_to_first_candidate_without_song_duration(
    fake_ytdlp: type[FakeYoutubeDL], tmp_path: Path
) -> None:
    fake_ytdlp.entries = [
        {"id": "first", "duration": 100},
        {"id": "second", "duration": 300},
    ]
    fake_ytdlp.downloaded_id = "first"

    song = _song(None)
    SpotifyProvider().download_track(song, tmp_path)

    assert song.download_path == tmp_path / "first.webm"


def test_ignores_candidates_without_usable_duration(
    fake_ytdlp: type[FakeYoutubeDL], tmp_path: Path
) -> None:
    fake_ytdlp.entries = [
        {"id": "no-duration"},
        {"id": "bad-duration", "duration": "not-a-number"},
        {"id": "matching", "duration": "202"},
    ]
    fake_ytdlp.downloaded_id = "matching"

    song = _song(200)
    SpotifyProvider().download_track(song, tmp_path)

    assert song.download_path == tmp_path / "matching.webm"
    assert fake_ytdlp.downloads == ["https://www.youtube.com/watch?v=matching"]


def test_empty_search_results_do_not_raise(
    fake_ytdlp: type[FakeYoutubeDL], tmp_path: Path
) -> None:
    fake_ytdlp.entries = []
    song = _song(200)

    result = SpotifyProvider().download_track(song, tmp_path)

    assert result == song
    assert song.download_path is None
    assert fake_ytdlp.downloads == []


def test_each_download_creates_its_own_youtube_dl(
    fake_ytdlp: type[FakeYoutubeDL], tmp_path: Path
) -> None:
    fake_ytdlp.entries = [{"id": "chosen", "duration": 200}]
    provider = SpotifyProvider()

    provider.download_track(_song(200), tmp_path)
    provider.download_track(_song(200), tmp_path)

    assert len(fake_ytdlp.instances) == 2
    assert fake_ytdlp.instances[0] is not fake_ytdlp.instances[1]


def test_download_error_is_wrapped(
    fake_ytdlp: type[FakeYoutubeDL], tmp_path: Path
) -> None:
    fake_ytdlp.error = "boom"
    song = _song(200)

    with pytest.raises(
        MusicShelfError,
        match="Failed to resolve audio stream from YouTube: boom",
    ):
        SpotifyProvider().download_track(song, tmp_path)

    assert song.download_path is None
