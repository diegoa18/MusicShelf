from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

import musicshelf.cli
from musicshelf.cli import app
from musicshelf.converter import AudioFormat
from musicshelf.exceptions import MusicShelfError, ValidationError
from musicshelf.models import Song
from musicshelf.providers import spotify
from musicshelf.providers.spotify import SpotifyProvider
from musicshelf.providers.youtube import YouTubeMusicProvider

PLAYLIST_URL = "https://open.spotify.com/playlist/playlist123"
runner = CliRunner()


def _song(
    title: str,
    artist: str,
    album: str,
    source_id: str,
) -> Song:
    return Song(
        title=title,
        artist=artist,
        album=album,
        source_id=source_id,
        year=2020,
        date="2020-01-01",
        duration=180,
        cover_url="cover.jpg",
        source_url=f"https://open.spotify.com/track/{source_id}",
    )


@pytest.mark.parametrize(
    "url",
    [
        PLAYLIST_URL,
        "https://open.spotify.com/intl-es/playlist/playlist123?si=abc",
        "https://spotify.com/playlist/playlist123",
    ],
)
def test_playlist_urls_are_supported(url: str) -> None:
    provider = SpotifyProvider()

    assert provider.detect_url_type(url) is spotify.UrlType.PLAYLIST
    assert provider.validate_url(url) is spotify.UrlType.PLAYLIST


