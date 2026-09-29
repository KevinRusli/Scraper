"""OpenStreetMap provider (free, no API key).

1. The country (and optional city) is geocoded with Nominatim to an OSM
   boundary.
2. Businesses matching the sector's OSM tags inside that boundary are fetched
   from the Overpass API.

Overpass returns elements sorted by id, so results are stable between runs.
The caller asks for ``already_seen + wanted`` results, which guarantees there
are always enough never-seen-before leads in the response (as long as the
area still has unseen businesses).
"""

from __future__ import annotations

import re
import time
from typing import Dict, Iterator, List, Optional, Tuple

from ..http import new_session, request_with_retry
from ..models import Lead
from ..sectors import resolve_sector
from .base import Provider, ProviderError, SearchQuery

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
AREA_OFFSET = 3_600_000_000  # Overpass area id = relation id + 3.6e9
BUSINESS_KEYS = "shop|amenity|office|craft|tourism|healthcare|leisure"
DEFAULT_MAX_RESULTS = 2000


class OSMProvider(Provider):
    name = "osm"

    def __init__(self, session=None, overpass_urls: Optional[List[str]] = None, timeout: int = 180):
        self.session = session or new_session()
        self.overpass_urls = overpass_urls or OVERPASS_URLS
        self.timeout = timeout
        self._last_nominatim = 0.0

    # ------------------------------------------------------------ geocoding
    def _nominatim(self, params: Dict[str, str]) -> List[dict]:
        # Nominatim usage policy: max 1 request per second.
        wait = 1.0 - (time.monotonic() - self._last_nominatim)
        if wait > 0:
            time.sleep(wait)
        params = {"format": "jsonv2", "limit": "10", "addressdetails": "1", **params}
        resp = request_with_retry(self.session, "GET", NOMINATIM_URL, params=params, timeout=30)
        self._last_nominatim = time.monotonic()
        return resp.json()

    def resolve_area(self, query: SearchQuery) -> Tuple[str, str]:
        """Return (overpass_filter, display_name) for the search area.

        The filter is either ``area.a`` (with an area statement prepended by
        :meth:`build_query`) or a bbox ``(s,w,n,e)``.
        """
        if query.city:
            results = self._nominatim({"city": query.city, "country": query.country})
            if not results:
                results = self._nominatim({"q": query.location})
        else:
            results = self._nominatim({"country": query.country, "featureType": "country"})
            if not results:
                results = self._nominatim({"q": query.country})
        if not results:
            raise ProviderError(f"Lokasi tidak ditemukan di OpenStreetMap: {query.location}")

        for item in results:
            if item.get("osm_type") == "relation":
                return f"area:{AREA_OFFSET + int(item['osm_id'])}", item.get("display_name", "")
        # No boundary relation (e.g. the city is only a node): fall back to bbox.
        item = results[0]
        south, north, west, east = (float(v) for v in item["boundingbox"])
        return f"bbox:{south},{west},{north},{east}", item.get("display_name", "")

    # -------------------------------------------------------------- overpass
    @staticmethod
    def build_query(area: str, tags: List[Tuple[str, str]], name_pattern: str, max_results: int, timeout: int) -> str:
        kind, value = area.split(":", 1)
        header = f"[out:json][timeout:{timeout}];\n"
        if kind == "area":
            header += f"area({value})->.a;\n"
            scope = "(area.a)"
        else:
            scope = f"({value})"

        def esc(s: str) -> str:
            return s.replace("\\", "\\\\").replace('"', '\\"')

        lines = [f'  nwr["{esc(k)}"="{esc(v)}"]["name"]{scope};' for k, v in tags]
        if name_pattern:
            lines.append(f'  nwr[~"^({BUSINESS_KEYS})$"~"."]["name"~"{esc(name_pattern)}",i]{scope};')
        body = "(\n" + "\n".join(lines) + "\n);\n"
        return header + body + f"out center tags {int(max_results)};"

    def search(self, query: SearchQuery, max_results: Optional[int] = None) -> Iterator[Lead]:
        canonical, tags, known = resolve_sector(query.sector)
        for raw in query.osm_tags:
            if "=" not in raw:
                raise ProviderError(f"--osm-tag harus berformat key=value, bukan: {raw}")
            k, v = raw.split("=", 1)
            tags.append((k.strip(), v.strip()))
        name_pattern = "" if known else re.escape(query.sector.strip())

        area, _display = self.resolve_area(query)
        overpass_query = self.build_query(
            area, tags, name_pattern, max_results or DEFAULT_MAX_RESULTS, self.timeout
        )
        resp = request_with_retry(
            self.session,
            "POST",
            self.overpass_urls,
            data={"data": overpass_query},
            # Short connect timeout so an unresponsive mirror fails fast and the
            # next one is tried; the read timeout covers slow queries.
            timeout=(20, self.timeout + 30),
            attempts=3,
            backoff=5,
        )
        payload = resp.json()
        if payload.get("remark") and not payload.get("elements"):
            raise ProviderError(f"Overpass error: {payload['remark']}")

        for element in payload.get("elements", []):
            lead = element_to_lead(element, query, canonical, tags)
            if lead:
                yield lead


def _first(tags: Dict[str, str], *keys: str) -> str:
    for key in keys:
        value = tags.get(key)
        if value:
            return value.strip()
    return ""


def element_to_lead(element: dict, query: SearchQuery, sector: str, sector_tags: List[Tuple[str, str]]) -> Optional[Lead]:
    tags = element.get("tags") or {}
    name = _first(tags, "name", "name:en", "brand")
    if not name:
        return None

    lat = element.get("lat") or (element.get("center") or {}).get("lat")
    lon = element.get("lon") or (element.get("center") or {}).get("lon")

    street = " ".join(p for p in (tags.get("addr:street", ""), tags.get("addr:housenumber", "")) if p)
    city = _first(tags, "addr:city", "addr:town", "addr:village") or query.city
    address = _first(tags, "addr:full") or ", ".join(
        p for p in (street, tags.get("addr:suburb", ""), city, tags.get("addr:postcode", "")) if p
    )

    categories = [f"{k}={tags[k]}" for k, _ in sector_tags if k in tags]
    if not categories:
        categories = [f"{k}={tags[k]}" for k in BUSINESS_KEYS.split("|") if k in tags]

    extra = {k: tags[k] for k in ("opening_hours", "contact:facebook", "contact:instagram", "brand", "operator") if k in tags}

    return Lead(
        source="osm",
        source_id=f"{element['type']}/{element['id']}",
        name=name,
        sector=sector,
        country=query.country,
        city=city,
        address=address,
        phone=_first(tags, "phone", "contact:phone", "contact:mobile", "mobile"),
        email=_first(tags, "email", "contact:email"),
        website=_first(tags, "website", "contact:website", "url"),
        latitude=float(lat) if lat is not None else None,
        longitude=float(lon) if lon is not None else None,
        maps_url=f"https://www.openstreetmap.org/{element['type']}/{element['id']}",
        categories=";".join(dict.fromkeys(categories)),
        extra=extra,
    )
