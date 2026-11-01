from __future__ import annotations

import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode, urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from musicshelf.exceptions import MusicShelfError, ValidationError
from musicshelf.models import Song
from musicshelf.providers.base import MusicProvider, UrlType

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
)
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">([^<]+)</script>'
)
_UNKNOWN_ALBUM = "Unknown Album"
_UNKNOWN_ARTIST = "Unknown"
_PLAYLIST_FETCH_WORKERS = 8

# The embed page provides an anonymous Web Player token. Its pathfinder
# endpoint is the same backend the public embed uses and, unlike the embed
# payload, includes each track's album. The persisted-query hash is owned by
# Spotify and may change; all network failures fall back to the embed data.
_PATHFINDER_URL = "https://api-partner.spotify.com/pathfinder/v1/query"
_PATHFINDER_PLAYLIST_HASH = (
    "a65e12194ed5fc443a1cdebed5fabe33ca5b07b987185d63c72483867ad13cb4"
)
_SPOTIFY_ID_RE = re.compile(r"^[0-9A-Za-z]{22}$")
_PATHFINDER_SESSION: dict[str, str] = {}


def _sanitize_ext(ext: str | None) -> str:
    _SAFE = {"webm", "opus", "m4a", "mp3", "ogg", "flac", "wav"}
    if ext and ext.lower() in _SAFE:
        return ext.lower()
    return "webm"


def _extract_year_from_html(html: str) -> int | None:
    match = re.search(r'<meta\s+property=["\']music:release_date["\']\s+content=["\'](\d{4})', html, re.IGNORECASE)
    if match:
        return int(match.group(1))

    match = re.search(r'"datePublished"\s*:\s*"(\d{4})', html)
    if match:
        return int(match.group(1))

    match = re.search(r'content=["\'](\d{4})-\d{2}-\d{2}', html)
    if match:
        return int(match.group(1))

    return None


