"""Deterministic snapshot state machine used by fixture and PostgreSQL modes."""
from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from uuid import uuid4

from .matching import distance_m, matches
from .model import FAMILIES, RawStore
from .normalization import brand_family, normalize_address, normalize_name
from .prefectures import PREFECTURES
from .source_policy import is_overture_backed_convenience_store


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_state() -> dict:
    return {"runs": [], "stores": [], "observations": [], "events": [], "evidence": []}


def promotion_status(missing_count: int, threshold: int) -> str:
    return "CLOSED_SUSPECTED" if missing_count >= threshold else "MISSING"


def within_distance(distance: float | None, threshold: float) -> bool:
    return distance is not None and distance <= threshold


def _validated_national_coverage_families(state: dict, source, source_name: str, coverage_policy_version: str, managed_presence_families: set[str]) -> set[str]:
    coverage_counts = getattr(source, "coverage_counts", None)
    if not callable(coverage_counts):
        return set()
    latest_by_prefecture: dict[str, dict] = {}
    for run in state["runs"]:
        if run["source"] != source_name or run["status"] != "succeeded":
            continue
        current = latest_by_prefecture.get(run["prefecture"])
        if current is None or str(run.get("finished_at", "")) > str(current.get("finished_at", "")):
            latest_by_prefecture[run["prefecture"]] = run
    if len(latest_by_prefecture) != len(PREFECTURES):
        return set()
    baseline_key = tuple(sorted((prefecture, str(run.get("snapshot_key", ""))) for prefecture, run in latest_by_prefecture.items()))
    cache = getattr(source, "_coverage_validation_cache", None)
    if cache and cache[0] == baseline_key:
        return set(cache[1])
    previous_policy_version = {str(run.get("metadata", {}).get("coverage_policy_version", "default")) for run in latest_by_prefecture.values()}
    policy_changed = len(previous_policy_version) != 1 or next(iter(previous_policy_version)) != coverage_policy_version
    previous_totals = {family: sum(int(run.get("metadata", {}).get("families", {}).get(family, 0)) for run in latest_by_prefecture.values()) for family in FAMILIES}
    current_totals = coverage_counts()
    validated: set[str] = set()
    for family, count in current_totals.items():
        previous = previous_totals.get(family, 0)
        changed_scope = family in managed_presence_families and policy_changed
        if changed_scope:
            continue
        if previous and count < previous - max(1, ceil(previous * 0.05)):
            raise RuntimeError(f"{family} nationwide coverage fell from {previous} to {count}; refusing incomplete snapshot")
        validated.add(family)
    setattr(source, "_coverage_validation_cache", (baseline_key, frozenset(validated)))
    return validated


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
    managed_presence_families = set(getattr(source, "managed_presence_families", set()))
    coverage_policy_version = str(getattr(source, "coverage_policy_version", "default"))
    source_name = source.__class__.__name__.replace("Source", "").lower()
    globally_validated_families = _validated_national_coverage_families(state, source, source_name, coverage_policy_version, managed_presence_families) if getattr(source, "guard_coverage", False) else set()
    prior_run = next((r for r in reversed(state["runs"]) if r["source"] == source_name and r["prefecture"] == prefecture and r["status"] == "succeeded"), None)
    if prior_run and getattr(source, "guard_coverage", False):
        previous = prior_run.get("metadata", {}).get("families", {})
        previous_policy_version = str(prior_run.get("metadata", {}).get("coverage_policy_version", "default"))
        for family, count in family_counts.items():
            previous_count = previous.get(family, 0)
            policy_changed_for_family = family in managed_presence_families and previous_policy_version != coverage_policy_version
            if family in globally_validated_families:
                if previous_count and count < previous_count - max(1, ceil(previous_count * 0.20)):
                    raise RuntimeError(f"{family} coverage in {prefecture} fell sharply from {previous_count} to {count}; refusing incomplete snapshot")
                continue
            if not policy_changed_for_family and previous_count and count < previous_count - max(1, ceil(previous_count * 0.05)):
                raise RuntimeError(f"{family} coverage fell from {previous[family]} to {count}; refusing incomplete snapshot")
    # Fetch completes before mutation; a failed source never creates a partial run.
    run = {"id": str(uuid4()), "snapshot_key": snapshot_key, "source": source_name, "prefecture": prefecture, "started_at": utc_now(), "finished_at": None, "status": "running", "store_count": 0, "metadata": {}}
    source_run_ids = {r["id"] for r in state["runs"] if r["source"] == source_name and r["prefecture"] == prefecture and r["status"] == "succeeded"}
    prior_ids = {observation["store_id"] for observation in state["observations"] if observation["snapshot_run_id"] in source_run_ids}
    observed_ids: set[str] = set()
    counts = {"fetched": len(fetched), "families": family_counts, "coverage_policy_version": coverage_policy_version, "requests": getattr(source, "requests", None), "normalized": 0, "matched": 0, "new": 0, "missing": 0, "out_of_scope": 0, "seven_missing": 0, "reopened": 0, "closure_candidates": 0}
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
                      if store["id"] not in observed_ids
                      and (store["source"] == raw.source or (
                          family in managed_presence_families
                          and store["source"] in ("openpoi", "overture", "jff")
                          and raw.source in ("overture", "jff")
                      ))
                      and matches(raw, store, family)]
        # A mall or station can contain multiple same-brand shops with the same
        # normalized address. Resolve an exact name and nearby position first;
        # address-only matching must remain unique.
        exact = [store for store in candidates
                 if store["normalized_name"] == normalize_name(raw.name)
                 and distance_m(raw.lat, raw.lng, store["lat"], store["lng"]) <= 30]
        store = exact[0] if len(exact) == 1 else candidates[0] if len(candidates) == 1 else None
        if store:
            counts["matched"] += 1
            if store["current_presence"] != "PRESENT":
                counts["reopened"] += 1
                for event in state["events"]:
                    if event["store_id"] == store["id"] and event["status"] not in ("REOPENED", "OUT_OF_SCOPE"):
                        event["status"] = "REOPENED"
                        event["updated_at"] = observed_at
            store.update(canonical_name=raw.name, normalized_name=normalize_name(raw.name), address=raw.address, normalized_address=normalize_address(raw.address), city=raw.city, lat=raw.lat, lng=raw.lng, source=raw.source, source_store_id=raw.source_store_id, source_category=raw.source_category, source_business_type=raw.source_business_type, licenses=list(raw.licenses), attributions=list(raw.attributions), last_seen_at=observed_at, current_presence="PRESENT", missing_count=0, updated_at=observed_at)
        else:
            store = {"id": str(uuid4()), "brand_family": family, "canonical_name": raw.name, "normalized_name": normalize_name(raw.name), "address": raw.address, "normalized_address": normalize_address(raw.address), "prefecture": raw.prefecture, "city": raw.city, "lat": raw.lat, "lng": raw.lng, "source": raw.source, "source_store_id": raw.source_store_id, "source_category": raw.source_category, "source_business_type": raw.source_business_type, "licenses": list(raw.licenses), "attributions": list(raw.attributions), "first_seen_at": observed_at, "last_seen_at": observed_at, "current_presence": "PRESENT", "missing_count": 0, "created_at": observed_at, "updated_at": observed_at}
            state["stores"].append(store)
            index_store(store)
            counts["new"] += 1
        observed_ids.add(store["id"])
        state["observations"].append({"id": str(uuid4()), "snapshot_run_id": run["id"], "store_id": store["id"], "source": raw.source, "source_store_id": raw.source_store_id, "observed_name": raw.name, "observed_address": raw.address, "lat": raw.lat, "lng": raw.lng, "source_category": raw.source_category, "source_business_type": raw.source_business_type, "licenses": raw.licenses, "attributions": raw.attributions, "raw_payload": raw.raw_payload, "fetched_at": utc_now(), "observed_at": observed_at})
    for store in state["stores"]:
        if store["id"] not in prior_ids or store["id"] in observed_ids or store["current_presence"] == "SUPPRESSED":
            continue
        if store["brand_family"] in managed_presence_families and not is_overture_backed_convenience_store(
            store.get("source"), store.get("source_category"), store.get("attributions")
        ):
            store.update(current_presence="SUPPRESSED", missing_count=0, updated_at=observed_at)
            for event in state["events"]:
                if event["store_id"] == store["id"] and event["status"] != "OUT_OF_SCOPE":
                    event.update(status="OUT_OF_SCOPE", reason="対象ブランドの候補をコンビニカテゴリとOverture出典に限定", updated_at=observed_at)
            counts["out_of_scope"] += 1
            continue
    for store in state["stores"]:
        if (store["id"] in prior_ids and store["id"] not in observed_ids
                and store["brand_family"] == "SEVEN_ELEVEN"
                and store["current_presence"] != "SUPPRESSED"):
            store["current_presence"] = "MISSING"
            store["missing_count"] = store.get("missing_count", 0) + 1
            counts["seven_missing"] += 1
    sevens = [s for s in state["stores"] if s["brand_family"] == "SEVEN_ELEVEN" and s["current_presence"] == "PRESENT"]
    for store in state["stores"]:
        if store["id"] not in prior_ids or store["id"] in observed_ids or store["brand_family"] == "SEVEN_ELEVEN" or store["current_presence"] == "SUPPRESSED":
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
    event = next(e for e in state["events"] if e["store_id"] == store["id"] and e["status"] not in ("REOPENED", "OUT_OF_SCOPE"))
    add_event_evidence(state, event["id"], evidence)


def add_event_evidence(state: dict, event_id: str, evidence: dict) -> None:
    event = next(e for e in state["events"] if e["id"] == event_id and e["status"] not in ("REOPENED", "OUT_OF_SCOPE"))
    if any(e["closure_event_id"] == event["id"] and e["title"] == evidence["title"] for e in state["evidence"]):
        return
    row = {"id": str(uuid4()), "closure_event_id": event["id"], "evidence_type": evidence["evidence_type"], "title": evidence["title"], "source_ref": evidence.get("source_ref"), "evidence_date": evidence.get("evidence_date"), "summary": evidence.get("summary", ""), "supports_closure": evidence.get("supports_closure", False), "created_at": utc_now()}
    state["evidence"].append(row)
    if evidence.get("confirm") and evidence.get("supports_closure"):
        event.update(status="CLOSED_CONFIRMED", closure_date=evidence.get("closure_date"), reason=evidence.get("summary"), confidence="HIGH", updated_at=utc_now())
