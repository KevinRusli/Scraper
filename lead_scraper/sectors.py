"""Map free-text business sectors (English / Indonesian) to OpenStreetMap tags.

OpenStreetMap does not support free-text category search, so a sector such as
"dentist" or "bengkel" has to be translated into OSM tags such as
``amenity=dentist`` or ``shop=car_repair``. Sectors not listed here fall back
to a generic tag guess plus a case-insensitive match on the business name.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

Tag = Tuple[str, str]

# canonical sector -> (synonyms, OSM tags)
SECTORS: Dict[str, Tuple[List[str], List[Tag]]] = {
    "restaurant": (
        ["restaurant", "restaurants", "restoran", "rumah makan", "resto", "warung makan"],
        [("amenity", "restaurant"), ("amenity", "fast_food"), ("amenity", "food_court")],
    ),
    "cafe": (
        ["cafe", "cafes", "coffee shop", "coffee", "kafe", "kedai kopi", "warung kopi"],
        [("amenity", "cafe"), ("shop", "coffee")],
    ),
    "bar": (["bar", "bars", "pub", "pubs", "nightclub"], [("amenity", "bar"), ("amenity", "pub"), ("amenity", "nightclub")]),
    "bakery": (["bakery", "bakeries", "toko roti", "roti", "pastry"], [("shop", "bakery"), ("shop", "pastry")]),
    "hotel": (
        ["hotel", "hotels", "penginapan", "hostel", "guest house", "guesthouse", "motel", "resort", "villa"],
        [("tourism", "hotel"), ("tourism", "hostel"), ("tourism", "guest_house"), ("tourism", "motel"), ("tourism", "apartment")],
    ),
    "dentist": (["dentist", "dentists", "dental clinic", "dokter gigi", "klinik gigi"], [("amenity", "dentist"), ("healthcare", "dentist")]),
    "clinic": (
        ["clinic", "clinics", "klinik", "medical clinic", "doctor", "doctors", "dokter", "puskesmas"],
        [("amenity", "clinic"), ("amenity", "doctors"), ("healthcare", "clinic"), ("healthcare", "doctor")],
    ),
    "hospital": (["hospital", "hospitals", "rumah sakit", "rs"], [("amenity", "hospital"), ("healthcare", "hospital")]),
    "pharmacy": (["pharmacy", "pharmacies", "apotek", "apotik", "drugstore", "chemist"], [("amenity", "pharmacy"), ("healthcare", "pharmacy"), ("shop", "chemist")]),
    "veterinary": (["veterinary", "vet", "vets", "dokter hewan", "klinik hewan"], [("amenity", "veterinary")]),
    "beauty salon": (
        ["beauty salon", "salon", "salons", "salon kecantikan", "beauty", "spa", "nail salon", "barbershop", "barber", "pangkas rambut"],
        [("shop", "beauty"), ("shop", "hairdresser"), ("leisure", "spa"), ("shop", "massage"), ("amenity", "spa")],
    ),
    "gym": (["gym", "gyms", "fitness", "fitness center", "pusat kebugaran", "yoga"], [("leisure", "fitness_centre"), ("leisure", "sports_centre"), ("sport", "fitness"), ("sport", "yoga")]),
    "car repair": (
        ["car repair", "auto repair", "mechanic", "bengkel", "bengkel mobil", "bengkel motor", "garage"],
        [("shop", "car_repair"), ("shop", "motorcycle_repair"), ("shop", "tyres"), ("craft", "mechanic")],
    ),
    "car dealer": (["car dealer", "dealer mobil", "showroom mobil", "car dealership", "motorcycle dealer", "dealer motor"], [("shop", "car"), ("shop", "motorcycle")]),
    "real estate": (["real estate", "realtor", "property", "properti", "agen properti", "estate agent"], [("office", "estate_agent")]),
    "lawyer": (["lawyer", "lawyers", "law firm", "advokat", "pengacara", "notaris", "notary", "kantor hukum"], [("office", "lawyer"), ("office", "notary")]),
    "accounting": (["accounting", "accountant", "accountants", "akuntan", "kantor akuntan", "tax consultant", "konsultan pajak"], [("office", "accountant"), ("office", "tax_advisor")]),
    "insurance": (["insurance", "asuransi"], [("office", "insurance")]),
    "bank": (["bank", "banks", "perbankan"], [("amenity", "bank")]),
    "it company": (
        ["it company", "it", "software", "software company", "technology", "tech company", "it consultant", "perusahaan it", "teknologi"],
        [("office", "it"), ("office", "company"), ("office", "telecommunication"), ("shop", "computer")],
    ),
    "marketing agency": (["marketing agency", "advertising", "advertising agency", "digital agency", "agensi", "periklanan"], [("office", "advertising_agency"), ("office", "marketing")]),
    "consulting": (["consulting", "consultant", "consultancy", "konsultan"], [("office", "consulting")]),
    "travel agency": (["travel agency", "travel", "tour operator", "agen perjalanan", "biro perjalanan"], [("shop", "travel_agency"), ("office", "travel_agent")]),
    "school": (
        ["school", "schools", "sekolah", "education", "pendidikan", "course", "kursus", "bimbel", "tutoring", "language school"],
        [("amenity", "school"), ("amenity", "language_school"), ("amenity", "music_school"), ("amenity", "driving_school"), ("amenity", "prep_school")],
    ),
    "university": (["university", "universities", "universitas", "college", "kampus"], [("amenity", "university"), ("amenity", "college")]),
    "kindergarten": (["kindergarten", "tk", "paud", "daycare", "preschool", "childcare"], [("amenity", "kindergarten"), ("amenity", "childcare")]),
    "supermarket": (["supermarket", "supermarkets", "minimarket", "grocery", "groceries", "toko kelontong", "swalayan"], [("shop", "supermarket"), ("shop", "convenience"), ("shop", "greengrocer")]),
    "clothing store": (["clothing store", "clothes", "fashion", "boutique", "butik", "toko baju", "pakaian"], [("shop", "clothes"), ("shop", "boutique"), ("shop", "fashion")]),
    "electronics store": (["electronics store", "electronics", "elektronik", "toko elektronik", "mobile phone", "handphone", "toko hp"], [("shop", "electronics"), ("shop", "mobile_phone"), ("shop", "computer")]),
    "furniture store": (["furniture store", "furniture", "mebel", "toko furniture", "interior"], [("shop", "furniture"), ("shop", "interior_decoration")]),
    "hardware store": (["hardware store", "hardware", "toko bangunan", "building materials", "bahan bangunan"], [("shop", "hardware"), ("shop", "doityourself"), ("shop", "trade")]),
    "construction": (["construction", "contractor", "kontraktor", "konstruksi", "builder"], [("office", "construction_company"), ("craft", "builder"), ("office", "architect")]),
    "architect": (["architect", "architects", "arsitek"], [("office", "architect")]),
    "printing": (["printing", "print shop", "percetakan", "digital printing", "fotokopi"], [("shop", "copyshop"), ("craft", "printer"), ("shop", "printing")]),
    "laundry": (["laundry", "dry cleaning", "binatu"], [("shop", "laundry"), ("shop", "dry_cleaning")]),
    "logistics": (["logistics", "courier", "ekspedisi", "logistik", "shipping", "freight", "jasa pengiriman"], [("office", "logistics"), ("amenity", "courier"), ("office", "courier"), ("shop", "courier")]),
    "photography": (["photography", "photographer", "photo studio", "fotografer", "studio foto"], [("shop", "photo"), ("craft", "photographer"), ("office", "photographer")]),
    "event venue": (["event venue", "wedding venue", "gedung pernikahan", "wedding organizer", "event organizer", "wo", "eo"], [("amenity", "events_venue"), ("amenity", "conference_centre"), ("office", "event_management")]),
    "florist": (["florist", "flower shop", "toko bunga"], [("shop", "florist")]),
    "jewelry": (["jewelry", "jewellery", "toko emas", "perhiasan", "jeweler"], [("shop", "jewelry")]),
    "optician": (["optician", "optik", "optical", "eyewear"], [("shop", "optician")]),
    "pet shop": (["pet shop", "pet store", "toko hewan"], [("shop", "pet"), ("shop", "pet_grooming")]),
    "car rental": (["car rental", "rental mobil", "sewa mobil"], [("amenity", "car_rental")]),
    "coworking": (["coworking", "co-working", "coworking space", "shared office"], [("office", "coworking"), ("amenity", "coworking_space")]),
    "manufacturing": (["manufacturing", "manufacturer", "factory", "pabrik", "industri"], [("man_made", "works"), ("industrial", "factory"), ("office", "company")]),
}

# Keys we try when a sector is not in SECTORS.
FALLBACK_KEYS = ["shop", "amenity", "office", "craft", "tourism", "healthcare", "leisure"]


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def resolve_sector(sector: str) -> Tuple[str, List[Tag], bool]:
    """Return (canonical_name, osm_tags, known).

    ``known`` is False when the sector was not recognised and the tags are a
    best-effort guess (callers then also match on the business name).
    """
    wanted = _norm(sector)
    for canonical, (synonyms, tags) in SECTORS.items():
        if wanted == canonical or wanted in synonyms:
            return canonical, list(tags), True
    slug = re.sub(r"[^a-z0-9]+", "_", wanted).strip("_")
    return wanted, [(key, slug) for key in FALLBACK_KEYS], False


def known_sectors() -> List[str]:
    return sorted(SECTORS)
