from __future__ import annotations

from collections.abc import Iterable


def has_overture_attribution(attributions: object) -> bool:
    if isinstance(attributions, str):
        values: Iterable[object] = [attributions]
    elif isinstance(attributions, (list, tuple, set)):
        values = attributions
    else:
        return False
    return any("overture maps foundation" in str(value).lower() or "overturemaps.org" in str(value).lower()
               for value in values)


def is_overture_backed_convenience_store(source: object, category: object, attributions: object) -> bool:
    """Accept a convenience-store POI with Overture provenance, even if JFF is representative."""
    if category != "convenience_store":
        return False
    return source == "overture" or has_overture_attribution(attributions)
