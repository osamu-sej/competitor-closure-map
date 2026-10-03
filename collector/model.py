from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RawStore:
    name: str
    address: str
    lat: float
    lng: float
    prefecture: str = "神奈川県"
    city: str = ""
    source: str = "fixture"
    source_store_id: str | None = None
    source_category: str | None = None
    source_business_type: str | None = None
    licenses: list[str] = field(default_factory=list)
    attributions: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


FAMILIES = ("FAMILY_MART", "LAWSON", "SEVEN_ELEVEN")
