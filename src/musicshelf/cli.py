from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

import typer
from rich import print
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from musicshelf.auditor import run_audit
from musicshelf.converter import AudioFormat, convert
from musicshelf.exceptions import MusicShelfError
from musicshelf.metadata import write_metadata
from musicshelf.organizer import get_target_path, organize
from musicshelf.providers import MusicProvider, UrlType, get_provider

console = Console()
app = typer.Typer(add_completion=False)


def _process_song(
    provider: MusicProvider,
    url: str,
    fmt: AudioFormat,
    directory: Path,
    temp_dir: Path,
    overwrite: bool,
) -> None:
    with console.status(
        f"[bold cyan]Fetching metadata from {provider.name}...[/bold cyan]"
    ):
        song = provider.inspect_song(url)

    target = get_target_path(song, directory, f".{fmt.value}")

    if target.exists() and not overwrite:
        print(
            f"[yellow]Skipped:[/yellow] '{song.title}' already exists in the library."
        )
        return

    with console.status(
        f"[bold cyan]Downloading audio from {provider.name}...[/bold cyan]"
    ):
        provider.download_tracks([song], temp_dir)

    print(f"[bold]Title:[/bold] {song.title}")
    print(f"[bold]Artist:[/bold] {song.artist}")
    print(f"[bold]Album:[/bold] {song.album}")
    print(f"[bold]Track:[/bold] {song.track}")
    print(f"[bold]Year:[/bold] {song.year}")
    print(f"[bold]Duration:[/bold] {song.duration}")

    if song.download_path:
        with console.status(f"[bold cyan]Converting to {fmt.value}...[/bold cyan]"):
            song.final_path = convert(song.download_path, fmt, temp_dir)
        print(f"[green]Converted:[/green] {song.final_path}")

    if song.final_path:
        write_metadata(song)
        print(f"[green]Metadata written:[/green] {song.final_path}")

    if song.final_path:
        target = organize(song, directory)
        print(f"[green]Organized:[/green] {target}")


def _process_album(
    provider: MusicProvider,
    url: str,
    fmt: AudioFormat,
    directory: Path,
    temp_dir: Path,
    overwrite: bool,
) -> None:
    with console.status(
        f"[bold cyan]Fetching album metadata from {provider.name}...[/bold cyan]"
    ):
        songs = provider.inspect_album(url)

    album_name = songs[0].album
    artist_name = songs[0].artist
    print(f"[bold]Album:[/bold] {album_name}")
    print(f"[bold]Artist:[/bold] {artist_name}")
    print(f"[bold]Tracks found:[/bold] {len(songs)}")

    pending_songs = []
    for song in songs:
        target = get_target_path(song, directory, f".{fmt.value}")
        if target.exists() and not overwrite:
            print(f"  [yellow]→ Skipped (already exists):[/yellow] {song.title}")
        else:
            pending_songs.append(song)

    if not pending_songs:
        print("\n[green]All tracks are already in the library.[/green]")
        return

    downloaded_songs = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        transient=True,
    ) as progress:
        task = progress.add_task(f"[green]Downloading from {provider.name}...", total=len(pending_songs))

        for song in pending_songs:
            progress.update(task, description=f"[green]Downloading: {song.title}")
            try:
                provider.download_tracks([song], temp_dir)
                if song.download_path and song.download_path.exists():
                    downloaded_songs.append(song)
                else:
                    print(f"\n  [yellow]→ Warning: Download path missing for '{song.title}'[/yellow]")
            except Exception as e:
                print(f"\n  [yellow]→ Warning: Failed to download '{song.title}': {e}[/yellow]")
            progress.advance(task)

    if not downloaded_songs:
        print("\n[bold red]Error: No tracks could be downloaded from this album.[/bold red]")
        return

    print("\n[bold cyan]Processing and organizing tracks...[/bold cyan]")
    for song in downloaded_songs:
        print(f"\n[bold]  → {song.title}[/bold]")
        try:
            if song.download_path:
                with console.status(f"[bold cyan]Converting to {fmt.value}...[/bold cyan]"):
                    song.final_path = convert(song.download_path, fmt, temp_dir)

            if song.final_path:
                write_metadata(song)

            if song.final_path:
                target = organize(song, directory)
                print(f"  [green]→ {target}[/green]")
        except Exception as e:
            print(f"  [red]→ Failed to process {song.title}: {e}[/red]")

    print("\n[bold green]✔ Album processing complete![/bold green]")


def _preview_song(
    provider: MusicProvider,
    url: str,
    fmt: AudioFormat,
    directory: Path,
) -> None:
    song = provider.inspect_song(url)
    target = get_target_path(song, directory, f".{fmt.value}")

    print("[bold]Dry run[/bold]")
    print(f"[bold]Provider:[/bold] {provider.name}")
    print(f"[bold]Title:[/bold] {song.title}")
    print(f"[bold]Artist:[/bold] {song.artist}")
    print(f"[bold]Album:[/bold] {song.album}")
    print(f"[bold]Track:[/bold] {song.track}")
    print(f"[bold]Year:[/bold] {song.year}")
    print(f"[bold]Duration:[/bold] {song.duration}")
    print(f"[bold]Format:[/bold] {fmt.value}")
    print(f"[bold]Output:[/bold] {target}")


def _preview_album(
    provider: MusicProvider,
    url: str,
    fmt: AudioFormat,
    directory: Path,
) -> None:
    songs = provider.inspect_album(url)

    print("[bold]Dry run[/bold]")
    print(f"[bold]Provider:[/bold] {provider.name}")
    print(f"[bold]Album:[/bold] {songs[0].album}")
    print(f"[bold]Artist:[/bold] {songs[0].artist}")
    print(f"[bold]Tracks:[/bold] {len(songs)}")

    for song in songs:
        target = get_target_path(song, directory, f".{fmt.value}")
        print(f"  → {target}")


@app.command()
def main(
    url: Annotated[
        str | None,
        typer.Argument(help="Track or album URL from a supported provider"),
    ] = None,
    format: Annotated[
        AudioFormat,
        typer.Option("-f", "--format", help="Output audio format"),
    ] = AudioFormat.M4A,
    directory: Annotated[
        Path,
        typer.Option(
            "-d", "--directory", help="Output directory for organized library"
        ),
    ] = Path("."),
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Preview changes without downloading or modifying files",
        ),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Overwrite existing files in the library"),
    ] = False,
    audit: Annotated[
        bool,
        typer.Option(
            "--audit",
            help="Audit the current library for misplaced or corrupted files",
        ),
    ] = False,
) -> None:
    if audit:
        run_audit(directory)
        raise typer.Exit(0)
    if not url:
        print(
            "[bold red]✖ Error:[/bold red] "
            "You must provide a URL or use the --audit flag."
        )
        raise typer.Exit(1)

    try:
        provider = get_provider(url)
        url_type = provider.validate_url(url)

        if url_type == UrlType.ALBUM:
            if dry_run:
                _preview_album(provider, url, format, directory)
            else:
                with tempfile.TemporaryDirectory(prefix="musicshelf-") as temp_dir:
                    _process_album(
                        provider, url, format, directory, Path(temp_dir), overwrite
                    )
        else:
            if dry_run:
                _preview_song(provider, url, format, directory)
            else:
                with tempfile.TemporaryDirectory(prefix="musicshelf-") as temp_dir:
                    _process_song(
                        provider, url, format, directory, Path(temp_dir), overwrite
                    )

    except MusicShelfError as e:
        print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
