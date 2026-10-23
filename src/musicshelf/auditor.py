import os
from pathlib import Path

import mutagen
from rich.console import Console
from rich.table import Table

console = Console()
_SUPPORTED_EXT = {".flac", ".mp3", ".ogg", ".opus", ".m4a"}

def run_audit(directory: Path) -> None:
    if not directory.exists() or not directory.is_dir():
        console.print(f"[bold red]✖ Error:[/bold red] Directory '{directory}' does not exist.")
        return

    console.print(f"[bold cyan]🔎 Auditing library at:[/bold cyan] {directory.resolve()}\n")

    issues = []
    total_files = 0

    for root, _, files in os.walk(directory):
        root_path = Path(root)
        for file in files:
            path = root_path / file
            if path.suffix.lower() not in _SUPPORTED_EXT:
                continue

            total_files += 1
            rel_path = path.relative_to(directory)

            if len(rel_path.parts) < 3:
                issues.append((str(rel_path), "Incorrect structure (Expected: Artist/Album/Track)"))
                continue

            try:
                audio = mutagen.File(path)
                if audio is None:
                    issues.append((str(rel_path), "File corrupted or format not recognized by Mutagen"))
                    continue
                if not audio.tags:
                    issues.append((str(rel_path), "Missing metadata (empty tags)"))
            except Exception:
                issues.append((str(rel_path), "Error reading file"))

    if not issues:
        console.print(f"[bold green]✔ Your library is spotless![/bold green] ({total_files} files checked)")
        return

    console.print(f"[bold red]⚠ Found {len(issues)} anomalies in {total_files} files:[/bold red]")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("File", style="dim")
    table.add_column("Issue", style="red")

    for file_path, issue in issues:
        table.add_row(file_path, issue)

    console.print(table)
