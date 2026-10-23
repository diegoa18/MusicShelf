import pytest
from typer.testing import CliRunner

import musicshelf.cli
from musicshelf.cli import app
from musicshelf.models import Song

runner = CliRunner()

@pytest.fixture
def mock_inspect(monkeypatch):
    def fake_inspect(url):
        return Song(
            title="Preview Track",
            artist="Test Artist",
            album="Test Album",
            video_id="dummy123",
            track=None,
            year=2026,
            duration=180,
            cover_url=None,
            source_url=url,
            download_path=None,
            final_path=None
        )
    monkeypatch.setattr(musicshelf.cli, "inspect_song", fake_inspect)

def test_dry_run_song_no_side_effects(mock_inspect, monkeypatch):
    def fail_if_called(*args, **kwargs):
        pytest.fail("Side effect (discharge/movement) triggered during dry-run")

    monkeypatch.setattr(musicshelf.cli, "_process_song", fail_if_called)
    monkeypatch.setattr(musicshelf.cli, "_process_album", fail_if_called)

    url = "https://music.youtube.com/watch?v=dummy123"
    result = runner.invoke(app, [url, "--dry-run", "--format", "flac"])

    assert result.exit_code == 0
    assert "Test Artist" in result.stdout
    assert "Preview Track" in result.stdout
    assert ".flac" in result.stdout


def test_skip_existing_file(mock_inspect, tmp_path, monkeypatch):
    album_dir = tmp_path / "Test Artist" / "Test Album"
    album_dir.mkdir(parents=True)
    existing_track = album_dir / "Preview Track.m4a"
    existing_track.touch()

    def fail_if_downloaded(*args, **kwargs):
        pytest.fail("download_song was invoked even though the file already existed.")

    monkeypatch.setattr(musicshelf.cli, "download_song", fail_if_downloaded)

    url = "https://music.youtube.com/watch?v=dummy123"
    result = runner.invoke(app, [url, "-d", str(tmp_path)])

    assert result.exit_code == 0
    assert "already exists in the library" in result.stdout
