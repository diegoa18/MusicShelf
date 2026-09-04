from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

import typer
from rich import print

from musicshelf.converter import AudioFormat, convert
from musicshelf.downloader import download_album, download_song, download_tracks
from musicshelf.exceptions import MusicShelfError
from musicshelf.metadata import write_metadata
from musicshelf.organizer import organize
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

        with tempfile.TemporaryDirectory(prefix="musicshelf-") as temp_dir:
            temp_path = Path(temp_dir)
            if url_type == UrlType.ALBUM:
                _process_album(url, format, directory, temp_path)
            else:
                _process_song(url, format, directory, temp_path)

    except MusicShelfError as e:
        print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