def test_inspect_playlist_creates_one_song_per_track(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playlist_entity = {
        "type": "playlist",
        "name": "Road Trip",
        "coverArt": {"sources": [{"url": "playlist-cover.jpg", "width": 300}]},
        "trackList": [
            {
                "uri": "spotify:track:track-one",
                "title": "First Song",
                "subtitle": "Artist One",
                "duration": 180000,
                "entityType": "track",
            },
            {
                "uri": "spotify:track:track-two",
                "title": "Second Song",
                "subtitle": "Artist Two",
                "duration": 240000,
                "entityType": "track",
            },
        ],
    }
    track_entities = {
        "track-one": {
            "title": "First Song",
            "artists": [{"name": "Artist One"}],
            "album": {"name": "Album One"},
            "duration": 180000,
            "releaseDate": {"isoString": "2019-03-01T00:00:00Z"},
            "visualIdentity": {
                "image": [
                    {"url": "cover-one-small.jpg", "maxWidth": 64},
                    {"url": "cover-one-large.jpg", "maxWidth": 640},
                ]
            },
        },
        "track-two": {
            "title": "Second Song",
            "artists": [{"name": "Artist Two"}],
            "album": {"name": "Album Two"},
            "duration": 240000,
            "releaseDate": {"isoString": "2021-07-09T00:00:00Z"},
            "visualIdentity": {"image": [{"url": "cover-two.jpg", "maxWidth": 640}]},
        },
    }

    def fake_fetch(kind: str, item_id: str) -> tuple[dict[str, object], int | None]:
        if kind == "playlist":
            return playlist_entity, None
        return track_entities[item_id], None

    monkeypatch.setattr(spotify, "_fetch_entity_and_year", fake_fetch)

    songs = SpotifyProvider().inspect_playlist(PLAYLIST_URL)

    assert [song.title for song in songs] == ["First Song", "Second Song"]
    assert [song.artist for song in songs] == ["Artist One", "Artist Two"]
    assert [song.album for song in songs] == ["Album One", "Album Two"]
    assert songs[0].album != playlist_entity["name"]
    assert [song.year for song in songs] == [2019, 2021]
    assert [song.date for song in songs] == ["2019-03-01", "2021-07-09"]
    assert [song.duration for song in songs] == [180, 240]
    assert [song.cover_url for song in songs] == [
        "cover-one-large.jpg",
        "cover-two.jpg",
    ]
    assert [song.source_id for song in songs] == ["track-one", "track-two"]
    assert [song.source_url for song in songs] == [
        "https://open.spotify.com/track/track-one",
        "https://open.spotify.com/track/track-two",
    ]
    assert all(song.track is None for song in songs)


def test_inspect_playlist_uses_pathfinder_album_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playlist_id = "37i9dQZF1DXcBWIGoYBM5M"
    playlist_url = f"https://open.spotify.com/playlist/{playlist_id}"
    playlist_entity = {
        "name": "Editorial Playlist",
        "trackList": [
            {
                "uri": "spotify:track:track-one",
                "title": "First Song",
                "subtitle": "Artist One",
                "duration": 180000,
                "entityType": "track",
            }
        ],
    }
    calls: list[tuple[str, str]] = []

    def fake_fetch(kind: str, item_id: str) -> tuple[dict[str, object], int | None]:
        calls.append((kind, item_id))
        return playlist_entity, None

    def fake_pathfinder(item_id: str) -> dict[str, dict[str, object]]:
        assert item_id == playlist_id
        return {
            "track-one": {
                "title": "First Song",
                "artists": [{"name": "Artist One"}],
                "album": {
                    "name": "Album One",
                    "date": {"isoString": "2020-02-03T00:00:00Z"},
                    "coverArt": {"sources": [{"url": "cover-one.jpg", "width": 640}]},
                },
                "trackNumber": 3,
            }
        }

    monkeypatch.setattr(spotify, "_fetch_entity_and_year", fake_fetch)
    monkeypatch.setattr(spotify, "_fetch_pathfinder_playlist", fake_pathfinder)

    song = SpotifyProvider().inspect_playlist(playlist_url)[0]

    assert song.album == "Album One"
    assert song.album != playlist_entity["name"]
    assert song.date == "2020-02-03"
    assert song.year == 2020
    assert song.track == 3
    assert song.cover_url == "cover-one.jpg"
    assert calls == [("playlist", playlist_id)]


def test_inspect_playlist_uses_item_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playlist_entity = {
        "trackList": [
            {
                "uri": "spotify:track:direct",
                "title": "Direct Song",
                "subtitle": "Direct Artist",
                "duration": 90000,
                "entityType": "track",
                "album": {"name": "Direct Album"},
                "releaseDate": {"isoString": "2018-02-03T00:00:00Z"},
                "trackNumber": 4,
            }
        ]
    }

    def fake_fetch(kind: str, item_id: str) -> tuple[dict[str, object], int | None]:
        assert kind == "playlist"
        return playlist_entity, None

    monkeypatch.setattr(spotify, "_fetch_entity_and_year", fake_fetch)

    song = SpotifyProvider().inspect_playlist(PLAYLIST_URL)[0]

    assert song.album == "Direct Album"
    assert song.year == 2018
    assert song.date == "2018-02-03"
    assert song.track == 4
    assert song.cover_url is None


def test_inspect_playlist_supports_api_style_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playlist_entity = {
        "trackList": [
            {
                "track": {
                    "uri": "spotify:track:track-one",
                    "name": "Wrapped Song",
                    "artists": [{"name": "Wrapped Artist"}],
                    "album": {"name": "Wrapped Album"},
                    "duration_ms": 120000,
                    "track_number": 2,
                }
            }
        ]
    }

    def fake_fetch(kind: str, item_id: str) -> tuple[dict[str, object], int | None]:
        if kind == "playlist":
            return playlist_entity, None
        return {}, None

    monkeypatch.setattr(spotify, "_fetch_entity_and_year", fake_fetch)

    song = SpotifyProvider().inspect_playlist(PLAYLIST_URL)[0]

    assert song.title == "Wrapped Song"
    assert song.artist == "Wrapped Artist"
    assert song.album == "Wrapped Album"
    assert song.duration == 120
    assert song.track == 2


def test_inspect_playlist_falls_back_to_unknown_album(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playlist_entity = {
        "name": "Playlist Name",
        "trackList": [
            {
                "uri": "spotify:track:no-album",
                "title": "No Album Song",
                "subtitle": "Some Artist",
                "duration": 120000,
                "entityType": "track",
            }
        ],
    }

    def fake_fetch(kind: str, item_id: str) -> tuple[dict[str, object], int | None]:
        if kind == "playlist":
            return playlist_entity, None
        return {}, None

    monkeypatch.setattr(spotify, "_fetch_entity_and_year", fake_fetch)

    song = SpotifyProvider().inspect_playlist(PLAYLIST_URL)[0]

    assert song.album == "Unknown Album"
    assert song.album != playlist_entity["name"]


def test_inspect_playlist_skips_non_track_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playlist_entity = {
        "trackList": [
            {
                "uri": "spotify:episode:episode-one",
                "title": "Podcast",
                "entityType": "episode",
            },
            {
                "uri": "spotify:track:real-track",
                "title": "Real Track",
                "subtitle": "Real Artist",
                "entityType": "track",
            },
        ]
    }

    def fake_fetch(kind: str, item_id: str) -> tuple[dict[str, object], int | None]:
        if kind == "playlist":
            return playlist_entity, None
        return {}, None

    monkeypatch.setattr(spotify, "_fetch_entity_and_year", fake_fetch)

    songs = SpotifyProvider().inspect_playlist(PLAYLIST_URL)

    assert [song.title for song in songs] == ["Real Track"]


def test_inspect_playlist_wraps_fetch_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_fetch(kind: str, item_id: str) -> tuple[dict[str, object], int | None]:
        raise RuntimeError("network down")

    monkeypatch.setattr(spotify, "_fetch_entity_and_year", broken_fetch)

    with pytest.raises(MusicShelfError, match="Failed to fetch Spotify playlist"):
        SpotifyProvider().inspect_playlist(PLAYLIST_URL)


def test_inspect_playlist_rejects_empty_playlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        spotify,
        "_fetch_entity_and_year",
        lambda kind, item_id: ({"trackList": []}, None),
    )

    with pytest.raises(ValidationError, match="No tracks found in Spotify playlist"):
        SpotifyProvider().inspect_playlist(PLAYLIST_URL)


def test_other_providers_reject_playlists() -> None:
    with pytest.raises(ValidationError, match="Playlists are not supported"):
        YouTubeMusicProvider().inspect_playlist(PLAYLIST_URL)


def test_playlist_dry_run_uses_individual_album_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    songs = [
        _song("First Song", "Artist One", "Album One", "track-one"),
        _song("Second Song", "Artist Two", "Album Two", "track-two"),
    ]
    monkeypatch.setattr(SpotifyProvider, "inspect_playlist", lambda self, url: songs)

    result = runner.invoke(app, [PLAYLIST_URL, "--dry-run", "-f", "flac"])

    assert result.exit_code == 0
    assert "Spotify (Hybrid)" in result.stdout
    assert "Tracks: 2" in result.stdout
    assert "Artist One/Album One/First Song.flac" in result.stdout.replace(
        str(Path.cwd()), ""
    )
    assert "Artist Two/Album Two/Second Song.flac" in result.stdout.replace(
        str(Path.cwd()), ""
    )
    assert "Road Trip" not in result.stdout


def test_process_playlist_organizes_each_track_by_its_own_album(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    songs = [
        _song("First Song", "Artist One", "Album One", "track-one"),
        _song("Second Song", "Artist Two", "Album Two", "track-two"),
    ]
    monkeypatch.setattr(SpotifyProvider, "inspect_playlist", lambda self, url: songs)

    downloaded: list[str] = []

    def fake_download_tracks(
        self: SpotifyProvider, batch: list[Song], temp_dir: Path
    ) -> list[Song]:
        song = batch[0]
        source = Path(temp_dir) / f"{song.source_id}.m4a"
        source.write_bytes(b"fake audio")
        song.download_path = source
        downloaded.append(song.source_id or "")
        return batch

    def fake_convert(source: Path, fmt: AudioFormat, temp_dir: Path) -> Path:
        destination = Path(temp_dir) / f"{source.stem}-converted.{fmt.value}"
        shutil.copyfile(source, destination)
        return destination

    metadata_written: list[str] = []

    def fake_write_metadata(song: Song) -> None:
        metadata_written.append(song.title)

    monkeypatch.setattr(SpotifyProvider, "download_tracks", fake_download_tracks)
    monkeypatch.setattr(musicshelf.cli, "convert", fake_convert)
    monkeypatch.setattr(musicshelf.cli, "write_metadata", fake_write_metadata)

    result = runner.invoke(app, [PLAYLIST_URL, "-d", str(tmp_path), "-f", "m4a"])

    assert result.exit_code == 0, result.stdout
    assert downloaded == ["track-one", "track-two"]
    assert metadata_written == ["First Song", "Second Song"]
    assert (tmp_path / "Artist One" / "Album One" / "First Song.m4a").exists()
    assert (tmp_path / "Artist Two" / "Album Two" / "Second Song.m4a").exists()
    assert not (tmp_path / "Road Trip").exists()


def test_playlist_all_existing_skips_before_workdir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    songs = [
        _song("First Song", "Artist One", "Album One", "track-one"),
        _song("Second Song", "Artist Two", "Album Two", "track-two"),
    ]
    monkeypatch.setattr(SpotifyProvider, "inspect_playlist", lambda self, url: songs)

    for song in songs:
        target = musicshelf.cli.get_target_path(song, tmp_path, ".m4a")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()

    def fail_if_called(*args: object, **kwargs: object) -> None:
        pytest.fail("Playlist started downloading or created a workdir.")

    monkeypatch.setattr(SpotifyProvider, "download_tracks", fail_if_called)
    monkeypatch.setattr(musicshelf.cli.tempfile, "TemporaryDirectory", fail_if_called)

    result = runner.invoke(app, [PLAYLIST_URL, "-d", str(tmp_path), "-f", "m4a"])

    assert result.exit_code == 0, result.stdout
    assert "All tracks are already in the library." in result.stdout
    assert "Downloaded: 0 | Processed: 0 | Skipped: 2" in result.stdout
