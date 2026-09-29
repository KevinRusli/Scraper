import json

import pytest

from lead_scraper.providers import GooglePlacesProvider, OSMProvider, SearchQuery, get_provider
from lead_scraper.providers.base import ProviderError
from lead_scraper.sectors import resolve_sector


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status
        self.text = json.dumps(payload)
        self.ok = status < 400

    def json(self):
        return self.payload

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, handler):
        self.handler = handler
        self.requests = []
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.handler(method, url, kwargs)


# ---------------------------------------------------------------- sectors
def test_resolve_sector_synonyms():
    assert resolve_sector("Bengkel")[0] == "car repair"
    assert resolve_sector("dokter gigi")[1] == [("amenity", "dentist"), ("healthcare", "dentist")]
    name, tags, known = resolve_sector("Solar Panel")
    assert not known and ("shop", "solar_panel") in tags


# -------------------------------------------------------------------- OSM
OVERPASS_PAYLOAD = {
    "elements": [
        {
            "type": "node",
            "id": 1,
            "lat": -6.2,
            "lon": 106.8,
            "tags": {
                "name": "Klinik Gigi Sehat",
                "amenity": "dentist",
                "phone": "+62 21 5551234",
                "website": "https://sehat.co.id",
                "addr:street": "Jl. Sudirman",
                "addr:housenumber": "5",
                "addr:city": "Jakarta Pusat",
            },
        },
        {"type": "way", "id": 2, "center": {"lat": -6.3, "lon": 106.9}, "tags": {"name": "Dental Care", "healthcare": "dentist"}},
        {"type": "node", "id": 3, "lat": 0, "lon": 0, "tags": {"amenity": "dentist"}},  # no name -> skipped
    ]
}


def osm_handler(method, url, kwargs):
    if "nominatim" in url:
        return FakeResponse([{"osm_type": "relation", "osm_id": 6362934, "display_name": "Jakarta, Indonesia"}])
    return FakeResponse(OVERPASS_PAYLOAD)


def test_osm_search(monkeypatch):
    monkeypatch.setattr("lead_scraper.providers.osm.time.sleep", lambda s: None)
    session = FakeSession(osm_handler)
    provider = OSMProvider(session=session)
    leads = list(provider.search(SearchQuery("dentist", "Indonesia", "Jakarta"), max_results=40))

    assert [l.uid for l in leads] == ["osm:node/1", "osm:way/2"]
    first = leads[0]
    assert first.phone == "+62 21 5551234"
    assert first.address == "Jl. Sudirman 5, Jakarta Pusat"
    assert first.city == "Jakarta Pusat"
    assert first.categories == "amenity=dentist"
    assert leads[1].latitude == -6.3 and leads[1].city == "Jakarta"

    nominatim = session.requests[0]
    assert nominatim[2]["params"]["city"] == "Jakarta"
    query = session.requests[1][2]["data"]["data"]
    assert "area(3606362934)->.a;" in query
    assert 'nwr["amenity"="dentist"]["name"](area.a);' in query
    assert query.endswith("out center tags 40;")


def test_osm_unknown_sector_matches_on_name():
    query = OSMProvider.build_query("bbox:1,2,3,4", [("shop", "solar_panel")], "solar panel", 10, 60)
    assert 'nwr["shop"="solar_panel"]["name"](1,2,3,4);' in query
    assert '["name"~"solar panel",i](1,2,3,4);' in query


def test_osm_location_not_found(monkeypatch):
    monkeypatch.setattr("lead_scraper.providers.osm.time.sleep", lambda s: None)
    provider = OSMProvider(session=FakeSession(lambda *a: FakeResponse([])))
    with pytest.raises(ProviderError):
        list(provider.search(SearchQuery("cafe", "Atlantis")))


# ----------------------------------------------------------------- Google
def place(i, **kw):
    p = {
        "id": f"place{i}",
        "displayName": {"text": f"Cafe {i}"},
        "formattedAddress": f"Jl. {i}, Bandung, Indonesia",
        "addressComponents": [{"longText": "Bandung", "types": ["locality", "political"]}],
        "internationalPhoneNumber": f"+62 22 555 {i:04d}",
        "websiteUri": f"https://cafe{i}.id",
        "rating": 4.5,
        "userRatingCount": 10,
        "location": {"latitude": -6.9, "longitude": 107.6},
        "types": ["cafe"],
    }
    p.update(kw)
    return p


def test_google_paging_and_mapping(monkeypatch):
    monkeypatch.setattr("lead_scraper.providers.google_places.time.sleep", lambda s: None)
    pages = [
        {"places": [place(1), place(2, businessStatus="CLOSED_PERMANENTLY")], "nextPageToken": "t1"},
        {"places": [place(3)]},
    ]
    session = FakeSession(lambda m, u, kw: FakeResponse(pages.pop(0)))
    provider = GooglePlacesProvider(api_key="k", session=session)
    leads = list(provider.search(SearchQuery("cafe", "Indonesia", "Bandung")))

    assert [l.uid for l in leads] == ["google:place1", "google:place3"]
    assert leads[0].city == "Bandung" and leads[0].rating == 4.5
    assert session.requests[0][2]["json"]["textQuery"] == "cafe in Bandung, Indonesia"
    assert session.requests[1][2]["json"]["pageToken"] == "t1"
    assert session.requests[0][2]["headers"]["X-Goog-Api-Key"] == "k"


def test_auto_provider_selection(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    assert get_provider("auto").name == "osm"
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "abc")
    assert get_provider("auto").name == "google"
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY")
    with pytest.raises(ProviderError):
        get_provider("google")
