from pathlib import Path

import pytest

from lead_scraper.cli import main, run_search
from lead_scraper.models import Lead
from lead_scraper.normalize import dedup_keys, normalize_phone, normalize_website
from lead_scraper.providers.base import Provider
from lead_scraper.store import LeadStore


def make_lead(i, source="osm", **kw):
    defaults = dict(source=source, source_id=f"node/{i}", name=f"Biz {i}", phone=f"+62 21 5550{i:04d}")
    defaults.update(kw)
    return Lead(**defaults)


class FakeProvider(Provider):
    """Returns the same stable, ordered list every run (like Overpass does)."""

    name = "osm"

    def __init__(self, leads):
        self.leads = leads
        self.calls = []

    def search(self, query, max_results=None):
        self.calls.append((query, max_results))
        items = self.leads[:max_results] if max_results else self.leads
        yield from items


@pytest.fixture
def store(tmp_path):
    s = LeadStore(tmp_path / "leads.db")
    yield s
    s.close()


def quiet(*_args, **_kw):
    pass


# ---------------------------------------------------------------- normalize
def test_phone_formats_are_equivalent():
    assert normalize_phone("+62 21 555 1234") == normalize_phone("021-5551234")
    assert normalize_phone("(021) 555 1234; 0812 999") == normalize_phone("+622155512 34")
    assert normalize_phone("123") == ""


def test_website_normalization():
    assert normalize_website("https://www.Example.co.id/") == "example.co.id"
    assert normalize_website("example.co.id/index.html") == "example.co.id"
    assert normalize_website("http://example.co.id/?utm=x") == "example.co.id"
    assert normalize_website("https://www.facebook.com/somebiz") == ""
    assert normalize_website("https://instagram.com/x") == ""


def test_dedup_keys_include_contacts():
    lead = make_lead(1, email="Info@Biz.com", website="https://www.biz.com/", latitude=-6.2, longitude=106.8)
    keys = dedup_keys(lead)
    assert "id:osm:node/1" in keys
    assert "email:info@biz.com" in keys
    assert "web:biz.com" in keys
    assert any(k.startswith("phone:") for k in keys)
    assert any(k.startswith("loc:biz 1@") for k in keys)


# -------------------------------------------------------------------- store
def test_same_business_from_other_source_is_duplicate(store):
    store.add([make_lead(1, website="biz1.com")])
    same_phone = Lead(source="google", source_id="ChIJxyz", name="Biz One", phone="021 55500001")
    same_site = Lead(source="google", source_id="ChIJabc", name="Other", website="https://www.biz1.com")
    other = Lead(source="google", source_id="ChIJnew", name="New Biz", phone="021 99999999")
    assert store.find_duplicate(same_phone) == "osm:node/1"
    assert store.find_duplicate(same_site) == "osm:node/1"
    assert store.find_duplicate(other) is None


def test_filter_new_removes_duplicates_within_batch(store):
    new, dupes = store.filter_new([make_lead(1), make_lead(2), make_lead(3, phone="021 55500001")])
    assert [l.source_id for l in new] == ["node/1", "node/2"]
    assert dupes == 1


# ---------------------------------------------------------------- run_search
def test_second_run_never_repeats_leads(store, tmp_path):
    provider = FakeProvider([make_lead(i) for i in range(1, 26)])

    first = run_search(store, provider, "restaurant", "Indonesia", limit=10, output=tmp_path / "a.csv", log=quiet)
    second = run_search(store, provider, "restaurant", "Indonesia", limit=10, output=tmp_path / "b.csv", log=quiet)
    third = run_search(store, provider, "restaurant", "Indonesia", limit=10, output=tmp_path / "c.csv", log=quiet)
    fourth = run_search(store, provider, "restaurant", "Indonesia", limit=10, output=tmp_path / "d.csv", log=quiet)

    ids = lambda r: [l.source_id for l in r.new_leads]
    assert ids(first) == [f"node/{i}" for i in range(1, 11)]
    assert ids(second) == [f"node/{i}" for i in range(11, 21)]
    assert ids(third) == [f"node/{i}" for i in range(21, 26)]
    assert fourth.new_leads == [] and fourth.output is None
    assert store.count() == 25
    # The OSM fetch cap grows with the number of stored leads.
    assert [c[1] for c in provider.calls] == [20, 30, 40, 45]
    # The output file only contains the new leads.
    assert (tmp_path / "b.csv").read_text(encoding="utf-8-sig").count("osm:node/") == 10


def test_dry_run_does_not_mark_leads(store, tmp_path):
    provider = FakeProvider([make_lead(i) for i in range(1, 6)])
    run_search(store, provider, "cafe", "Indonesia", limit=3, dry_run=True, output=tmp_path / "x.csv", log=quiet)
    assert store.count() == 0
    again = run_search(store, provider, "cafe", "Indonesia", limit=3, output=tmp_path / "y.csv", log=quiet)
    assert [l.source_id for l in again.new_leads] == ["node/1", "node/2", "node/3"]


def test_require_phone_skips_leads_without_phone(store, tmp_path):
    leads = [make_lead(1), make_lead(2, phone=""), make_lead(3)]
    result = run_search(
        store, FakeProvider(leads), "cafe", "Indonesia", limit=5, require=["phone"], output=tmp_path / "r.csv", log=quiet
    )
    assert [l.source_id for l in result.new_leads] == ["node/1", "node/3"]
    assert result.skipped == 1
    # The lead without a phone was not stored, so it can still show up later.
    assert store.count() == 2


def test_multiple_cities_share_dedup(store, tmp_path):
    provider = FakeProvider([make_lead(1), make_lead(2)])
    result = run_search(
        store, provider, "cafe", "Indonesia", cities=["Jakarta", "Bandung"], limit=0, output=tmp_path / "m.csv", log=quiet
    )
    assert len(result.new_leads) == 2
    assert result.duplicates == 2
    assert [c[0].city for c in provider.calls] == ["Jakarta", "Bandung"]


# ----------------------------------------------------------------- commands
def test_import_marks_existing_leads(tmp_path, monkeypatch):
    db = tmp_path / "leads.db"
    old = tmp_path / "old.csv"
    old.write_text("Name,Phone,Website\nBiz 1,021-55500001,\nSomething,,https://something.com\n", encoding="utf-8")
    assert main(["--db", str(db), "import", str(old)]) == 0
    assert main(["--db", str(db), "import", str(old)]) == 0  # idempotent

    with LeadStore(db) as store:
        assert store.count() == 2
        result = run_search(
            store, FakeProvider([make_lead(1), make_lead(2)]), "x", "Indonesia", limit=5, output=tmp_path / "o.csv", log=quiet
        )
    assert [l.source_id for l in result.new_leads] == ["node/2"]


def test_export_and_stats(tmp_path, capsys):
    db = tmp_path / "leads.db"
    with LeadStore(db) as store:
        run_search(store, FakeProvider([make_lead(1), make_lead(2)]), "cafe", "Indonesia", limit=5,
                   output=tmp_path / "o.csv", log=quiet)
    out = tmp_path / "all.csv"
    assert main(["--db", str(db), "export", "-o", str(out)]) == 0
    text = out.read_text(encoding="utf-8-sig")
    assert "first_seen" in text.splitlines()[0]
    assert text.count("osm:node/") == 2
    assert main(["--db", str(db), "stats"]) == 0
    assert "Total leads unik: 2" in capsys.readouterr().out
