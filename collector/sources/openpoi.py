from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from collector.model import RawStore
from collector.matching import distance_m
from collector.normalization import brand_family as detect_brand, normalize_name
from collector.prefectures import PREFECTURES
from .base import StoreSource


# Includes the inhabited islands as well as the main islands of Japan.
JAPAN_BBOX = (122.0, 20.0, 154.5, 46.1)
KEYWORDS = {
    "FAMILY_MART": ["ファミリーマート", "ファミマ", "FamilyMart"],
    "LAWSON": ["ローソン", "LAWSON"],
    "SEVEN_ELEVEN": ["セブンイレブン", "セブン-イレブン", "セブン‐イレブン", "セブン－イレブン", "7-Eleven", "Seven Eleven"],
}


class OpenPoiSource(StoreSource):
    """Official /v1/search client; saturated leaves fail instead of silently truncating."""
    require_nonempty_each_family = False
    guard_coverage = True
    managed_presence_families = set(KEYWORDS)
    coverage_policy_version = "overture-convenience-store-v2"

    def __init__(self, base_url: str | None = None, limit: int = 200, max_depth: int = 12, cache_key: str | None = None, cache_dir: Path | None = None):
        self.base_url = (base_url or os.getenv("OPENPOI_BASE_URL", "https://api.openpoiapi.com")).rstrip("/")
        self.limit = limit
        self.max_depth = max_depth
        self.requests = 0
        self.cache: dict[str, list[RawStore]] = {}
        self.cache_key = cache_key
        self.cache_dir = cache_dir

    def _cache_path(self, brand_family: str) -> Path | None:
        if not self.cache_dir or not self.cache_key:
            return None
        digest = sha256(self.cache_key.encode()).hexdigest()[:20]
        return self.cache_dir / f"{digest}-{brand_family}.json"

    def _load_family(self, brand_family: str) -> list[RawStore]:
        path = self._cache_path(brand_family)
        if path and path.exists() and os.getenv("OPENPOI_REFRESH_CACHE") != "1":
            payload = json.loads(path.read_text(encoding="utf-8"))
            cache_policy = self.coverage_policy_version
            if payload.get("version") == 3 and payload.get("policy") == cache_policy and payload.get("base_url") == self.base_url and payload.get("keywords") == KEYWORDS[brand_family]:
                rows = [RawStore(**row) for row in payload["stores"]]
                if rows:
                    print(f"OpenPOI {brand_family}: {len(rows)} stores from local cache", flush=True)
                    return rows
        rows = self._fetch_family(brand_family)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            cache_policy = self.coverage_policy_version
            temporary.write_text(json.dumps({"version": 3, "policy": cache_policy, "base_url": self.base_url, "keywords": KEYWORDS[brand_family], "stores": [asdict(row) for row in rows]}, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
        return rows

    def prime(self) -> None:
        for brand_family in KEYWORDS:
            if brand_family not in self.cache:
                self.cache[brand_family] = self._load_family(brand_family)

    def coverage_counts(self) -> dict[str, int]:
        self.prime()
        return {family: sum(store.prefecture in PREFECTURES for store in self.cache[family])
                for family in KEYWORDS}

    def _search(self, keyword: str, bbox: tuple[float, float, float, float]) -> list[dict]:
        query = urlencode({"q": keyword, "bbox": ",".join(map(str, bbox)), "limit": self.limit})
        for attempt in range(4):
            try:
                with urlopen(f"{self.base_url}/v1/search?{query}", timeout=30) as response:
                    body = json.load(response)
                break
            except (HTTPError, URLError, TimeoutError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
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
        if prefecture not in PREFECTURES:
            raise ValueError(f"Unknown prefecture: {prefecture}")
        if brand_family not in self.cache:
            self.cache[brand_family] = self._load_family(brand_family)
        # Count map POIs classified as physical convenience stores for all
        # chains. Name-only search also returns permits, ATMs, lockers, and
        # other non-store points.
        stores = [store for store in self.cache[brand_family]
                  if store.source == "overture" and store.source_category == "convenience_store"]
        return [store for store in stores if store.prefecture == prefecture]

    def _fetch_family(self, brand_family: str) -> list[RawStore]:
        seen: set[tuple] = set()
        stores: list[RawStore] = []
        by_name: dict[tuple[str, str], list[int]] = {}
        for keyword in KEYWORDS[brand_family]:
            for row in self._partition(keyword, JAPAN_BBOX):
                if not (
                    row.get("source") == "overture" and row.get("category") == "convenience_store"
                ):
                    # Filter before cross-source deduplication so permits,
                    # service points, and secondary datasets cannot replace
                    # the actual map POI for any chain.
                    continue
                prefecture = row.get("prefecture")
                if prefecture not in PREFECTURES:
                    prefecture = next((name for name in PREFECTURES if str(row.get("address", "")).startswith(name)), None)
                if prefecture is None:
                    continue
                if detect_brand(row.get("name", "")) != brand_family:
                    continue
                if not isinstance(row.get("lat"), (int, float)) or not isinstance(row.get("lng"), (int, float)):
                    continue
                key = (row.get("source"), row.get("name"), row.get("address"), round(row["lat"], 7), round(row["lng"], 7))
                if key in seen:
                    continue
                seen.add(key)
                name_key = (prefecture, normalize_name(row["name"]))
                duplicate = next((index for index in by_name.get(name_key, []) if distance_m(stores[index].lat, stores[index].lng, row["lat"], row["lng"]) <= 30), None)
                if duplicate is not None:
                    old = stores[duplicate]
                    records = old.raw_payload.get("records", [old.raw_payload])
                    prefer_new = bool(row.get("address") and not old.address)
                    stores[duplicate] = replace(old,
                        name=row["name"] if prefer_new else old.name,
                        address=row.get("address", "") if prefer_new else old.address,
                        lat=row["lat"] if prefer_new else old.lat,
                        lng=row["lng"] if prefer_new else old.lng,
                        city=row.get("city", "") if prefer_new else old.city,
                        source_category=row.get("category") if prefer_new else old.source_category,
                        source_business_type=row.get("business_type") if prefer_new else old.source_business_type,
                        licenses=list(dict.fromkeys(old.licenses + (row.get("licenses") or []))),
                        attributions=list(dict.fromkeys(old.attributions + (row.get("attributions") or []))),
                        raw_payload={"records": records + [row]})
                    continue
                by_name.setdefault(name_key, []).append(len(stores))
                stores.append(RawStore(name=row["name"], address=row.get("address", ""), lat=row["lat"], lng=row["lng"], prefecture=prefecture, city=row.get("city", ""), source="overture", source_store_id=row.get("source_store_id"), source_category=row.get("category"), source_business_type=row.get("business_type"), licenses=row.get("licenses") or [], attributions=row.get("attributions") or [], raw_payload=row))
        if not stores:
            raise RuntimeError(f"No {brand_family} stores found in Japan; refusing incomplete snapshot")
        print(f"OpenPOI {brand_family}: {len(stores)} stores ({self.requests} requests total)", flush=True)
        return stores
