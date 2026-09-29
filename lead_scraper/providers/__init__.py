import os

from .base import Provider, ProviderError, SearchQuery
from .google_places import GooglePlacesProvider
from .osm import OSMProvider

PROVIDERS = ("auto", "osm", "google")


def get_provider(name: str, google_api_key: str = "") -> Provider:
    """`auto` uses Google Places when an API key is available, else OSM."""
    if name == "auto":
        name = "google" if (google_api_key or os.environ.get("GOOGLE_MAPS_API_KEY")) else "osm"
    if name == "google":
        return GooglePlacesProvider(api_key=google_api_key or None)
    if name == "osm":
        return OSMProvider()
    raise ProviderError(f"Provider tidak dikenal: {name}")


__all__ = [
    "PROVIDERS",
    "GooglePlacesProvider",
    "OSMProvider",
    "Provider",
    "ProviderError",
    "SearchQuery",
    "get_provider",
]
