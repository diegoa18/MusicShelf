from __future__ import annotations
import shutil
import subprocess
from enum import StrEnum
from pathlib import Path
from musicshelf.exceptions import ConversionError

class AudioFormat(StrEnum):
    FLAC = "flac"
    MP3 = "mp3"
    OPUS = "opus"
    WAV = "wav"
    M4A = "m4a"
    OGG = "ogg"


_FORMAT_ARGS: dict[AudioFormat, list[str]] = {
    AudioFormat.FLAC: ["-codec:a", "flac"],
    AudioFormat.MP3: ["-codec:a", "libmp3lame", "-b:a", "320k"],
    AudioFormat.OPUS: ["-codec:a", "libopus", "-b:a", "128k"],
    AudioFormat.WAV: ["-codec:a", "pcm_s16le"],
    AudioFormat.M4A: ["-f", "mp4", "-codec:a", "aac", "-b:a", "256k"],
    AudioFormat.OGG: ["-codec:a", "libvorbis", "-b:a", "256k"],
}

def convert(source: Path, fmt: AudioFormat) -> Path:
    if not source.exists():
        raise ConversionError(f"Source file not found: {source}")

    if shutil.which("ffmpeg") is None:
        raise ConversionError("ffmpeg is not installed or not in PATH")

    output = source.with_suffix(f".{fmt.value}")
    args = [
        "ffmpeg",
        "-y",
        "-i", str(source),
        *_FORMAT_ARGS[fmt],
        "-hide_banner",
        "-loglevel", "error",
        str(output),
    ]

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise ConversionError(f"ffmpeg failed: {result.stderr.strip()}")

    source.unlink()
    return output
