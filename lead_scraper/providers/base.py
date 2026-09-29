from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, List, Optional

from ..models import Lead


@dataclass
class SearchQuery:
    sector: str
    country: str
    city: str = ""
    # Extra raw OSM tags ("key=value"), only used by the OSM provider.
    osm_tags: List[str] = field(default_factory=list)

    @property
    def location(self) -> str:
        return f"{self.city}, {self.country}" if self.city else self.country


class Provider:
    name = "base"

    def search(self, query: SearchQuery, max_results: Optional[int] = None) -> Iterator[Lead]:
        """Yield leads for `query`, lazily where possible.

        `max_results` is a hint for how many raw results to fetch at most; the
        caller filters out already-seen leads and stops iterating once it has
        enough new ones.
        """
        raise NotImplementedError


class ProviderError(RuntimeError):
    pass
