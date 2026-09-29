"""SQLite store that remembers every lead ever returned.

This is what prevents duplicates between runs: before a lead is shown it is
checked against all keys stored here (see :mod:`lead_scraper.normalize`), and
after the results are saved the new leads and their keys are recorded.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .models import CSV_COLUMNS, Lead
from .normalize import dedup_keys

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    uid         TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    name        TEXT NOT NULL,
    sector      TEXT,
    country     TEXT,
    city        TEXT,
    data        TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    search_id   INTEGER
);
CREATE TABLE IF NOT EXISTS lead_keys (
    key  TEXT PRIMARY KEY,
    uid  TEXT NOT NULL REFERENCES leads(uid)
);
CREATE TABLE IF NOT EXISTS searches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    provider    TEXT NOT NULL,
    sector      TEXT NOT NULL,
    country     TEXT NOT NULL,
    city        TEXT,
    fetched     INTEGER NOT NULL,
    new_leads   INTEGER NOT NULL,
    output      TEXT
);
CREATE INDEX IF NOT EXISTS idx_leads_source ON leads(source);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LeadStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.parent and not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "LeadStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ reads
    def find_duplicate(self, lead: Lead) -> Optional[str]:
        """Return the uid of a previously stored lead matching `lead`, if any."""
        keys = dedup_keys(lead)
        placeholders = ",".join("?" * len(keys))
        row = self.conn.execute(
            f"SELECT uid FROM lead_keys WHERE key IN ({placeholders}) LIMIT 1", keys
        ).fetchone()
        return row[0] if row else None

    def is_new(self, lead: Lead, batch_keys: Optional[set] = None) -> bool:
        """True if `lead` was never stored and is not in `batch_keys`.

        When it is new, its keys are added to `batch_keys` so a second copy
        within the same run is rejected too.
        """
        keys = dedup_keys(lead)
        if batch_keys is not None and batch_keys.intersection(keys):
            return False
        if self.find_duplicate(lead):
            return False
        if batch_keys is not None:
            batch_keys.update(keys)
        return True

    def filter_new(self, leads: Iterable[Lead]) -> Tuple[List[Lead], int]:
        """Split `leads` into never-seen-before leads and a duplicate count.

        Duplicates *within* the batch are removed as well.
        """
        new: List[Lead] = []
        batch_keys: set = set()
        duplicates = 0
        for lead in leads:
            if self.is_new(lead, batch_keys):
                new.append(lead)
            else:
                duplicates += 1
        return new, duplicates

    def count(self, source: Optional[str] = None) -> int:
        if source:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM leads WHERE source = ?", (source,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) FROM leads").fetchone()
        return int(row[0])

    def stats(self) -> Dict[str, object]:
        by_source = dict(
            self.conn.execute("SELECT source, COUNT(*) FROM leads GROUP BY source")
        )
        by_query = self.conn.execute(
            "SELECT sector, country, COALESCE(city, ''), COUNT(*) FROM leads "
            "GROUP BY sector, country, city ORDER BY COUNT(*) DESC"
        ).fetchall()
        searches = self.conn.execute(
            "SELECT created_at, provider, sector, country, COALESCE(city, ''), "
            "fetched, new_leads, COALESCE(output, '') FROM searches "
            "ORDER BY id DESC LIMIT 20"
        ).fetchall()
        return {
            "total": self.count(),
            "by_source": by_source,
            "by_query": by_query,
            "recent_searches": searches,
        }

    def all_leads(self) -> List[dict]:
        rows = self.conn.execute(
            "SELECT data, first_seen FROM leads ORDER BY first_seen, rowid"
        ).fetchall()
        out = []
        for data, first_seen in rows:
            row = json.loads(data)
            row["first_seen"] = first_seen
            out.append(row)
        return out

    # ----------------------------------------------------------------- writes
    def record_search(
        self,
        provider: str,
        sector: str,
        country: str,
        city: str,
        fetched: int,
        new_leads: int,
        output: str = "",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO searches (created_at, provider, sector, country, city, "
            "fetched, new_leads, output) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (_now(), provider, sector, country, city or None, fetched, new_leads, output),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add(self, leads: Iterable[Lead], search_id: Optional[int] = None) -> int:
        """Remember `leads` so they are never returned again. Returns #added."""
        added = 0
        now = _now()
        with self.conn:
            for lead in leads:
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO leads (uid, source, name, sector, country, "
                    "city, data, first_seen, search_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        lead.uid,
                        lead.source,
                        lead.name,
                        lead.sector,
                        lead.country,
                        lead.city,
                        json.dumps(lead.to_row(), ensure_ascii=False),
                        now,
                        search_id,
                    ),
                )
                added += cur.rowcount
                self.conn.executemany(
                    "INSERT OR IGNORE INTO lead_keys (key, uid) VALUES (?, ?)",
                    [(k, lead.uid) for k in dedup_keys(lead)],
                )
        return added


def lead_from_row(row: dict) -> Lead:
    """Build a Lead from a CSV/JSON row (used by `import`)."""

    def num(value, cast):
        if value in (None, ""):
            return None
        try:
            return cast(value)
        except (TypeError, ValueError):
            return None

    source = (row.get("source") or "import").strip()
    source_id = (row.get("source_id") or "").strip()
    uid = (row.get("uid") or "").strip()
    if not source_id and uid and ":" in uid:
        source, source_id = uid.split(":", 1)
    name = (row.get("name") or row.get("company") or row.get("business_name") or "").strip()
    if not source_id:
        # No stable id: derive one from the contact details so re-importing the
        # same file does not create new rows.
        source_id = "|".join(
            (row.get(k) or "").strip().lower() for k in ("name", "phone", "email", "website", "address")
        )
    lead = Lead(source=source, source_id=source_id, name=name)
    for col in CSV_COLUMNS:
        if col in ("uid", "source", "source_id", "name") or col not in row:
            continue
        value = row[col]
        if col in ("latitude", "longitude", "rating"):
            value = num(value, float)
        elif col == "review_count":
            value = num(value, lambda v: int(float(v)))
        else:
            value = (value or "").strip() if isinstance(value, str) else (value or "")
        setattr(lead, col, value)
    return lead
