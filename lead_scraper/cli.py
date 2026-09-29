"""Command line interface.

    python -m lead_scraper                       # interactive: asks sector & country
    python -m lead_scraper search -s dentist -c Indonesia --city Jakarta -n 50
    python -m lead_scraper stats
    python -m lead_scraper export -o semua_leads.csv
    python -m lead_scraper import leads_lama.csv
    python -m lead_scraper sectors
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from .enrich import enrich_emails
from .export import default_output_path, read_rows, write_rows
from .models import CSV_COLUMNS, Lead
from .normalize import normalize_email, normalize_phone, normalize_website
from .providers import PROVIDERS, Provider, ProviderError, SearchQuery, get_provider
from .sectors import known_sectors
from .store import LeadStore, lead_from_row

DEFAULT_DB = os.environ.get("LEAD_SCRAPER_DB", "leads.db")
REQUIRE_CHOICES = ("phone", "email", "website", "any-contact")


@dataclass
class SearchResult:
    new_leads: List[Lead] = field(default_factory=list)
    fetched: int = 0
    duplicates: int = 0
    skipped: int = 0  # did not meet --require
    output: Optional[Path] = None


def meets_requirements(lead: Lead, require: Sequence[str]) -> bool:
    has = {
        "phone": bool(normalize_phone(lead.phone)),
        "email": bool(normalize_email(lead.email)),
        "website": bool(lead.website.strip()),
    }
    for req in require:
        if req == "any-contact" and not any(has.values()):
            return False
        if req in has and not has[req]:
            return False
    return True


def run_search(
    store: LeadStore,
    provider: Provider,
    sector: str,
    country: str,
    cities: Sequence[str] = (),
    limit: int = 50,
    require: Sequence[str] = (),
    osm_tags: Sequence[str] = (),
    find_emails: bool = False,
    output: Optional[Path] = None,
    fmt: str = "csv",
    dry_run: bool = False,
    log=print,
) -> SearchResult:
    """Fetch leads, drop every lead seen in a previous run, save the rest."""
    result = SearchResult()
    batch_keys: set = set()
    city_list = [c for c in cities if c.strip()] or [""]

    for city in city_list:
        remaining = limit - len(result.new_leads) if limit else 0
        if limit and remaining <= 0:
            break
        query = SearchQuery(sector=sector, country=country, city=city.strip(), osm_tags=list(osm_tags))
        max_results = None
        if provider.name == "osm":
            # Results are stable between runs, so asking for (#already seen +
            # a margin) always leaves room for new leads. With --require some
            # results are skipped without being stored, so fetch everything.
            if require:
                max_results = 100_000
            else:
                max_results = store.count("osm") + (remaining * 2 if limit else 20_000)
        log(f"Mencari '{sector}' di {query.location} via {provider.name} ...")

        for lead in provider.search(query, max_results=max_results):
            result.fetched += 1
            lead.sector = lead.sector or sector
            lead.country = lead.country or country
            if require and not meets_requirements(lead, require):
                result.skipped += 1
                continue
            if not store.is_new(lead, batch_keys):
                result.duplicates += 1
                continue
            result.new_leads.append(lead)
            if limit and len(result.new_leads) >= limit:
                break

    if find_emails and result.new_leads:
        log(f"Mencari email di website {sum(1 for l in result.new_leads if l.website and not l.email)} leads ...")
        found = enrich_emails(result.new_leads)
        log(f"  {found} email ditemukan.")
        # A found e-mail can reveal that a lead is a company we already have.
        before = len(result.new_leads)
        result.new_leads, dupes = store.filter_new(result.new_leads)
        result.duplicates += dupes
        if require:
            kept = [l for l in result.new_leads if meets_requirements(l, require)]
            result.skipped += len(result.new_leads) - len(kept)
            result.new_leads = kept
        if len(result.new_leads) != before:
            log(f"  {before - len(result.new_leads)} lead dibuang setelah pengecekan email.")

    if not result.new_leads:
        if not dry_run:
            store.record_search(provider.name, sector, country, ", ".join(c for c in city_list if c), result.fetched, 0)
        return result

    output = output or default_output_path(sector, country, [c for c in city_list if c], fmt)
    result.output = write_rows((l.to_row() for l in result.new_leads), output, fmt)
    if not dry_run:
        search_id = store.record_search(
            provider.name,
            sector,
            country,
            ", ".join(c for c in city_list if c),
            result.fetched,
            len(result.new_leads),
            str(result.output),
        )
        store.add(result.new_leads, search_id=search_id)
    return result


def print_table(leads: List[Lead], max_rows: int = 20) -> None:
    cols = [("name", 32), ("city", 16), ("phone", 18), ("website", 32), ("email", 28)]
    header = "  ".join(name.upper().ljust(width) for name, width in cols)
    print(header)
    print("-" * len(header))
    for lead in leads[:max_rows]:
        row = lead.to_row()
        print("  ".join(str(row.get(name) or "")[:width].ljust(width) for name, width in cols))
    if len(leads) > max_rows:
        print(f"... dan {len(leads) - max_rows} lainnya (lihat file output)")


# ----------------------------------------------------------------- commands
def cmd_search(args: argparse.Namespace) -> int:
    try:
        provider = get_provider(args.provider, args.google_api_key or "")
    except ProviderError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    with LeadStore(args.db) as store:
        try:
            result = run_search(
                store,
                provider,
                sector=args.sector,
                country=args.country,
                cities=args.city or [],
                limit=args.limit,
                require=args.require or [],
                osm_tags=args.osm_tag or [],
                find_emails=args.find_emails,
                output=Path(args.output) if args.output else None,
                fmt=args.format,
                dry_run=args.dry_run,
            )
        except ProviderError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # network errors etc.
            print(f"Gagal mengambil data dari {provider.name}: {exc}", file=sys.stderr)
            return 1

        print()
        print(f"Diambil dari sumber : {result.fetched}")
        print(f"Duplikat (dibuang)  : {result.duplicates}")
        if args.require:
            print(f"Tidak ada kontak    : {result.skipped}")
        print(f"Leads BARU          : {len(result.new_leads)}")
        if not result.new_leads:
            print("\nTidak ada leads baru. Coba kota lain (--city), sektor lain, atau provider lain.")
            return 0
        print()
        print_table(result.new_leads)
        print(f"\nHasil disimpan ke: {result.output}")
        if args.dry_run:
            print("(dry-run: leads ini TIDAK ditandai, jadi bisa muncul lagi di pencarian berikutnya)")
        else:
            print(f"Total leads tersimpan di database ({args.db}): {store.count()}")
        if args.limit and len(result.new_leads) < args.limit:
            print(
                f"Catatan: hanya {len(result.new_leads)} dari {args.limit} leads baru yang tersedia untuk pencarian ini."
            )
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    with LeadStore(args.db) as store:
        stats = store.stats()
    print(f"Database: {args.db}")
    print(f"Total leads unik: {stats['total']}")
    for source, count in stats["by_source"].items():
        print(f"  {source}: {count}")
    if stats["by_query"]:
        print("\nPer sektor / negara / kota:")
        for sector, country, city, count in stats["by_query"]:
            where = f"{city}, {country}" if city else country
            print(f"  {sector} @ {where}: {count}")
    if stats["recent_searches"]:
        print("\nPencarian terakhir:")
        for created, provider, sector, country, city, fetched, new, output in stats["recent_searches"]:
            where = f"{city}, {country}" if city else country
            print(f"  {created}  [{provider}] {sector} @ {where}: {new} baru / {fetched} diambil  {output}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    fmt = args.format or ("json" if args.output.lower().endswith(".json") else "csv")
    with LeadStore(args.db) as store:
        rows = store.all_leads()
    path = write_rows(rows, Path(args.output), fmt, columns=CSV_COLUMNS + ["first_seen"])
    print(f"{len(rows)} leads diekspor ke {path}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    total_added = 0
    with LeadStore(args.db) as store:
        for file in args.files:
            rows = read_rows(Path(file))
            leads = [lead_from_row(r) for r in rows]
            leads = [
                l
                for l in leads
                if l.name or normalize_phone(l.phone) or normalize_email(l.email) or normalize_website(l.website)
            ]
            new, dupes = store.filter_new(leads)
            added = store.add(new)
            total_added += added
            print(f"{file}: {added} leads ditambahkan, {dupes} sudah ada")
        print(f"Total leads di database: {store.count()}")
    return 0


def cmd_sectors(args: argparse.Namespace) -> int:
    print("Sektor yang dikenali (untuk provider OSM; sektor lain tetap bisa dicoba):")
    for name in known_sectors():
        print(f"  - {name}")
    return 0


def interactive(db: str) -> int:
    print("=== Lead Scraper ===")
    try:
        sector = input("Sektor bisnis (contoh: restaurant, dentist, bengkel): ").strip()
        country = input("Negara (contoh: Indonesia): ").strip()
        city = input("Kota (opsional, pisahkan dengan koma, Enter = seluruh negara): ").strip()
        limit_raw = input("Jumlah leads baru [50]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1
    if not sector or not country:
        print("Sektor dan negara wajib diisi.")
        return 2
    return main(
        ["--db", db, "search", "-s", sector, "-c", country, "-n", limit_raw or "50"]
        + [arg for c in city.split(",") if c.strip() for arg in ("--city", c.strip())]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lead_scraper",
        description="Cari leads bisnis berdasarkan sektor & negara, tanpa duplikat dengan hasil sebelumnya.",
    )
    parser.add_argument("--db", default=DEFAULT_DB, help=f"File database SQLite (default: {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("search", help="Cari leads baru")
    p.add_argument("-s", "--sector", required=True, help="Sektor bisnis, mis. 'restaurant', 'dentist', 'bengkel'")
    p.add_argument("-c", "--country", required=True, help="Negara, mis. 'Indonesia'")
    p.add_argument("--city", action="append", help="Kota (boleh diulang: --city Jakarta --city Bandung)")
    p.add_argument("-n", "--limit", type=int, default=50, help="Jumlah leads baru yang diinginkan (0 = semua)")
    p.add_argument("-p", "--provider", choices=PROVIDERS, default="auto",
                   help="Sumber data: osm (gratis), google (butuh API key), auto (google jika ada key)")
    p.add_argument("--require", action="append", choices=REQUIRE_CHOICES,
                   help="Hanya ambil leads yang punya kontak ini (boleh diulang)")
    p.add_argument("--find-emails", action="store_true", help="Cari email di website tiap lead baru")
    p.add_argument("-o", "--output", help="File output (default: results/<waktu>_<sektor>_<negara>.csv)")
    p.add_argument("-f", "--format", choices=("csv", "json"), default="csv")
    p.add_argument("--dry-run", action="store_true", help="Tampilkan hasil tanpa menandai leads sebagai sudah keluar")
    p.add_argument("--osm-tag", action="append", help="Tag OSM tambahan, mis. shop=bicycle (boleh diulang)")
    p.add_argument("--google-api-key", help="API key Google Places (default: env GOOGLE_MAPS_API_KEY)")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("stats", help="Ringkasan leads yang sudah pernah keluar")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("export", help="Ekspor semua leads yang pernah keluar")
    p.add_argument("-o", "--output", default="all_leads.csv")
    p.add_argument("-f", "--format", choices=("csv", "json"))
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("import", help="Tandai leads dari file CSV/JSON lama sebagai sudah pernah keluar")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("sectors", help="Daftar sektor yang dikenali")
    p.set_defaults(func=cmd_sectors)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        return interactive(args.db)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
