from __future__ import annotations

import re
import shutil
from pathlib import Path

from musicshelf.exceptions import MusicShelfError
from musicshelf.models import Song

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')


def _sanitize(name: str) -> str:
    cleaned = _INVALID_CHARS.sub("", name).strip()
    return cleaned or "Unknown"


def organize(song: Song, directory: Path) -> Path:
    if not song.final_path or not song.final_path.exists():
        raise MusicShelfError("No audio file to organize")

    artist = _sanitize(song.artist)
    album = _sanitize(song.album)

    parts: list[str] = []
    if song.track is not None:
        parts.append(f"{song.track:02d}")
    parts.append(_sanitize(song.title))
    filename = " - ".join(parts) + song.final_path.suffix

    target = directory / artist / album / filename
    target.parent.mkdir(parents=True, exist_ok=True)

    shutil.move(str(song.final_path), str(target))
    return target
