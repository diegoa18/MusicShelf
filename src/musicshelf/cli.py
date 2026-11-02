from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer
from rich import print
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from musicshelf.auditor import run_audit
from musicshelf.converter import AudioFormat, convert
from musicshelf.exceptions import MusicShelfError
from musicshelf.metadata import write_metadata
from musicshelf.models import Song
from musicshelf.organizer import get_target_path, organize
from musicshelf.providers import MusicProvider, UrlType, get_provider

console = Console()
app = typer.Typer(add_completion=False)


def _partition_songs(
    songs: list[Song],
    directory: Path,
    fmt: AudioFormat,
    overwrite: bool,
) -> tuple[list[Song], int]:
    """Split songs into pending downloads and already-present tracks.

    Existing targets are reported immediately so the caller only has to
    handle the pending batch. Keeping this in one place guarantees the
    same skip semantics for songs, albums and playlists.
    """
    pending: list[Song] = []
    skipped = 0

    for song in songs:
        target = get_target_path(song, directory, f".{fmt.value}")
        if target.exists() and not overwrite:
            console.print(
                f"  [yellow]↷ Skipping (already exists in the library):[/yellow] "
                f"{target}",
                soft_wrap=True,
            )
            skipped += 1
        else:
            pending.append(song)

    return pending, skipped


@contextmanager
def _temporary_workdir(temp_dir: Path | None) -> Iterator[Path]:
    """Use the caller's work dir or create one only when it is needed."""
    if temp_dir is not None:
        yield temp_dir
        return

    with tempfile.TemporaryDirectory(prefix="musicshelf-") as created:
        yield Path(created)


def _print_summary(downloaded: int, processed: int, skipped: int) -> None:
    print(
        f"\n[bold]Summary:[/bold] Downloaded: {downloaded} | "
        f"Processed: {processed} | Skipped: {skipped}"
    )


def _process_song(
    provider: MusicProvider,
    url: str,
    fmt: AudioFormat,
    directory: Path,
    temp_dir: Path | None = None,
    overwrite: bool = False,
) -> None:
    with console.status(
        f"[bold cyan]Fetching metadata from {provider.name}...[/bold cyan]"
    ):
        song = provider.inspect_song(url)

    pending_songs, skipped = _partition_songs([song], directory, fmt, overwrite)

    if not pending_songs:
        print("[green]Track is already in the library.[/green]")
        _print_summary(0, 0, skipped)
        return

    song = pending_songs[0]
    downloaded = 0
    processed = 0

    try:
        with _temporary_workdir(temp_dir) as work_dir:
            with console.status(
                f"[bold cyan]Downloading audio from {provider.name}...[/bold cyan]"
            ):
                provider.download_tracks([song], work_dir)

            if song.download_path and song.download_path.exists():
                downloaded = 1

            print(f"[bold]Title:[/bold] {song.title}")
            print(f"[bold]Artist:[/bold] {song.artist}")
            print(f"[bold]Album:[/bold] {song.album}")
            print(f"[bold]Track:[/bold] {song.track}")
            print(f"[bold]Year:[/bold] {song.year}")
            print(f"[bold]Duration:[/bold] {song.duration}")

            if song.download_path:
                with console.status(
                    f"[bold cyan]Converting to {fmt.value}...[/bold cyan]"
                ):
                    song.final_path = convert(song.download_path, fmt, work_dir)
                print(f"[green]Converted:[/green] {song.final_path}")

            if song.final_path:
                write_metadata(song)
                print(f"[green]Metadata written:[/green] {song.final_path}")

            if song.final_path:
                target = organize(song, directory)
                processed = 1
                print(f"[green]Organized:[/green] {target}")
    finally:
        _print_summary(downloaded, processed, skipped)


def _process_album(
    provider: MusicProvider,
    url: str,
    fmt: AudioFormat,
    directory: Path,
    temp_dir: Path | None = None,
    overwrite: bool = False,
) -> None:
    with console.status(
        f"[bold cyan]Fetching album metadata from {provider.name}...[/bold cyan]"
    ):
        songs = provider.inspect_album(url)

    album_name = songs[0].album
    artist_name = songs[0].artist
    album_year = songs[0].year

    print(f"[bold]Album:[/bold] {album_name}")
    print(f"[bold]Artist:[/bold] {artist_name}")
    print(f"[bold]Year:[/bold] {album_year}")
    print(f"[bold]Tracks found:[/bold] {len(songs)}")

    pending_songs, skipped = _partition_songs(songs, directory, fmt, overwrite)

    if not pending_songs:
        print("\n[green]All tracks are already in the library.[/green]")
        _print_summary(0, 0, skipped)
        return

    downloaded_songs: list[Song] = []
    processed = 0

    with _temporary_workdir(temp_dir) as work_dir:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task(
                f"[green]Downloading from {provider.name}...",
                total=len(pending_songs),
            )

            for song in pending_songs:
                progress.update(task, description=f"[green]Downloading: {song.title}")
                try:
                    provider.download_tracks([song], work_dir)
                    if song.download_path and song.download_path.exists():
                        downloaded_songs.append(song)
                    else:
                        print(
                            f"\n  [yellow]→ Warning: Download path missing for "
                            f"'{song.title}'[/yellow]"
                        )
                except Exception as e:
                    print(
                        f"\n  [yellow]→ Warning: Failed to download "
                        f"'{song.title}': {e}[/yellow]"
                    )
                progress.advance(task)

        if not downloaded_songs:
            print(
                "\n[bold red]Error: No tracks could be downloaded from this "
                "album.[/bold red]"
            )
            _print_summary(0, processed, skipped)
            return

        print("\n[bold cyan]Processing and organizing tracks...[/bold cyan]")
        for song in downloaded_songs:
            print(f"\n[bold]  → {song.title}[/bold]")
            try:
                if song.download_path:
                    with console.status(
                        f"[bold cyan]Converting to {fmt.value}...[/bold cyan]"
                    ):
                        song.final_path = convert(song.download_path, fmt, work_dir)

                if song.final_path:
                    write_metadata(song)

                if song.final_path:
                    target = organize(song, directory)
                    processed += 1
                    print(f"  [green]→ {target}[/green]")
            except Exception as e:
                print(f"  [red]→ Failed to process {song.title}: {e}[/red]")

    _print_summary(len(downloaded_songs), processed, skipped)
    print("\n[bold green]✔ Album processing complete![/bold green]")


