"""Google Places API (New) provider — better data, needs an API key.

Set ``GOOGLE_MAPS_API_KEY`` (or pass ``--google-api-key``). Text Search returns
at most 60 places per query (3 pages of 20), so for large countries search
city by city (``--city Jakarta --city Surabaya ...``).
"""

from __future__ import annotations

import os
import time
from typing import Iterator, Optional

from ..http import new_session, request_with_retry
from ..models import Lead
from .base import Provider, ProviderError, SearchQuery

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.addressComponents",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.websiteUri",
        "places.rating",
        "places.userRatingCount",
        "places.googleMapsUri",
        "places.primaryTypeDisplayName",
        "places.types",
        "places.location",
        "places.businessStatus",
        "nextPageToken",
    ]
)
PAGE_SIZE = 20
MAX_PAGES = 3


class GooglePlacesProvider(Provider):
    name = "google"

    def __init__(self, api_key: Optional[str] = None, session=None, language: str = "en"):
        self.api_key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY", "")
        if not self.api_key:
            raise ProviderError(
                "Google Places butuh API key: set env GOOGLE_MAPS_API_KEY atau pakai --google-api-key"
            )
        self.session = session or new_session()
        self.language = language

    def search(self, query: SearchQuery, max_results: Optional[int] = None) -> Iterator[Lead]:
        body = {
            "textQuery": f"{query.sector} in {query.location}",
            "pageSize": PAGE_SIZE,
            "languageCode": self.language,
        }
        headers = {"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": FIELD_MASK}
        for page in range(MAX_PAGES):
            resp = request_with_retry(self.session, "POST", SEARCH_URL, json=body, headers=headers, timeout=30)
            data = resp.json()
            for place in data.get("places", []):
                if place.get("businessStatus") == "CLOSED_PERMANENTLY":
                    continue
                yield place_to_lead(place, query)
            token = data.get("nextPageToken")
            if not token:
                return
            body = {**body, "pageToken": token}
            time.sleep(1)  # the next page token needs a moment to become valid


def place_to_lead(place: dict, query: SearchQuery) -> Lead:
    city = query.city
    for comp in place.get("addressComponents", []):
        types = comp.get("types", [])
        if "locality" in types or ("administrative_area_level_2" in types and not city):
            city = comp.get("longText") or comp.get("shortText") or city
            if "locality" in types:
                break
    location = place.get("location") or {}
    category = (place.get("primaryTypeDisplayName") or {}).get("text", "")
    types = place.get("types") or []
    return Lead(
        source="google",
        source_id=place["id"],
        name=(place.get("displayName") or {}).get("text", ""),
        sector=query.sector,
        country=query.country,
        city=city,
        address=place.get("formattedAddress", ""),
        phone=place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber", ""),
        website=place.get("websiteUri", ""),
        latitude=location.get("latitude"),
        longitude=location.get("longitude"),
        rating=place.get("rating"),
        review_count=place.get("userRatingCount"),
        maps_url=place.get("googleMapsUri", ""),
        categories=";".join([category] + types if category else types),
    )
