from __future__ import annotations

import json
import os
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from collector.model import RawStore
from collector.normalization import brand_family as detect_brand
from .base import StoreSource


KANAGAWA_BBOX = (138.90, 35.12, 139.86, 35.68)
KEYWORDS = {
    "FAMILY_MART": ["ファミリーマート", "ファミマ", "FamilyMart"],
    "LAWSON": ["ローソン", "LAWSON"],
    "SEVEN_ELEVEN": ["セブンイレブン", "セブン-イレブン", "7-Eleven"],
}


class OpenPoiSource(StoreSource):
    """Official /v1/search client; saturated leaves fail instead of silently truncating."""
    require_nonempty_each_family = True

    def __init__(self, base_url: str | None = None, limit: int = 200, max_depth: int = 12):
        self.base_url = (base_url or os.getenv("OPENPOI_BASE_URL", "https://api.openpoiapi.com")).rstrip("/")
        self.limit = limit
        self.max_depth = max_depth
        self.requests = 0

    def _search(self, keyword: str, bbox: tuple[float, float, float, float]) -> list[dict]:
        query = urlencode({"q": keyword, "bbox": ",".join(map(str, bbox)), "limit": self.limit})
        with urlopen(f"{self.base_url}/v1/search?{query}", timeout=30) as response:
            body = json.load(response)
        self.requests += 1
        results = body.get("results")
        if not isinstance(results, list) or body.get("count") != len(results):
            raise ValueError("Unexpected OpenPOI search response")
        time.sleep(0.05)
        return results

    def _partition(self, keyword: str, bbox: tuple[float, float, float, float], depth: int = 0) -> list[dict]:
        results = self._search(keyword, bbox)
        if len(results) < self.limit:
            return results
        if depth >= self.max_depth:
            raise RuntimeError(f"OpenPOI result saturated at depth {depth}: {keyword} {bbox}")
        west, south, east, north = bbox
        mid_lng, mid_lat = (west + east) / 2, (south + north) / 2
        boxes = [(west, south, mid_lng, mid_lat), (mid_lng, south, east, mid_lat), (west, mid_lat, mid_lng, north), (mid_lng, mid_lat, east, north)]
        return [row for box in boxes for row in self._partition(keyword, box, depth + 1)]

    def fetch_stores(self, prefecture: str, brand_family: str) -> list[RawStore]:
        if prefecture != "神奈川県":
            raise ValueError("MVP supports 神奈川県 only")
        seen: set[tuple] = set()
        stores: list[RawStore] = []
        for keyword in KEYWORDS[brand_family]:
            for row in self._partition(keyword, KANAGAWA_BBOX):
                if row.get("prefecture") != prefecture and not str(row.get("address", "")).startswith(prefecture):
                    continue
                if detect_brand(row.get("name", "")) != brand_family:
                    continue
                if not isinstance(row.get("lat"), (int, float)) or not isinstance(row.get("lng"), (int, float)):
                    continue
                key = (row.get("source"), row.get("name"), row.get("address"), round(row["lat"], 7), round(row["lng"], 7))
                if key in seen:
                    continue
                seen.add(key)
                stores.append(RawStore(name=row["name"], address=row.get("address", ""), lat=row["lat"], lng=row["lng"], prefecture=prefecture, city=row.get("city", ""), source="openpoi", source_category=row.get("category"), source_business_type=row.get("business_type"), licenses=row.get("licenses") or [], attributions=row.get("attributions") or [], raw_payload=row))
        return stores
