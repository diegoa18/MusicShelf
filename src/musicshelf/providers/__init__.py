from __future__ import annotations

from musicshelf.exceptions import ValidationError
from musicshelf.providers.base import MusicProvider, UrlType
from musicshelf.providers.youtube import YouTubeMusicProvider

_PROVIDERS: tuple[MusicProvider, ...] = (
    YouTubeMusicProvider(),
)


def get_provider(url: str) -> MusicProvider:
    """Resolve and return the matching MusicProvider for a URL."""
    for provider in _PROVIDERS:
        if provider.can_handle(url):
            return provider

    supported = ", ".join(p.name for p in _PROVIDERS)
    raise ValidationError(
        f"Unsupported URL or provider. Currently supported: {supported}."
    )


__all__ = [
    "MusicProvider",
    "UrlType",
    "YouTubeMusicProvider",
    "get_provider",
]
