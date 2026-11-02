import shutil
from pathlib import Path

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
    mock_inspect: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    album_dir = tmp_path / "Test Artist" / "Test Album"
    album_dir.mkdir(parents=True)
    existing_track = album_dir / "Preview Track.m4a"
    existing_track.touch()

    def fail_if_called(*args: object, **kwargs: object) -> None:
        pytest.fail("Work was started even though the file already existed.")

    monkeypatch.setattr(YouTubeMusicProvider, "download_tracks", fail_if_called)
    monkeypatch.setattr(musicshelf.cli.tempfile, "TemporaryDirectory", fail_if_called)

    url = "https://music.youtube.com/watch?v=dummy123"
    result = runner.invoke(app, [url, "-d", str(tmp_path)])

    assert result.exit_code == 0
    assert "already exists in the library" in result.stdout
    assert str(existing_track) in result.stdout
    assert "Downloaded: 0 | Processed: 0 | Skipped: 1" in result.stdout


def _album_song(
    title: str,
    track: int,
    number: str,
) -> Song:
    return Song(
        title=title,
        artist="Test Artist",
        album="Test Album",
        source_id=number,
        track=track,
        year=2026,
        duration=180,
        source_url=f"https://music.youtube.com/watch?v={number}",
    )


def test_album_all_existing_skips_before_workdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    songs = [
        _album_song("First Song", 1, "one"),
        _album_song("Second Song", 2, "two"),
    ]
    monkeypatch.setattr(YouTubeMusicProvider, "inspect_album", lambda self, url: songs)

    for song in songs:
        target = musicshelf.cli.get_target_path(song, tmp_path, ".m4a")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()

    def fail_if_called(*args: object, **kwargs: object) -> None:
        pytest.fail("Album started downloading or created a workdir.")

    monkeypatch.setattr(YouTubeMusicProvider, "download_tracks", fail_if_called)
    monkeypatch.setattr(musicshelf.cli.tempfile, "TemporaryDirectory", fail_if_called)

    url = "https://music.youtube.com/playlist?list=OLAK5uy_test"
    result = runner.invoke(app, [url, "-d", str(tmp_path)])

    assert result.exit_code == 0
    assert "All tracks are already in the library." in result.stdout
    assert "Downloaded: 0 | Processed: 0 | Skipped: 2" in result.stdout


def test_overwrite_processes_existing_file(
    mock_inspect: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    album_dir = tmp_path / "Test Artist" / "Test Album"
    album_dir.mkdir(parents=True)
    existing_track = album_dir / "Preview Track.m4a"
    existing_track.write_bytes(b"old")

    downloaded: list[str] = []

    def fake_download_tracks(
        self: YouTubeMusicProvider, songs: list[Song], temp_dir: Path
    ) -> list[Song]:
        downloaded.append(songs[0].title)
        source = Path(temp_dir) / "raw.m4a"
        source.write_bytes(b"new")
        songs[0].download_path = source
        return songs

    def fake_convert(source: Path, fmt: object, temp_dir: Path) -> Path:
        destination = Path(temp_dir) / "converted.m4a"
        shutil.copyfile(source, destination)
        return destination

    monkeypatch.setattr(YouTubeMusicProvider, "download_tracks", fake_download_tracks)
    monkeypatch.setattr(musicshelf.cli, "convert", fake_convert)
    monkeypatch.setattr(musicshelf.cli, "write_metadata", lambda song: None)

    url = "https://music.youtube.com/watch?v=dummy123"
    result = runner.invoke(app, [url, "-d", str(tmp_path), "--overwrite"])

    assert result.exit_code == 0, result.stdout
    assert downloaded == ["Preview Track"]
    assert existing_track.read_bytes() == b"new"
    assert "Downloaded: 1 | Processed: 1 | Skipped: 0" in result.stdout


def test_album_partial_skip_downloads_only_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    songs = [
        _album_song("First Song", 1, "one"),
        _album_song("Second Song", 2, "two"),
    ]
    monkeypatch.setattr(YouTubeMusicProvider, "inspect_album", lambda self, url: songs)

    existing_target = musicshelf.cli.get_target_path(songs[0], tmp_path, ".m4a")
    existing_target.parent.mkdir(parents=True)
    existing_target.write_bytes(b"old")

    downloaded: list[str] = []

    def fake_download_tracks(
        self: YouTubeMusicProvider, batch: list[Song], temp_dir: Path
    ) -> list[Song]:
        downloaded.extend(song.title for song in batch)
        source = Path(temp_dir) / f"{batch[0].source_id}.m4a"
        source.write_bytes(b"new")
        batch[0].download_path = source
        return batch

    def fake_convert(source: Path, fmt: object, temp_dir: Path) -> Path:
        destination = Path(temp_dir) / f"{source.stem}-converted.m4a"
        shutil.copyfile(source, destination)
        return destination

    monkeypatch.setattr(YouTubeMusicProvider, "download_tracks", fake_download_tracks)
    monkeypatch.setattr(musicshelf.cli, "convert", fake_convert)
    monkeypatch.setattr(musicshelf.cli, "write_metadata", lambda song: None)

    url = "https://music.youtube.com/playlist?list=OLAK5uy_test"
    result = runner.invoke(app, [url, "-d", str(tmp_path)])

    assert result.exit_code == 0, result.stdout
    assert downloaded == ["Second Song"]
    assert existing_target.read_bytes() == b"old"
    new_target = musicshelf.cli.get_target_path(songs[1], tmp_path, ".m4a")
    assert new_target.exists()
    assert "Downloaded: 1 | Processed: 1 | Skipped: 1" in result.stdout
