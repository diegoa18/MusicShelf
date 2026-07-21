from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Song:
    title: str
    artist: str
    album: str
    track: int | None = None
    year: int | None = None
    duration: int | None = None
    cover_url: str | None = None
    source_url: str | None = None
    download_path: Path | None = None
    final_path: Path | None = None
