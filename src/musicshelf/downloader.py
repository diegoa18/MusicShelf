from pathlib import Path
import tempfile
from yt_dlp import YoutubeDL
from musicshelf.models import Song


YTDLP_OPTIONS = {
    "quiet": True,
    "no_warnings": True,
}

def download_song(url: str) -> Song:
    temp_dir = Path(tempfile.gettempdir()) / "musicshelf"
    temp_dir.mkdir(parents=True, exist_ok=True)

    options = {
        **YTDLP_OPTIONS,
        "format": "bestaudio/best",
        "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
    }

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        download_path = Path(ydl.prepare_filename(info))

    return Song(
        title=info.get("track") or info.get("title", "Unknown"),
        artist=info.get("artist") or info.get("uploader", "Unknown"),
        album=info.get("album", "Unknown"),
        track=info.get("track_number"),
        year=info.get("release_year"),
        duration=info.get("duration"),
        cover_url=info.get("thumbnail"),
        source_url=url,
        download_path=download_path,
    )
