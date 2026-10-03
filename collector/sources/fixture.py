from __future__ import annotations

import json
from pathlib import Path

from collector.model import RawStore
from collector.normalization import brand_family as detect_brand
from .base import StoreSource


class FixtureSource(StoreSource):
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def fetch_stores(self, prefecture: str, brand_family: str) -> list[RawStore]:
        rows = json.loads(self.path.read_text(encoding="utf-8"))["stores"]
        return [RawStore(**row) for row in rows if row.get("prefecture") == prefecture and detect_brand(row["name"]) == brand_family]
