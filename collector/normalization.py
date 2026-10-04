from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from .prefectures import PREFECTURES


ALIASES = json.loads((Path(__file__).parent / "brands.json").read_text())


def compact(value: str) -> str:
    return re.sub(r"[\s\u3000・･\-‐ー－!！]+", "", unicodedata.normalize("NFKC", value).lower())


def brand_family(name: str) -> str | None:
    value = compact(name)
    for family, aliases in ALIASES.items():
        if any(value.startswith(compact(alias)) for alias in aliases):
            return family
    return None


def normalize_name(name: str) -> str:
    value = compact(name)
    for aliases in ALIASES.values():
        for alias in sorted(aliases, key=len, reverse=True):
            value = value.replace(compact(alias), "")
    return value.replace("店", "")


def normalize_address(address: str) -> str:
    value = unicodedata.normalize("NFKC", address).lower()
    for prefecture in PREFECTURES:
        if value.startswith(prefecture):
            value = value[len(prefecture):]
            break
    value = value.replace("丁目", "-").replace("番地", "-").replace("番", "-").replace("号", "")
    return re.sub(r"[\s\u3000‐ー－-]+", "-", value).strip("-")
