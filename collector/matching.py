from difflib import SequenceMatcher
from math import asin, cos, radians, sin, sqrt

from .model import RawStore
from .normalization import normalize_address, normalize_name


def distance_m(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    # Identity matching only; production proximity uses PostGIS geography.
    radius = 6371008.8
    p1, p2 = radians(a_lat), radians(b_lat)
    dp, dl = radians(b_lat - a_lat), radians(b_lng - a_lng)
    h = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * radius * asin(sqrt(h))


def matches(raw: RawStore, old: dict, family: str) -> bool:
    if family != old["brand_family"]:
        return False
    if raw.source_store_id and old.get("source_store_id") and raw.source == old.get("source"):
        return raw.source_store_id == old["source_store_id"]
    address = normalize_address(raw.address)
    if address and old.get("normalized_address") and address == old["normalized_address"]:
        return True
    return (
        distance_m(raw.lat, raw.lng, old["lat"], old["lng"]) <= 30
        and SequenceMatcher(None, normalize_name(raw.name), old["normalized_name"]).ratio() >= 0.85
    )
