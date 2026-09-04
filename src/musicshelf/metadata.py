from __future__ import annotations

import base64
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TRCK
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from musicshelf.exceptions import MusicShelfError
from musicshelf.models import Song

_MIME_SIGNATURES: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG": "image/png",
    b"RIFF": "image/webp",
}
DEFAULT_MIME = "image/jpeg"
_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
_FETCH_TIMEOUT = 15
_MAX_COVER_SIZE = 10 * 1024 * 1024  # 10 MB


def _fetch_cover(url: str) -> tuple[bytes, str] | None:
    if not url.startswith("https://"):
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            data = resp.read(_MAX_COVER_SIZE + 1)
            if len(data) > _MAX_COVER_SIZE:
                return None
        return data, _detect_mime(data)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None

def _detect_mime(data: bytes) -> str:
    for sig, mime in _MIME_SIGNATURES.items():
        if data[: len(sig)] == sig:
            return mime
    return DEFAULT_MIME

def _build_vorbis_picture_block(data: bytes, mime: str) -> bytes:
    pic = Picture()
    pic.type = 3
    pic.mime = mime
    pic.data = data
    return base64.b64encode(pic.write())

def _write_vorbis_tags(audio: OggVorbis | OggOpus, song: Song) -> None:
    audio.clear()
    audio["title"] = [song.title]
    audio["artist"] = [song.artist]
    audio["album"] = [song.album]
    if song.year:
        audio["date"] = [str(song.year)]
    if song.track:
        audio["tracknumber"] = [str(song.track)]

def _write_flac(song: Song, path: Path, cover: tuple[bytes, str] | None) -> None:
    audio = FLAC(path)
    audio.clear()
    audio["title"] = song.title
    audio["artist"] = song.artist
    audio["album"] = song.album
    if song.year:
        audio["date"] = str(song.year)
    if song.track:
        audio["tracknumber"] = str(song.track)
    if cover:
        data, mime = cover
        pic = Picture()
        pic.type = 3
        pic.mime = mime
        pic.data = data
        audio.add_picture(pic)
    audio.save()

def _write_mp3(song: Song, path: Path, cover: tuple[bytes, str] | None) -> None:
    audio = ID3(path)
    audio.delete()
    audio.add(TIT2(encoding=3, text=[song.title]))
    audio.add(TPE1(encoding=3, text=[song.artist]))
    audio.add(TALB(encoding=3, text=[song.album]))
    if song.year:
        audio.add(TDRC(encoding=3, text=[str(song.year)]))
    if song.track:
        audio.add(TRCK(encoding=3, text=[str(song.track)]))
    if cover:
        data, mime = cover
        audio.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
    audio.save()

def _write_vorbis(song: Song, path: Path, cover: tuple[bytes, str] | None) -> None:
    audio = OggVorbis(path)
    _write_vorbis_tags(audio, song)
    if cover:
        data, mime = cover
        audio.add_picture(Picture(type=3, mime=mime, data=data))
    audio.save()

def _write_opus(song: Song, path: Path, cover: tuple[bytes, str] | None) -> None:
    audio = OggOpus(path)
    _write_vorbis_tags(audio, song)
    if cover:
        data, mime = cover
        block = _build_vorbis_picture_block(data, mime)
        audio["METADATA_BLOCK_PICTURE"] = [block.decode("ascii")]
    audio.save()

def _write_m4a(song: Song, path: Path, cover: tuple[bytes, str] | None) -> None:
    audio = MP4(path)
    audio.delete()
    audio["\xa9nam"] = [song.title]
    audio["\xa9ART"] = [song.artist]
    audio["\xa9alb"] = [song.album]
    if song.year:
        audio["\xa9day"] = [str(song.year)]
    if song.track:
        audio["trkn"] = [(song.track, 0)]
    if cover:
        data, mime = cover
        fmt = MP4Cover.FORMAT_JPEG if "jpeg" in mime else MP4Cover.FORMAT_PNG
        audio["covr"] = [MP4Cover(data, imageformat=fmt)]
    audio.save()

_SUPPORTED: dict[str, Callable[..., None]] = {
    ".flac": _write_flac,
    ".mp3": _write_mp3,
    ".ogg": _write_vorbis,
    ".opus": _write_opus,
    ".m4a": _write_m4a,
}

_SKIP_METADATA: set[str] = {".wav"}

def write_metadata(song: Song) -> None:
    path = song.final_path or song.download_path
    if not path or not path.exists():
        raise MusicShelfError("No audio file to write metadata to")

    ext = path.suffix.lower()

    if ext in _SKIP_METADATA:
        return

    writer = _SUPPORTED.get(ext)
    if writer is None:
        raise MusicShelfError(f"Unsupported format for metadata: {ext}")

    cover = _fetch_cover(song.cover_url) if song.cover_url else None
    writer(song, path, cover)
