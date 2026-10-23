import pytest
from typer.testing import CliRunner
from musicshelf.cli import app
from musicshelf.models import Song
import musicshelf.cli

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
        pytest.fail("Efecto secundario (descarga/movimiento) invocado durante dry-run")

    monkeypatch.setattr(musicshelf.cli, "_process_song", fail_if_called)
    monkeypatch.setattr(musicshelf.cli, "_process_album", fail_if_called)

    url = "https://music.youtube.com/watch?v=dummy123"
    result = runner.invoke(app, [url, "--dry-run", "--format", "flac"])

    assert result.exit_code == 0
    assert "Test Artist" in result.stdout
    assert "Preview Track" in result.stdout
    assert ".flac" in result.stdout
