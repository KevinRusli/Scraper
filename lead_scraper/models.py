"""Data model for a single lead."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Optional


@dataclass
class Lead:
    source: str  # provider name, e.g. "osm" or "google"
    source_id: str  # stable id inside that provider (OSM element id, Google place id)
    name: str
    sector: str = ""
    country: str = ""
    city: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    maps_url: str = ""
    categories: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"

    def to_row(self) -> dict:
        """Flat dict for CSV/JSON output (without the free-form `extra`)."""
        row = asdict(self)
        row.pop("extra", None)
        row["uid"] = self.uid
        return row


CSV_COLUMNS = ["uid"] + [f.name for f in fields(Lead) if f.name != "extra"]
