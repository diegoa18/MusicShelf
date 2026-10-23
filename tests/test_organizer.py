import pytest
from pathlib import Path
from musicshelf.organizer import get_target_path
from musicshelf.models import Song
from musicshelf.exceptions import MusicShelfError

@pytest.fixture
def mock_song():
    return Song(
        title="Death Of The Endless",
        artist="Sewerslvt",
        album="Sewerslvt Presents",
        video_id="v-YQ6Idf3qU",
        track=None,
        year=2024,
        duration=312,
        cover_url=None,
        source_url="https://music.youtube.com/watch?v=v-YQ6Idf3qU",
        download_path=None,
        final_path=None
    )

def test_get_target_path_without_track(mock_song, tmp_path):
    target = get_target_path(mock_song, tmp_path, ".m4a")
    expected = tmp_path / "Sewerslvt" / "Sewerslvt Presents" / "Death Of The Endless.m4a"
    assert target == expected

def test_get_target_path_with_track(mock_song, tmp_path):
    mock_song.track = 2
    target = get_target_path(mock_song, tmp_path, ".flac")
    expected = tmp_path / "Sewerslvt" / "Sewerslvt Presents" / "02 - Death Of The Endless.flac"
    assert target == expected

def test_get_target_path_sanitization(mock_song, tmp_path):
    mock_song.artist = "AC/DC"
    mock_song.album = "Back in Black"
    mock_song.title = "Hells Bells?"
    target = get_target_path(mock_song, tmp_path, ".m4a")

    expected = tmp_path / "ACDC" / "Back in Black" / "Hells Bells.m4a"
    assert target == expected

def test_get_target_path_sanitizes_traversal(mock_song, tmp_path):
    mock_song.artist = "../Malicious"
    target = get_target_path(mock_song, tmp_path, ".m4a")
    expected = tmp_path / "Malicious" / "Sewerslvt Presents" / "Death Of The Endless.m4a"
    assert target == expected

def test_get_target_path_failsafe_protection(mock_song, tmp_path, monkeypatch):
    import musicshelf.organizer
    monkeypatch.setattr(musicshelf.organizer, "_sanitize", lambda x: f"../../{x}")

    with pytest.raises(MusicShelfError, match="outside target directory"):
        get_target_path(mock_song, tmp_path, ".m4a")