def _fetch_entity_and_year(kind: str, item_id: str) -> tuple[dict[str, Any], int | None]:
    url = f"https://open.spotify.com/{kind}/{item_id}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    html = ""
    year = None

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            year = _extract_year_from_html(html)
    except URLError:
        pass

    embed_url = f"https://open.spotify.com/embed/{kind}/{item_id}"
    embed_req = urllib.request.Request(embed_url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(embed_req, timeout=15) as resp:
            embed_html = resp.read().decode("utf-8", errors="replace")
            match = _NEXT_DATA_RE.search(embed_html)
            if match:
                payload = json.loads(match.group(1))
                settings = (
                    payload.get("props", {})
                    .get("pageProps", {})
                    .get("state", {})
                    .get("settings", {})
                )
                session = (
                    settings.get("session")
                    if isinstance(settings, dict)
                    else None
                )
                if isinstance(session, dict):
                    token = session.get("accessToken")
                    if isinstance(token, str) and token:
                        _PATHFINDER_SESSION["token"] = token

                entity = payload["props"]["pageProps"]["state"]["data"]["entity"]
                if isinstance(entity, dict):
                    if not year:
                        # Deep search in embed entity if HTML meta didn't catch it
                        year = _extract_year_fallback(entity)
                    return entity, year
    except Exception:
        pass

    if not html:
        raise MusicShelfError("Could not reach Spotify endpoint.")

    return {}, year


def _fetch_pathfinder_playlist(playlist_id: str) -> dict[str, dict[str, Any]]:
    """Fetch playlist tracks with album data from Spotify's public backend.

    The anonymous token comes from the playlist embed. This is a best-effort
    enrichment: if Spotify rotates the persisted-query hash or rejects the
    request, callers continue with the data exposed by the embed itself.
    """
    token = _PATHFINDER_SESSION.get("token")
    if not token or not _SPOTIFY_ID_RE.fullmatch(playlist_id):
        return {}

    variables = {
        "uri": f"spotify:playlist:{playlist_id}",
        "offset": 0,
        "limit": 100,
        "enableWatchFeedEntrypoint": False,
    }
    extensions = {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": _PATHFINDER_PLAYLIST_HASH,
        }
    }
    query = urlencode(
        {
            "operationName": "fetchPlaylist",
            "variables": json.dumps(variables, separators=(",", ":")),
            "extensions": json.dumps(extensions, separators=(",", ":")),
        }
    )
    request = urllib.request.Request(
        f"{_PATHFINDER_URL}?{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": _USER_AGENT,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(
                response.read().decode("utf-8", errors="replace")
            )
    except Exception:
        return {}

    playlist = payload.get("data", {}).get("playlistV2")
    if not isinstance(playlist, dict):
        return {}
    content = playlist.get("content")
    items = content.get("items") if isinstance(content, dict) else None
    if not isinstance(items, list):
        return {}

    tracks: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        wrapper = item.get("itemV2")
        data = wrapper.get("data") if isinstance(wrapper, dict) else None
        if not isinstance(data, dict):
            continue
        uri = data.get("uri")
        if not isinstance(uri, str) or not uri.startswith("spotify:track:"):
            continue

        track_id = uri.rsplit(":", 1)[-1]
        album = data.get("albumOfTrack")
        if not isinstance(album, dict):
            album = {}

        artists: list[dict[str, str]] = []
        for group in (data.get("firstArtist"), data.get("otherArtists")):
            group_items = group.get("items") if isinstance(group, dict) else None
            if not isinstance(group_items, list):
                continue
            for artist in group_items:
                profile = artist.get("profile") if isinstance(artist, dict) else None
                name = profile.get("name") if isinstance(profile, dict) else None
                if isinstance(name, str) and name.strip():
                    artists.append({"name": name.strip()})

        duration = data.get("duration")
        duration_ms = (
            duration.get("totalMilliseconds")
            if isinstance(duration, dict)
            else None
        )
        tracks[track_id] = {
            "title": data.get("name"),
            "artists": artists,
            "album": album,
            "duration": duration_ms,
            "trackNumber": data.get("trackNumber"),
        }

    return tracks


def _extract_year_fallback(entity: dict[str, Any]) -> int | None:
    targets = [entity]
    if isinstance(entity.get("album"), dict):
        targets.append(entity["album"])

    for target in targets:
        for key in (
            "releaseDate",
            "release_date",
            "date",
            "year",
            "originalReleaseDate",
            "release",
        ):
            val = target.get(key)
            if isinstance(val, dict):
                for sub_val in val.values():
                    if isinstance(sub_val, str):
                        match = re.search(r"\b(19\d{2}|20\d{2})\b", sub_val)
                        if match:
                            return int(match.group(1))
            elif isinstance(val, str):
                match = re.search(r"\b(19\d{2}|20\d{2})\b", val)
                if match:
                    return int(match.group(1))
            elif isinstance(val, int) and 1900 <= val <= 2100:
                return val

    return None


def _best_image_url(sources: list[Any]) -> str | None:
    """Return the largest image URL, falling back to the last available one."""
    best_url: str | None = None
    best_width = -1

    for source in sources:
        if not isinstance(source, dict):
            continue
        url = source.get("url")
        if not isinstance(url, str) or not url:
            continue
        width = source.get("maxWidth") or source.get("width") or 0
        if not isinstance(width, int):
            width = 0
        if width >= best_width:
            best_url = url
            best_width = width

    return best_url


def _extract_cover_url(entity: dict[str, Any]) -> str | None:
    visual = entity.get("visualIdentity") or {}
    cover_art = entity.get("coverArt") or {}
    sources = (
        visual.get("image") or cover_art.get("sources") or entity.get("images") or []
    )
    if isinstance(sources, list) and sources:
        url = _best_image_url(sources)
        if url:
            return url

    for key in ("album", "albumOfTrack"):
        nested = entity.get(key)
        if isinstance(nested, dict):
            url = _extract_cover_url(nested)
            if url:
                return url

    return None


def _extract_album_name(source: dict[str, Any]) -> str | None:
    """Extract an album name from any of Spotify's track/album shapes."""
    for key in ("album", "albumOfTrack", "albumName", "collection"):
        value = source.get(key)
        if isinstance(value, str):
            name = value.strip()
            if name:
                return name
        elif isinstance(value, dict):
            for name_key in ("name", "title", "albumName"):
                name = value.get(name_key)
                if isinstance(name, str) and name.strip():
                    return name.strip()

    return None


def _extract_artist_names(source: dict[str, Any]) -> str | None:
    """Extract one or more artist names from a Spotify entity."""
    artists = source.get("artists")
    names: list[str] = []
    if isinstance(artists, list):
        for artist in artists:
            if isinstance(artist, dict):
                name = artist.get("name")
            elif isinstance(artist, str):
                name = artist
            else:
                name = None
            if isinstance(name, str) and name.strip():
                names.append(name.strip())

    if names:
        return ", ".join(names)

    for key in ("artist", "artistName", "subtitle"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


def _extract_date_and_year(value: Any) -> tuple[str | None, int | None]:
    """Normalize Spotify release dates into (YYYY-MM-DD, year)."""
    if isinstance(value, int):
        if 1900 <= value <= 2100:
            return str(value), value
        return None, None

    if isinstance(value, dict):
        for key in ("isoString", "date", "value", "year", "releaseDate"):
            if key in value:
                date, year = _extract_date_and_year(value[key])
                if year:
                    return date, year
        return None, None

    if isinstance(value, str):
        match = re.search(r"\b(19\d{2}|20\d{2})\b", value)
        if not match:
            return None, None
        year = int(match.group(1))
        date_match = re.match(r"\s*(\d{4}-\d{2}-\d{2})", value)
        return (date_match.group(1) if date_match else str(year)), year

    return None, None


def _extract_date_from_source(
    source: dict[str, Any],
) -> tuple[str | None, int | None]:
    for key in (
        "releaseDate",
        "release_date",
        "date",
        "originalReleaseDate",
        "year",
    ):
        if key in source:
            date, year = _extract_date_and_year(source[key])
            if year:
                return date, year

    for key in ("album", "albumOfTrack"):
        nested = source.get(key)
        if isinstance(nested, dict):
            date, year = _extract_date_from_source(nested)
            if year:
                return date, year

    return None, None


def _extract_track_number(source: dict[str, Any]) -> int | None:
    for key in ("trackNumber", "track_number", "track"):
        value = source.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.strip().isdigit():
            number = int(value.strip())
            if number > 0:
                return number

    for key in ("album", "albumOfTrack"):
        nested = source.get(key)
        if isinstance(nested, dict):
            return _extract_track_number(nested)

    return None


def _fetch_playlist_track(
    track_id: str | None,
) -> tuple[dict[str, Any], int | None]:
    """Fetch per-track details, treating failures as non-fatal."""
    if not track_id:
        return {}, None
    try:
        return _fetch_entity_and_year("track", track_id)
    except Exception:
        return {}, None


def _merge_track_details(
    song: Song,
    entity: dict[str, Any],
    entity_year: int | None,
) -> None:
    """Fill missing per-track metadata without overriding playlist data."""
    if not entity:
        if song.year is None and entity_year:
            song.year = entity_year
            song.date = song.date or str(entity_year)
        return

    if song.album == _UNKNOWN_ALBUM:
        album = _extract_album_name(entity)
        if album:
            song.album = album

    if song.artist == _UNKNOWN_ARTIST:
        artist = _extract_artist_names(entity)
        if artist:
            song.artist = artist

    title = entity.get("title") or entity.get("name")
    if isinstance(title, str) and title.strip() and song.title == "Unknown":
        song.title = title.strip()

    if song.year is None:
        date, year = _extract_date_from_source(entity)
        if not year and entity_year:
            date, year = str(entity_year), entity_year
        if year:
            song.year = year
            song.date = song.date or date or str(year)

    if song.duration is None:
        duration_ms = entity.get("duration")
        if isinstance(duration_ms, int) and duration_ms > 0:
            song.duration = duration_ms // 1000

    if not song.cover_url:
        song.cover_url = _extract_cover_url(entity)

    if song.track is None:
        song.track = _extract_track_number(entity)


class SpotifyProvider(MusicProvider):
    """Hybrid Provider: Reads public Spotify embed metadata, resolves audio via YouTube."""

    @property
    def name(self) -> str:
        return "Spotify (Hybrid)"

    @property
    def supported_hosts(self) -> set[str]:
        return {"open.spotify.com", "spotify.com"}

    def detect_url_type(self, url: str) -> UrlType:
        if not self.can_handle(url):
            return UrlType.UNKNOWN

        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if parts and parts[0].startswith("intl-"):
            parts = parts[1:]

        if len(parts) < 2:
            return UrlType.UNKNOWN

        kind = parts[0]
        if kind == "track":
            return UrlType.SONG
        if kind == "album":
            return UrlType.ALBUM
        if kind == "playlist":
            return UrlType.PLAYLIST
        if kind == "artist":
            return UrlType.CHANNEL

        return UrlType.UNKNOWN

    def validate_url(self, url: str) -> UrlType:
        url_type = self.detect_url_type(url)

        if url_type == UrlType.CHANNEL:
            raise ValidationError("Spotify artist profiles are not supported.")
        if url_type == UrlType.UNKNOWN:
            raise ValidationError("Unrecognized Spotify URL format.")

        return url_type

    def _extract_id(self, url: str) -> str:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        return parts[-1]

    def inspect_song(self, url: str) -> Song:
        track_id = self._extract_id(url)
        entity, year_val = _fetch_entity_and_year("track", track_id)

        title = entity.get("title") or entity.get("name") or "Unknown"
        artists = entity.get("artists") or []
        artist = (
            artists[0].get("name", "Unknown")
            if artists and isinstance(artists[0], dict)
            else (entity.get("subtitle") or "Unknown")
        )

        duration_ms = entity.get("duration") or 0

        return Song(
            title=title,
            artist=artist,
            album=entity.get("subtitle") or "Spotify Singles",
            source_id=entity.get("id") or track_id,
            track=1,
            year=year_val,
            date=str(year_val) if year_val else None,
            duration=duration_ms // 1000 if duration_ms else None,
            cover_url=_extract_cover_url(entity),
            source_url=url,
        )

    def inspect_album(self, url: str) -> list[Song]:
        album_id = self._extract_id(url)
        entity, album_year = _fetch_entity_and_year("album", album_id)

        album_name = entity.get("title") or entity.get("name") or "Unknown Album"
        album_artist = entity.get("subtitle") or "Unknown"
        cover_url = _extract_cover_url(entity)

        track_list = entity.get("trackList") or []
        if not track_list:
            raise ValidationError("No tracks found in Spotify album.")

        if not album_year and track_list:
            first_item = track_list[0]
            uri = first_item.get("uri") or ""
            if ":" in uri:
                first_track_id = uri.split(":")[-1]
                try:
                    track_entity, track_year = _fetch_entity_and_year(
                        "track", first_track_id
                    )
                    if track_year:
                        album_year = track_year
                except Exception:
                    pass

        songs: list[Song] = []
        for idx, item in enumerate(track_list, start=1):
            if not isinstance(item, dict):
                continue
            uri = item.get("uri") or ""
            track_id = uri.split(":")[-1] if ":" in uri else f"{album_id}_{idx}"
            duration_ms = item.get("duration") or 0

            songs.append(
                Song(
                    title=item.get("title") or "Unknown",
                    artist=item.get("subtitle") or album_artist,
                    album=album_name,
                    source_id=track_id,
                    track=idx,
                    year=album_year,
                    date=str(album_year) if album_year else None,
                    duration=duration_ms // 1000 if duration_ms else None,
                    cover_url=cover_url,
                    source_url=f"https://open.spotify.com/track/{track_id}",
                )
            )

        return songs

    def inspect_playlist(self, url: str) -> list[Song]:
        """Inspect a playlist through Spotify's public embed payload.

        The public embed exposes at most the first 100 tracks and does not
        include each track's album. Album, release date, cover and track
        number are enriched from the Web Player backend used by the embed;
        individual track embeds fill any remaining gaps. When the album is
        still unavailable it falls back to ``Unknown Album``. The playlist
        name is never used as an album, so tracks keep their own
        ``artist/album`` destination.
        """
        playlist_id = self._extract_id(url)
        _PATHFINDER_SESSION.pop("token", None)
        try:
            entity, _playlist_year = _fetch_entity_and_year("playlist", playlist_id)
        except MusicShelfError:
            raise
        except Exception as exc:
            raise MusicShelfError(
                f"Failed to fetch Spotify playlist metadata: {exc}"
            ) from exc

        track_list = entity.get("trackList") or []
        if not track_list:
            raise ValidationError("No tracks found in Spotify playlist.")

        playlist_cover = _extract_cover_url(entity)
        songs: list[Song] = []
        track_ids: list[str | None] = []

        for idx, item in enumerate(track_list, start=1):
            if not isinstance(item, dict):
                continue

            # Public API-style playlist items wrap the track in a "track"
            # object; embed items are already flat.
            nested_track = item.get("track")
            if isinstance(nested_track, dict):
                item = {**item, **nested_track}

            uri = item.get("uri")
            uri = uri if isinstance(uri, str) else ""
            if uri.startswith("spotify:episode:"):
                continue

            entity_type = item.get("entityType")
            if isinstance(entity_type, str) and entity_type != "track":
                continue

            track_id = uri.split(":")[-1] if uri.startswith("spotify:track:") else None
            if not track_id and isinstance(item.get("id"), str):
                raw_id = item["id"]
                if _SPOTIFY_ID_RE.fullmatch(raw_id):
                    track_id = raw_id

            title = item.get("title") or item.get("name")
            if not isinstance(title, str) or not title.strip():
                if not track_id:
                    continue
                title = "Unknown"

            artist = _extract_artist_names(item) or _UNKNOWN_ARTIST
            album = _extract_album_name(item) or _UNKNOWN_ALBUM
            date, year = _extract_date_from_source(item)

            duration_ms = item.get("duration")
            if not isinstance(duration_ms, int):
                duration_ms = item.get("duration_ms")
            duration = (
                duration_ms // 1000
                if isinstance(duration_ms, int) and duration_ms > 0
                else None
            )

            songs.append(
                Song(
                    title=title.strip(),
                    artist=artist,
                    album=album,
                    source_id=track_id,
                    track=_extract_track_number(item),
                    year=year,
                    date=date or (str(year) if year else None),
                    duration=duration,
                    cover_url=_extract_cover_url(item),
                    source_url=(
                        f"https://open.spotify.com/track/{track_id}"
                        if track_id
                        else f"{url}#track-{idx}"
                    ),
                )
            )
            track_ids.append(track_id)

        if not songs:
            raise ValidationError("No tracks found in Spotify playlist.")

        # The embed's track list has no album. The Web Player backend exposes
        # it for the whole playlist in one request; only tracks still missing
        # data fall back to individual embeds.
        pathfinder_tracks = _fetch_pathfinder_playlist(playlist_id)
        for song in songs:
            if song.source_id and song.source_id in pathfinder_tracks:
                _merge_track_details(song, pathfinder_tracks[song.source_id], None)

        needs_enrichment = [
            index
            for index, song in enumerate(songs)
            if song.album == _UNKNOWN_ALBUM
            or song.date is None
            or song.cover_url is None
        ]
        if needs_enrichment:
            # Per-track embeds are independent requests; fetch them
            # concurrently so a long playlist is not a serial network crawl.
            workers = min(_PLAYLIST_FETCH_WORKERS, len(needs_enrichment))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                details = list(
                    executor.map(
                        _fetch_playlist_track,
                        [track_ids[index] for index in needs_enrichment],
                    )
                )
            for index, (track_entity, track_year) in zip(
                needs_enrichment, details, strict=True
            ):
                _merge_track_details(songs[index], track_entity, track_year)

        for song in songs:
            # Prefer the track's own artwork; the playlist cover is only a
            # last resort when neither backend exposes one.
            if not song.cover_url:
                song.cover_url = playlist_cover

        return songs

    def download_tracks(self, songs: list[Song], temp_dir: Path) -> list[Song]:
        options = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio/best",
            "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
        }

        try:
            with YoutubeDL(options) as ydl:
                for song in songs:
                    if not song.title or not song.artist:
                        continue

                    query = f"ytsearch1:{song.artist} - {song.title} official audio"
                    info = ydl.extract_info(query, download=True)
                    if not info:
                        continue

                    entries = info.get("entries")
                    entry = entries[0] if entries else info
                    yt_id = entry.get("id")
                    ext = _sanitize_ext(entry.get("ext"))

                    if yt_id:
                        song.download_path = temp_dir / f"{yt_id}.{ext}"
        except DownloadError as e:
            raise MusicShelfError(
                f"Failed to resolve audio stream from YouTube: {e.msg}"
            ) from None

        return songs
