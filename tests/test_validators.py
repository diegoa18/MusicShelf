import pytest

from musicshelf.validators import UrlType, detect_url_type


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
def test_detect_url_type(url: str, expected: UrlType):
    assert detect_url_type(url) == expected