def _process_playlist(
    provider: MusicProvider,
    url: str,
    fmt: AudioFormat,
    directory: Path,
    temp_dir: Path | None = None,
    overwrite: bool = False,
) -> None:
    with console.status(
        f"[bold cyan]Fetching playlist metadata from {provider.name}...[/bold cyan]"
    ):
        songs = provider.inspect_playlist(url)

    if not songs:
        print("[yellow]No tracks found in this playlist.[/yellow]")
        return

    artists = {song.artist for song in songs}
    albums = {(song.artist, song.album) for song in songs}

    print(f"[bold]Playlist:[/bold] {url}")
    print(f"[bold]Tracks found:[/bold] {len(songs)}")
    print(f"[bold]Artists:[/bold] {len(artists)}")
    print(f"[bold]Albums:[/bold] {len(albums)}")

    pending_songs, skipped = _partition_songs(songs, directory, fmt, overwrite)

    if not pending_songs:
        print("\n[green]All tracks are already in the library.[/green]")
        _print_summary(0, 0, skipped)
        return

    downloaded_songs: list[Song] = []
    processed = 0

    with _temporary_workdir(temp_dir) as work_dir:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task(
                f"[green]Downloading from {provider.name}...",
                total=len(pending_songs),
            )

            for song in pending_songs:
                progress.update(task, description=f"[green]Downloading: {song.title}")
                try:
                    provider.download_tracks([song], work_dir)
                    if song.download_path and song.download_path.exists():
                        downloaded_songs.append(song)
                    else:
                        print(
                            f"\n  [yellow]→ Warning: Download path missing for "
                            f"'{song.title}'[/yellow]"
                        )
                except MusicShelfError as e:
                    print(
                        f"\n  [yellow]→ Warning: Failed to download "
                        f"'{song.title}': {e}[/yellow]"
                    )
                except Exception as e:
                    print(
                        f"\n  [yellow]→ Warning: Failed to download "
                        f"'{song.title}': {e}[/yellow]"
                    )
                finally:
                    progress.advance(task)

        if not downloaded_songs:
            print(
                "\n[bold red]Error: No tracks could be downloaded from this "
                "playlist.[/bold red]"
            )
            _print_summary(0, processed, skipped)
            return

        print("\n[bold cyan]Processing and organizing tracks...[/bold cyan]")
        for song in downloaded_songs:
            print(f"\n[bold]  → {song.artist} — {song.album}: {song.title}[/bold]")
            try:
                if song.download_path:
                    with console.status(
                        f"[bold cyan]Converting to {fmt.value}...[/bold cyan]"
                    ):
                        song.final_path = convert(song.download_path, fmt, work_dir)

                if song.final_path:
                    write_metadata(song)

                if song.final_path:
                    target = organize(song, directory)
                    processed += 1
                    print(f"  [green]→ {target}[/green]")
            except MusicShelfError as e:
                print(f"  [red]→ Failed to process {song.title}: {e}[/red]")
            except Exception as e:
                print(f"  [red]→ Failed to process {song.title}: {e}[/red]")

    _print_summary(len(downloaded_songs), processed, skipped)
    print("\n[bold green]✔ Playlist processing complete![/bold green]")


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
    print(f"[bold]Year:[/bold] {songs[0].year}")
    print(f"[bold]Tracks:[/bold] {len(songs)}")

    for song in songs:
        target = get_target_path(song, directory, f".{fmt.value}")
        print(f"  → {target}")


def _preview_playlist(
    provider: MusicProvider,
    url: str,
    fmt: AudioFormat,
    directory: Path,
) -> None:
    songs = provider.inspect_playlist(url)

    artists = {song.artist for song in songs}
    albums = {(song.artist, song.album) for song in songs}

    print("[bold]Dry run[/bold]")
    print(f"[bold]Provider:[/bold] {provider.name}")
    print(f"[bold]Tracks:[/bold] {len(songs)}")
    print(f"[bold]Artists:[/bold] {len(artists)}")
    print(f"[bold]Albums:[/bold] {len(albums)}")

    for song in songs:
        target = get_target_path(song, directory, f".{fmt.value}")
        console.print(f"  → {target}", soft_wrap=True)


@app.command()
def main(
    url: Annotated[
        str | None,
        typer.Argument(help="Track, album, or playlist URL from a supported provider"),
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
                _process_album(provider, url, format, directory, None, overwrite)
        elif url_type == UrlType.PLAYLIST:
            if dry_run:
                _preview_playlist(provider, url, format, directory)
            else:
                _process_playlist(provider, url, format, directory, None, overwrite)
        else:
            if dry_run:
                _preview_song(provider, url, format, directory)
            else:
                _process_song(provider, url, format, directory, None, overwrite)

    except MusicShelfError as e:
        print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
