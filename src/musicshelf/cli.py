import typer
from rich import print
from musicshelf.downloader import download_song

app = typer.Typer(add_completion=False)

@app.callback(invoke_without_command=True)
def main(
    url: str = typer.Argument(..., help="YTMusic URL"),
):
    song = download_song(url)

    print(f"[bold]Title:[/bold] {song.title}")
    print(f"[bold]Artist:[/bold] {song.artist}")
    print(f"[bold]Album:[/bold] {song.album}")
    print(f"[bold]Track:[/bold] {song.track}")
    print(f"[bold]Year:[/bold] {song.year}")
    print(f"[bold]Duration:[/bold] {song.duration}")
    print(f"[green]Downloaded:[/green] {song.download_path}")
