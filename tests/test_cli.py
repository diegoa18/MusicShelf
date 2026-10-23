import pytest
from typer.testing import CliRunner

import musicshelf.cli
from musicshelf.cli import app
from musicshelf.models import Song
from musicshelf.providers.youtube import YouTubeMusicProvider

runner = CliRunner()


@pytest.fixture
def mock_inspect(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_inspect(self: YouTubeMusicProvider, url: str) -> Song:
        return Song(
            title="Preview Track",
            artist="Test Artist",
            album="Test Album",
            source_id="dummy123",
            track=None,
            year=2026,
            duration=180,
            cover_url=None,
            source_url=url,
            download_path=None,
            final_path=None,
        )

    monkeypatch.setattr(YouTubeMusicProvider, "inspect_song", fake_inspect)


def test_dry_run_song_no_side_effects(
    mock_inspect: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        pytest.fail("Side effect triggered during dry-run")

    monkeypatch.setattr(musicshelf.cli, "_process_song", fail_if_called)
    monkeypatch.setattr(musicshelf.cli, "_process_album", fail_if_called)

    url = "https://music.youtube.com/watch?v=dummy123"
    result = runner.invoke(app, [url, "--dry-run", "--format", "flac"])

    assert result.exit_code == 0
    assert "YouTube Music" in result.stdout
    assert "Test Artist" in result.stdout
    assert "Preview Track" in result.stdout
    assert ".flac" in result.stdout


def test_skip_existing_file(
    mock_inspect: None, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    album_dir = tmp_path / "Test Artist" / "Test Album"
    album_dir.mkdir(parents=True)
    existing_track = album_dir / "Preview Track.m4a"
    existing_track.touch()

    def fail_if_downloaded(*args: object, **kwargs: object) -> None:
        pytest.fail("download_track was invoked even though the file already existed.")

    monkeypatch.setattr(YouTubeMusicProvider, "download_track", fail_if_downloaded)

    url = "https://music.youtube.com/watch?v=dummy123"
    result = runner.invoke(app, [url, "-d", str(tmp_path)])

    assert result.exit_code == 0
    assert "already exists in the library" in result.stdout
