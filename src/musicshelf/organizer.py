from __future__ import annotations

import re
import shutil
from pathlib import Path

from musicshelf.exceptions import MusicShelfError
from musicshelf.models import Song

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')


def _sanitize(name: str) -> str:
    cleaned = _INVALID_CHARS.sub("", name).strip().replace("..", "")
    return cleaned or "Unknown"

def organize(song: Song, directory: Path) -> Path:
    if not song.final_path or not song.final_path.exists():
        raise MusicShelfError("No audio file to organize")

    target = get_target_path(
        song,
        directory,
        song.final_path.suffix,
    )
    target.parent.mkdir(parents=True, exist_ok=True)

    shutil.move(str(song.final_path), str(target))
    return target

def get_target_path(
    song: Song,
    directory: Path,
    suffix: str,
) -> Path:
    artist = _sanitize(song.artist)
    album = _sanitize(song.album)

    parts: list[str] = []
    if song.track is not None:
        parts.append(f"{song.track:02d}")
    parts.append(_sanitize(song.title))
    filename = " - ".join(parts) + suffix

    target = (directory / artist / album / filename).resolve()
    if not target.is_relative_to(directory.resolve()):
        raise MusicShelfError("Invalid path: attempt to write outside target directory")

    return target
