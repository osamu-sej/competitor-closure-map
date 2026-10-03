from __future__ import annotations

import csv
from pathlib import Path

from collector.model import RawStore
from collector.normalization import brand_family as detect_brand
from .base import StoreSource


class CsvSource(StoreSource):
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def fetch_stores(self, prefecture: str, brand_family: str) -> list[RawStore]:
        with self.path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        return [RawStore(name=row["name"], address=row["address"], lat=float(row["lat"]), lng=float(row["lng"]), prefecture=row["prefecture"], city=row.get("city", ""), source="csv", source_store_id=row.get("source_store_id") or None, raw_payload=row) for row in rows if row["prefecture"] == prefecture and detect_brand(row["name"]) == brand_family]
