"""Deterministic snapshot state machine used by fixture and PostgreSQL modes."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .matching import distance_m, matches
from .model import FAMILIES, RawStore
from .normalization import brand_family, normalize_address, normalize_name
from .prefectures import PREFECTURES


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_state() -> dict:
    return {"runs": [], "stores": [], "observations": [], "events": [], "evidence": []}


def promotion_status(missing_count: int, threshold: int) -> str:
    return "CLOSED_SUSPECTED" if missing_count >= threshold else "MISSING"


def within_distance(distance: float | None, threshold: float) -> bool:
    return distance is not None and distance <= threshold


def apply_snapshot(state: dict, source, snapshot_key: str, observed_at: str, missing_threshold: int = 2, prefecture: str = "神奈川県") -> dict:
    if missing_threshold not in (1, 2):
        raise ValueError("MISSING_THRESHOLD must be 1 or 2")
    if prefecture not in PREFECTURES:
        raise ValueError(f"Unknown prefecture: {prefecture}")
    existing = next((run for run in state["runs"] if run["snapshot_key"] == snapshot_key), None)
    if existing:
        return existing
    fetched: list[RawStore] = []
    family_counts: dict[str, int] = {}
    for family in FAMILIES:
        family_rows = source.fetch_stores(prefecture, family)
        if getattr(source, "require_nonempty_each_family", False) and not family_rows:
            raise RuntimeError(f"No {family} stores returned; refusing incomplete snapshot")
        family_counts[family] = len(family_rows)
        fetched += family_rows
    source_name = source.__class__.__name__.replace("Source", "").lower()
    prior_run = next((r for r in reversed(state["runs"]) if r["source"] == source_name and r["prefecture"] == prefecture and r["status"] == "succeeded"), None)
    if prior_run and getattr(source, "guard_coverage", False):
        previous = prior_run.get("metadata", {}).get("families", {})
        for family, count in family_counts.items():
            if previous.get(family, 0) >= 20 and count < previous[family] * 0.95:
                raise RuntimeError(f"{family} coverage fell from {previous[family]} to {count}; refusing incomplete snapshot")
    # Fetch completes before mutation; a failed source never creates a partial run.
    run = {"id": str(uuid4()), "snapshot_key": snapshot_key, "source": source_name, "prefecture": prefecture, "started_at": utc_now(), "finished_at": None, "status": "running", "store_count": 0, "metadata": {}}
    source_run_ids = {r["id"] for r in state["runs"] if r["source"] == source_name and r["prefecture"] == prefecture and r["status"] == "succeeded"}
    prior_ids = {observation["store_id"] for observation in state["observations"] if observation["snapshot_run_id"] in source_run_ids}
    observed_ids: set[str] = set()
    counts = {"fetched": len(fetched), "families": family_counts, "requests": getattr(source, "requests", None), "normalized": 0, "matched": 0, "new": 0, "missing": 0, "seven_missing": 0, "reopened": 0, "closure_candidates": 0}
    # Most stores have a usable address. Index that and nearby coordinate cells
    # so a prefecture-sized snapshot does not compare every pair of stores.
    by_address: dict[tuple[str, str], list[dict]] = {}
    by_cell: dict[tuple[str, int, int], list[dict]] = {}
    cell_size = 0.0002
    def index_store(store: dict) -> None:
        if store["normalized_address"]:
            by_address.setdefault((store["brand_family"], store["normalized_address"]), []).append(store)
        cell = (store["brand_family"], int(store["lat"] // cell_size), int(store["lng"] // cell_size))
        by_cell.setdefault(cell, []).append(store)
    for old in state["stores"]:
        if old["prefecture"] == prefecture:
            index_store(old)
    for raw in fetched:
        family = brand_family(raw.name)
        if family is None or raw.prefecture != prefecture or not (-90 <= raw.lat <= 90 and -180 <= raw.lng <= 180):
            continue
        counts["normalized"] += 1
        address = normalize_address(raw.address)
        lat_cell, lng_cell = int(raw.lat // cell_size), int(raw.lng // cell_size)
        nearby = [store for lat_offset in range(-2, 3) for lng_offset in range(-2, 3)
                  for store in by_cell.get((family, lat_cell + lat_offset, lng_cell + lng_offset), [])]
        possible = by_address.get((family, address), []) + nearby if address else nearby
        candidates = [store for store in {s["id"]: s for s in possible}.values()
                      if store["id"] not in observed_ids and store["source"] == raw.source and matches(raw, store, family)]
        # Ambiguous identity is left separate rather than merging automatically.
        store = candidates[0] if len(candidates) == 1 else None
        if store:
            counts["matched"] += 1
            if store["current_presence"] != "PRESENT":
                counts["reopened"] += 1
                for event in state["events"]:
                    if event["store_id"] == store["id"] and event["status"] not in ("REOPENED",):
                        event["status"] = "REOPENED"
                        event["updated_at"] = observed_at
            store.update(canonical_name=raw.name, normalized_name=normalize_name(raw.name), address=raw.address, normalized_address=normalize_address(raw.address), city=raw.city, lat=raw.lat, lng=raw.lng, source=raw.source, source_store_id=raw.source_store_id, last_seen_at=observed_at, current_presence="PRESENT", missing_count=0, updated_at=observed_at)
        else:
            store = {"id": str(uuid4()), "brand_family": family, "canonical_name": raw.name, "normalized_name": normalize_name(raw.name), "address": raw.address, "normalized_address": normalize_address(raw.address), "prefecture": raw.prefecture, "city": raw.city, "lat": raw.lat, "lng": raw.lng, "source": raw.source, "source_store_id": raw.source_store_id, "first_seen_at": observed_at, "last_seen_at": observed_at, "current_presence": "PRESENT", "missing_count": 0, "created_at": observed_at, "updated_at": observed_at}
            state["stores"].append(store)
            index_store(store)
            counts["new"] += 1
        observed_ids.add(store["id"])
        state["observations"].append({"id": str(uuid4()), "snapshot_run_id": run["id"], "store_id": store["id"], "source": raw.source, "source_store_id": raw.source_store_id, "observed_name": raw.name, "observed_address": raw.address, "lat": raw.lat, "lng": raw.lng, "source_category": raw.source_category, "source_business_type": raw.source_business_type, "licenses": raw.licenses, "attributions": raw.attributions, "raw_payload": raw.raw_payload, "fetched_at": utc_now(), "observed_at": observed_at})
    for seven in state["stores"]:
        if seven["id"] in prior_ids and seven["id"] not in observed_ids and seven["brand_family"] == "SEVEN_ELEVEN":
            seven["current_presence"] = "MISSING"
            seven["missing_count"] = seven.get("missing_count", 0) + 1
            counts["seven_missing"] += 1
    sevens = [s for s in state["stores"] if s["brand_family"] == "SEVEN_ELEVEN" and s["current_presence"] == "PRESENT"]
    for store in state["stores"]:
        if store["id"] not in prior_ids or store["id"] in observed_ids or store["brand_family"] == "SEVEN_ELEVEN":
            continue
        store["current_presence"] = "MISSING"
        store["missing_count"] = store.get("missing_count", 0) + 1
        counts["missing"] += 1
        event = next((event for event in state["events"] if event["store_id"] == store["id"] and event["status"] != "REOPENED"), None)
        if event:
            if event["status"] == "MISSING":
                event["status"] = promotion_status(store["missing_count"], missing_threshold)
                event["updated_at"] = observed_at
            continue
        last_observation = max((o for o in state["observations"] if o["store_id"] == store["id"] and o["snapshot_run_id"] in source_run_ids), key=lambda o: o["observed_at"])
        nearest = min(sevens, key=lambda seven: distance_m(store["lat"], store["lng"], seven["lat"], seven["lng"])) if sevens else None
        distance = distance_m(store["lat"], store["lng"], nearest["lat"], nearest["lng"]) if nearest else None
        state["events"].append({"id": str(uuid4()), "store_id": store["id"], "detected_at": observed_at, "last_seen_at": store["last_seen_at"], "status": promotion_status(store["missing_count"], missing_threshold), "closure_date": None, "reason": None, "confidence": "LOW", "nearest_seven_store_id": nearest["id"] if nearest else None, "distance_m": round(distance, 2) if distance is not None else None, "within_100m": within_distance(distance, 100), "last_observation_id": last_observation["id"], "created_at": observed_at, "updated_at": observed_at})
        counts["closure_candidates"] += 1
    run.update(finished_at=utc_now(), status="succeeded", store_count=len(observed_ids), metadata=counts)
    state["runs"].append(run)
    return run


def add_evidence(state: dict, store_name: str, evidence: dict) -> None:
    store = next(s for s in state["stores"] if s["canonical_name"] == store_name)
    event = next(e for e in state["events"] if e["store_id"] == store["id"] and e["status"] != "REOPENED")
    add_event_evidence(state, event["id"], evidence)


def add_event_evidence(state: dict, event_id: str, evidence: dict) -> None:
    event = next(e for e in state["events"] if e["id"] == event_id and e["status"] != "REOPENED")
    if any(e["closure_event_id"] == event["id"] and e["title"] == evidence["title"] for e in state["evidence"]):
        return
    row = {"id": str(uuid4()), "closure_event_id": event["id"], "evidence_type": evidence["evidence_type"], "title": evidence["title"], "source_ref": evidence.get("source_ref"), "evidence_date": evidence.get("evidence_date"), "summary": evidence.get("summary", ""), "supports_closure": evidence.get("supports_closure", False), "created_at": utc_now()}
    state["evidence"].append(row)
    if evidence.get("confirm") and evidence.get("supports_closure"):
        event.update(status="CLOSED_CONFIRMED", closure_date=evidence.get("closure_date"), reason=evidence.get("summary"), confidence="HIGH", updated_at=utc_now())
