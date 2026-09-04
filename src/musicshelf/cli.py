from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

import typer
from rich import print

from musicshelf.converter import AudioFormat, convert
from musicshelf.downloader import (
    download_album,
    download_song,
    download_tracks,
    inspect_song,
)
from musicshelf.exceptions import MusicShelfError
from musicshelf.metadata import write_metadata
from musicshelf.organizer import get_target_path, organize
from musicshelf.validators import UrlType, detect_url_type

app = typer.Typer(add_completion=False)

def _process_song(
    url: str,
    fmt: AudioFormat,
    directory: Path,
    temp_dir: Path,
) -> None:
    song = download_song(url, temp_dir)

    print(f"[bold]Title:[/bold] {song.title}")
    print(f"[bold]Artist:[/bold] {song.artist}")
    print(f"[bold]Album:[/bold] {song.album}")
    print(f"[bold]Track:[/bold] {song.track}")
    print(f"[bold]Year:[/bold] {song.year}")
    print(f"[bold]Duration:[/bold] {song.duration}")

    if song.download_path:
        song.final_path = convert(song.download_path, fmt, temp_dir)
        print(f"[green]Converted:[/green] {song.final_path}")

    if song.final_path:
        write_metadata(song)
        print(f"[green]Metadata written:[/green] {song.final_path}")

    if song.final_path:
        target = organize(song, directory)
        print(f"[green]Organized:[/green] {target}")


def _process_album(
    url: str,
    fmt: AudioFormat,
    directory: Path,
    temp_dir: Path,
) -> None:
    songs = download_album(url)

    album_name = songs[0].album
    artist_name = songs[0].artist
    print(f"[bold]Album:[/bold] {album_name}")
    print(f"[bold]Artist:[/bold] {artist_name}")
    print(f"[bold]Tracks:[/bold] {len(songs)}")

    songs = download_tracks(songs, temp_dir)

    for song in songs:
        print(f"\n[bold]  → {song.title}[/bold]")

        if song.download_path:
            song.final_path = convert(song.download_path, fmt, temp_dir)

        if song.final_path:
            write_metadata(song)

        if song.final_path:
            target = organize(song, directory)
            print(f"  [green]→ {target}[/green]")


def _preview_song(
    url: str,
    fmt: AudioFormat,
    directory: Path,
) -> None:
    song = inspect_song(url)
    target = get_target_path(song, directory, f".{fmt.value}",)

    print("[bold]Dry run[/bold]")
    print(f"[bold]Title:[/bold] {song.title}")
    print(f"[bold]Artist:[/bold] {song.artist}")
    print(f"[bold]Album:[/bold] {song.album}")
    print(f"[bold]Track:[/bold] {song.track}")
    print(f"[bold]Year:[/bold] {song.year}")
    print(f"[bold]Duration:[/bold] {song.duration}")
    print(f"[bold]Format:[/bold] {fmt.value}")
    print(f"[bold]Output:[/bold] {target}")

def _preview_album(
    url: str,
    fmt: AudioFormat,
    directory: Path,
) -> None:
    songs = download_album(url)

    print("[bold]Dry run[/bold]")
    print(f"[bold]Album:[/bold] {songs[0].album}")
    print(f"[bold]Artist:[/bold] {songs[0].artist}")
    print(f"[bold]Tracks:[/bold] {len(songs)}")

    for song in songs:
        target = get_target_path(song, directory, f".{fmt.value}",)
        print(f"  → {target}")


@app.command()
def main(
    url: str = typer.Argument(..., help="YTMusic URL"),
    format: Annotated[
        AudioFormat,
        typer.Option("-f", "--format", help="Output audio format"),
    ] = AudioFormat.M4A,
    directory: Annotated[
        Path,
        typer.Option("-d", "--directory", help="Output directory for organized library"),
    ] = Path("."),
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview changes without downloading or modifying files"),
    ] = False,
):
    try:
        url_type = detect_url_type(url)

        if url_type == UrlType.CHANNEL:
            raise MusicShelfError(
                "Channel URLs are not supported. Use a song or album URL instead."
            )

        if url_type == UrlType.PLAYLIST:
            raise MusicShelfError(
                "User playlists are not supported. Use an official album URL instead."
            )

        if url_type == UrlType.UNKNOWN:
            raise MusicShelfError("Unrecognized YouTube Music URL.")

        if url_type == UrlType.ALBUM:
            if dry_run:
                _preview_album(url, format, directory)
            else:
                with tempfile.TemporaryDirectory(prefix="musicshelf-") as temp_dir:
                    _process_album(url, format, directory, Path(temp_dir))
        else:
            if dry_run:
                _preview_song(url, format, directory)
            else:
                with tempfile.TemporaryDirectory(prefix="musicshelf-") as temp_dir:
                    _process_song(url, format, directory, Path(temp_dir))

    except MusicShelfError as e:
        print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
