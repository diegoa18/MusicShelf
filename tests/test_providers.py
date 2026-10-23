import pytest

from musicshelf.exceptions import ValidationError
from musicshelf.providers import UrlType, YouTubeMusicProvider, get_provider


@pytest.fixture
def yt_provider() -> YouTubeMusicProvider:
    return YouTubeMusicProvider()


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://music.youtube.com/watch?v=v-YQ6Idf3qU", UrlType.SONG),
        ("https://music.youtube.com/watch?v=v-YQ6Idf3qU&si=xyz", UrlType.SONG),
        ("https://music.youtube.com/watch?si=xyz&v=v-YQ6Idf3qU", UrlType.SONG),
        ("https://music.youtube.com/playlist?list=OLAK5uy_abc123", UrlType.ALBUM),
        ("https://music.youtube.com/playlist?list=PL123456", UrlType.PLAYLIST),
        ("https://music.youtube.com/@artista", UrlType.CHANNEL),
        ("https://youtube.com/watch?v=v-YQ6Idf3qU", UrlType.UNKNOWN),
        ("https://evil.example/music.youtube.com/watch?v=abc", UrlType.UNKNOWN),
        ("https://music.youtube.com/watch", UrlType.UNKNOWN),
    ],
)
def test_youtube_detect_url_type(
    yt_provider: YouTubeMusicProvider, url: str, expected: UrlType
) -> None:
    assert yt_provider.detect_url_type(url) == expected


def test_get_provider_resolves_youtube() -> None:
    provider = get_provider("https://music.youtube.com/watch?v=v-YQ6Idf3qU")
    assert isinstance(provider, YouTubeMusicProvider)
    assert provider.name == "YouTube Music"


@pytest.mark.parametrize(
    "unsupported_url",
    [
        "https://youtube.com/watch?v=v-YQ6Idf3qU",
        "https://evil.example/music.youtube.com/watch?v=abc",
        "ftp://music.youtube.com/watch?v=abc",
    ],
)
def test_get_provider_rejects_unsupported_domains(unsupported_url: str) -> None:
    with pytest.raises(ValidationError, match="Unsupported URL or provider"):
        get_provider(unsupported_url)


@pytest.mark.parametrize(
    "invalid_url, expected_message",
    [
        (
            "https://music.youtube.com/@artista",
            "Channel URLs are not supported",
        ),
        (
            "https://music.youtube.com/playlist?list=PL123456",
            "User playlists are not supported",
        ),
        (
            "https://music.youtube.com/watch",
            "Unrecognized YouTube Music URL",
        ),
    ],
)
def test_youtube_validate_url_rejects_invalid_types(
    yt_provider: YouTubeMusicProvider, invalid_url: str, expected_message: str
) -> None:
    with pytest.raises(ValidationError, match=expected_message):
        yt_provider.validate_url(invalid_url)
