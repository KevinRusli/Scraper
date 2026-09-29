"""Write leads to CSV or JSON."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence

from .models import CSV_COLUMNS


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "x"


def default_output_path(sector: str, country: str, cities: Sequence[str], fmt: str, folder: str = "results") -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    parts = [stamp, slug(sector), slug(country)]
    if cities:
        parts.append(slug("-".join(cities))[:60])
    return Path(folder) / ("_".join(parts) + f".{fmt}")


def write_rows(rows: Iterable[dict], path: Path, fmt: str, columns: List[str] = CSV_COLUMNS) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if fmt == "json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        # utf-8-sig so Excel opens non-ASCII names correctly.
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in columns})
    return path


def read_rows(path: Path) -> List[dict]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else [data]
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [{(k or "").strip().lower(): v for k, v in row.items()} for row in csv.DictReader(fh)]
