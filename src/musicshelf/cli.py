from typing import Annotated, Optional
from pathlib import Path

import typer
from rich import print

from musicshelf.converter import AudioFormat, convert
from musicshelf.downloader import download_song
from musicshelf.exceptions import MusicShelfError
from musicshelf.metadata import write_metadata
from musicshelf.organizer import organize

app = typer.Typer(add_completion=False)

@app.command()
def main(
    url: str = typer.Argument(..., help="YTMusic URL"),
    format: Annotated[
        Optional[AudioFormat],
        typer.Option("-f", "--format", help="Output audio format"),
    ] = None,
    directory: Annotated[
        Path,
        typer.Option("-d", "--directory", help="Output directory for organized library"),
    ] = Path("."),
):
    try:
        song = download_song(url)

        print(f"[bold]Title:[/bold] {song.title}")
        print(f"[bold]Artist:[/bold] {song.artist}")
        print(f"[bold]Album:[/bold] {song.album}")
        print(f"[bold]Track:[/bold] {song.track}")
        print(f"[bold]Year:[/bold] {song.year}")
        print(f"[bold]Duration:[/bold] {song.duration}")

        if format and song.download_path:
            song.final_path = convert(song.download_path, format)
            print(f"[green]Converted:[/green] {song.final_path}")
        elif song.download_path:
            song.final_path = song.download_path
            print(f"[green]Downloaded:[/green] {song.download_path}")

        if song.final_path:
            write_metadata(song)
            print(f"[green]Metadata written:[/green] {song.final_path}")

        if song.final_path:
            target = organize(song, directory)
            print(f"[green]Organized:[/green] {target}")

    except MusicShelfError as e:
        print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
