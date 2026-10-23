from pathlib import Path

import pytest

import musicshelf.organizer
from musicshelf.exceptions import MusicShelfError
from musicshelf.models import Song
from musicshelf.organizer import get_target_path


@pytest.fixture
def mock_song() -> Song:
    return Song(
        title="Death Of The Endless",
        artist="Sewerslvt",
        album="Sewerslvt Presents",
        source_id="v-YQ6Idf3qU",
        track=None,
        year=2024,
        duration=312,
        cover_url=None,
        source_url="https://music.youtube.com/watch?v=v-YQ6Idf3qU",
        download_path=None,
        final_path=None,
    )


def test_get_target_path_without_track(mock_song: Song, tmp_path: Path) -> None:
    target = get_target_path(mock_song, tmp_path, ".m4a")
    expected = (
        tmp_path / "Sewerslvt" / "Sewerslvt Presents" / "Death Of The Endless.m4a"
    )
    assert target == expected


def test_get_target_path_with_track(mock_song: Song, tmp_path: Path) -> None:
    mock_song.track = 2
    target = get_target_path(mock_song, tmp_path, ".flac")
    expected = (
        tmp_path / "Sewerslvt" / "Sewerslvt Presents" / "02 - Death Of The Endless.flac"
    )
    assert target == expected


def test_get_target_path_sanitization(mock_song: Song, tmp_path: Path) -> None:
    mock_song.artist = "AC/DC"
    mock_song.album = "Back in Black"
    mock_song.title = "Hells Bells?"
    target = get_target_path(mock_song, tmp_path, ".m4a")

    expected = tmp_path / "ACDC" / "Back in Black" / "Hells Bells.m4a"
    assert target == expected


def test_get_target_path_sanitizes_traversal(mock_song: Song, tmp_path: Path) -> None:
    mock_song.artist = "../Malicious"
    target = get_target_path(mock_song, tmp_path, ".m4a")
    expected = (
        tmp_path / "Malicious" / "Sewerslvt Presents" / "Death Of The Endless.m4a"
    )
    assert target == expected


def test_get_target_path_failsafe_protection(
    mock_song: Song, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(musicshelf.organizer, "_sanitize", lambda x: f"../../{x}")

    with pytest.raises(MusicShelfError, match="outside target directory"):
        get_target_path(mock_song, tmp_path, ".m4a")
