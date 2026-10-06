import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from .engine import add_evidence, add_event_evidence, apply_snapshot, new_state, promotion_status, within_distance
from .matching import distance_m
from .sources.csv_source import CsvSource
from .sources.fixture import FixtureSource
from .sources.openpoi import OpenPoiSource
from .prefectures import PREFECTURES


ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "fixture-state.json"


def recover_sheets_snapshot(state: dict, snapshot_key: str, *, started_at: str, finished_at: str,
                            source_requests: int, raw_family_totals: dict[str, int]) -> dict:
    """Finish a nationwide Sheets snapshot whose store writes succeeded but later tabs hit a quota."""
    from .prefectures import PREFECTURES

    keys = {prefecture: f"{snapshot_key}:{prefecture}" for prefecture in PREFECTURES}
    stores_by_key: dict[str, list[dict]] = {key: [] for key in keys.values()}
    for store in state.get("stores", []):
        key = str(store.get("last_snapshot_key", ""))
        if key in stores_by_key:
            stores_by_key[key].append(store)
    observed_at_values = [str(store.get("last_observed_at", "")) for rows in stores_by_key.values() for store in rows]
    observed_at = max(observed_at_values, default="")
    if not observed_at:
        raise RuntimeError(f"No persisted stores found for snapshot {snapshot_key}")

    successful_keys = {str(run.get("snapshot_key", run.get("id", ""))) for run in state.get("runs", [])
                       if run.get("status") == "succeeded"}
    for prefecture, key in keys.items():
        if key in successful_keys:
            continue
        rows = stores_by_key[key]
        families = {family: sum(store.get("brand_family") == family for store in rows)
                    for family in ("FAMILY_MART", "LAWSON", "SEVEN_ELEVEN")}
        if not rows:
            raise RuntimeError(f"No persisted stores found for {prefecture}; refusing to mark its snapshot successful")
        missing_count = sum(store.get("current_presence") == "MISSING" and store.get("updated_at") == observed_at
                            and store.get("prefecture") == prefecture for store in state.get("stores", []))
        new_count = sum(store.get("first_seen_at") == observed_at for store in rows)
        state.setdefault("runs", []).append({
            "id": key, "snapshot_key": key, "source": "openpoi", "prefecture": prefecture,
            "started_at": started_at, "finished_at": finished_at, "status": "succeeded",
            "store_count": len(rows), "metadata": {
                "fetched": len(rows), "families": families, "requests": source_requests,
                "normalized": len(rows), "matched": len(rows) - new_count, "new": new_count,
                "missing": missing_count, "recovered_after_partial_write": True,
                "source_family_totals": raw_family_totals,
            },
        })

    # A partial Sheets write can leave Stores ahead of Changes. Rebuild any missing
    # change rows by comparing the current store against the latest recorded change.
    stores_by_id = {str(store.get("id", "")): store for store in state.get("stores", [])}
    current_keys = set(keys.values())
    for change in state.get("changes", []):
        change_at = str(change.get("observed_at", ""))
        store_id = str(change.get("store_id", ""))
        if change_at != observed_at or not str(change.get("snapshot_key", "")).startswith(snapshot_key + ":"):
            continue
        store = stores_by_id.get(store_id)
        if not store:
            continue
        prefecture = str(store.get("prefecture", ""))
        if str(store.get("last_snapshot_key", "")) in current_keys:
            change_key = str(store["last_snapshot_key"])
        elif store.get("current_presence") == "MISSING" and store.get("updated_at") == observed_at and prefecture in keys:
            change_key = keys[prefecture]
        else:
            continue
        change["snapshot_key"] = change_key
        change["id"] = f"{change_key}:{store_id}:{change.get('change_type', '')}"

    latest_change: dict[str, dict] = {}
    existing_change_at_time: set[tuple[str, str, str]] = set()
    for change in state.get("changes", []):
        store_id = str(change.get("store_id", ""))
        if not store_id:
            continue
        old = latest_change.get(store_id)
        if old is None or str(change.get("observed_at", "")) >= str(old.get("observed_at", "")):
            latest_change[store_id] = change
        existing_change_at_time.add((store_id, str(change.get("observed_at", "")), str(change.get("change_type", ""))))

    recovered_changes = 0
    for store in state.get("stores", []):
        store_id = str(store.get("id", ""))
        prefecture = str(store.get("prefecture", ""))
        current_key = str(store.get("last_snapshot_key", ""))
        observed_store = current_key in stores_by_key
        missing_this_run = (store.get("current_presence") == "MISSING" and store.get("updated_at") == observed_at
                            and prefecture in keys)
        if not observed_store and not missing_this_run:
            continue
        change_at = str(store.get("last_observed_at", "") if observed_store else store.get("updated_at", observed_at))
        previous = latest_change.get(store_id)
        if missing_this_run:
            kind = "MISSING"
            change_key = keys[prefecture]
        elif previous is None:
            kind = "NEW_STORE" if successful_keys else "BASELINE"
            change_key = current_key
        else:
            fields_changed = any(
                previous.get(old_key) != store.get(store_key)
                for old_key, store_key in (("observed_name", "canonical_name"), ("observed_address", "address"),
                                           ("lat", "lat"), ("lng", "lng"), ("prefecture", "prefecture"), ("city", "city"))
            )
            if fields_changed:
                kind = "STORE_UPDATED"
            elif str(previous.get("change_type", "")) == "MISSING" and store.get("current_presence") == "PRESENT":
                kind = "REOPENED"
            else:
                continue
            change_key = current_key if observed_store else keys[prefecture]
        if (store_id, change_at, kind) in existing_change_at_time:
            continue
        state.setdefault("changes", []).append({
            "id": f"{change_key}:{store_id}:{kind}", "store_id": store_id, "observed_at": change_at,
            "change_type": kind, "brand_family": store.get("brand_family", ""),
            "observed_name": store.get("canonical_name", ""), "observed_address": store.get("address", ""),
            "prefecture": prefecture, "city": store.get("city", ""), "lat": store.get("lat"), "lng": store.get("lng"),
            "source": store.get("source", "openpoi"), "source_store_id": store.get("source_store_id"),
            "snapshot_key": change_key,
        })
        existing_change_at_time.add((store_id, change_at, kind))
        recovered_changes += 1

    # Recreate any missing-event rows produced before the interrupted tab writes.
    prior_run_ids = {str(run.get("id", "")) for run in state.get("runs", [])
                     if run.get("source") == "openpoi" and run.get("status") == "succeeded"
                     and run.get("snapshot_key") not in keys.values()}
    events_by_store = {str(event.get("store_id", "")) for event in state.get("events", [])
                       if event.get("status") != "REOPENED"}
    sevens = [store for store in state.get("stores", [])
              if store.get("brand_family") == "SEVEN_ELEVEN" and store.get("current_presence") == "PRESENT"]
    recovered_events = 0
    for store in state.get("stores", []):
        if (store.get("current_presence") != "MISSING" or store.get("updated_at") != observed_at
                or store.get("brand_family") == "SEVEN_ELEVEN" or str(store.get("id")) in events_by_store):
            continue
        previous_observations = [observation for observation in state.get("observations", [])
                                 if str(observation.get("store_id")) == str(store.get("id"))
                                 and str(observation.get("snapshot_run_id", "")) in prior_run_ids]
        if not previous_observations:
            continue
        last_observation = max(previous_observations, key=lambda observation: str(observation.get("observed_at", "")))
        nearest = min(sevens, key=lambda seven: distance_m(store["lat"], store["lng"], seven["lat"], seven["lng"])) if sevens else None
        distance = distance_m(store["lat"], store["lng"], nearest["lat"], nearest["lng"]) if nearest else None
        state.setdefault("events", []).append({
            "id": str(uuid4()), "store_id": store["id"], "detected_at": observed_at,
            "last_seen_at": store.get("last_seen_at"), "status": promotion_status(int(store.get("missing_count", 1)), 2),
            "closure_date": None, "reason": None, "confidence": "LOW",
            "nearest_seven_store_id": nearest["id"] if nearest else None,
            "distance_m": round(distance, 2) if distance is not None else None,
            "within_100m": within_distance(distance, 100), "last_observation_id": last_observation["id"],
            "created_at": observed_at, "updated_at": observed_at,
        })
        recovered_events += 1

    state["_replace_changes"] = True
    state["_sheet_row_counts"] = {**state.get("_sheet_row_counts", {}), "Changes": 0}
    brands = {family: sum(store.get("brand_family") == family and store.get("current_presence") == "PRESENT"
                          for store in state.get("stores", []))
              for family in ("FAMILY_MART", "LAWSON", "SEVEN_ELEVEN")}
    return {"snapshot_key": snapshot_key, "prefectures": len(keys), "observed_at": observed_at,
            "store_count": sum(len(rows) for rows in stores_by_key.values()), "brands": brands,
            "recovered_changes": recovered_changes, "recovered_events": recovered_events}


def build_fixture() -> dict:
    state = new_state()
    for number in (1, 2):
        path = ROOT / "fixtures" / f"snapshot_{number:03}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        apply_snapshot(state, FixtureSource(path), f"fixture-{number:03}", payload["observed_at"])
    evidence = json.loads((ROOT / "fixtures" / "evidence.json").read_text(encoding="utf-8"))
    add_evidence(state, evidence.pop("store_name"), evidence)
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build-fixture")
    sub.add_parser("migrate")
    sub.add_parser("migrate-to-sheets")
    recover = sub.add_parser("recover-sheets-snapshot", help="Recover snapshot tabs after a partial Google Sheets write")
    recover.add_argument("--snapshot-key", required=True)
    recover.add_argument("--started-at", required=True)
    recover.add_argument("--finished-at", required=True)
    recover.add_argument("--source-requests", type=int, required=True)
    recover.add_argument("--raw-family-total", action="append", default=[], metavar="FAMILY=COUNT")
    snap = sub.add_parser("snapshot")
    snap.add_argument("--prefecture", help="都道府県名。OpenPOIの既定値は全国。")
    snap.add_argument("--source", choices=("openpoi", "fixture", "csv"), required=True)
    snap.add_argument("--file")
    snap.add_argument("--snapshot-key", required=True)
    snap.add_argument("--observed-at")
    evidence_parser = sub.add_parser("add-evidence")
    evidence_parser.add_argument("--event-id", required=True)
    evidence_parser.add_argument("--type", dest="evidence_type", choices=("official","web","local_media","manual","source_diff"), required=True)
    evidence_parser.add_argument("--title", required=True)
    evidence_parser.add_argument("--summary", required=True)
    evidence_parser.add_argument("--source-ref")
    evidence_parser.add_argument("--evidence-date")
    evidence_parser.add_argument("--closure-date")
    evidence_parser.add_argument("--supports-closure", action="store_true")
    evidence_parser.add_argument("--confirm", action="store_true")
    status_parser = sub.add_parser("set-status")
    status_parser.add_argument("--event-id", required=True)
    status_parser.add_argument("--status", choices=("MISSING","CLOSED_SUSPECTED","RELOCATED","TEMPORARY_CLOSED","RENAMED","DATA_ISSUE"), required=True)
    status_parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    if args.command == "build-fixture":
        state = build_fixture()
        print(json.dumps({"runs": len(state["runs"]), "events": len(state["events"]), "status": state["events"][0]["status"]}, ensure_ascii=False))
        return
    if args.command == "snapshot":
        args.prefecture = args.prefecture or ("全国" if args.source == "openpoi" else "神奈川県")
        if args.prefecture != "全国" and args.prefecture not in PREFECTURES:
            parser.error("Unknown prefecture")
    if args.command == "snapshot" and args.source in ("fixture", "csv") and not args.file:
        parser.error("--file is required for fixture/csv")
    storage_mode = os.getenv("STORAGE_MODE", "database")
    if storage_mode not in ("database", "sheets"):
        parser.error("STORAGE_MODE must be database or sheets")
    if args.command == "recover-sheets-snapshot":
        if storage_mode != "sheets":
            parser.error("recover-sheets-snapshot requires STORAGE_MODE=sheets")
        raw_family_totals = {}
        for item in args.raw_family_total:
            try:
                family, count = item.split("=", 1)
                raw_family_totals[family] = int(count)
            except (ValueError, TypeError):
                parser.error("--raw-family-total must use FAMILY=COUNT")
        from . import sheets_storage
        state = sheets_storage.load_state()
        summary = recover_sheets_snapshot(state, args.snapshot_key, started_at=args.started_at,
                                          finished_at=args.finished_at, source_requests=args.source_requests,
                                          raw_family_totals=raw_family_totals)
        sheets_storage.save_state(state)
        print(json.dumps(summary, ensure_ascii=False))
        return
    if args.command in ("migrate", "migrate-to-sheets") and not os.getenv("DATABASE_URL"):
        parser.error("DATABASE_URL is required for database migration")
    if storage_mode == "database" and args.command not in ("migrate", "migrate-to-sheets") and not os.getenv("DATABASE_URL"):
        parser.error("DATABASE_URL is required; use build-fixture for offline demo")
    from .db import connect, load_state, save_state
    from .engine import utc_now
    if args.command == "migrate":
        with connect(os.environ["DATABASE_URL"]) as connection:
            with connection.cursor() as cursor:
                cursor.execute((ROOT / "supabase" / "migrations" / "202610040001_initial.sql").read_text(encoding="utf-8"))
        print(json.dumps({"status": "migrated"}))
        return
    if args.command == "migrate-to-sheets":
        from . import sheets_storage
        with connect(os.environ["DATABASE_URL"]) as connection:
            state = load_state(connection)
            with connection.cursor() as cursor:
                cursor.execute("""select o.id::text,o.store_id::text,o.source,o.source_store_id,o.observed_name,o.observed_address,o.lat,o.lng,o.observed_at,r.snapshot_key,s.brand_family,s.prefecture,s.city
                    from store_observations o join snapshot_runs r on r.id=o.snapshot_run_id join stores s on s.id=o.store_id
                    where r.status='succeeded' order by o.store_id,o.observed_at,o.id""")
                history = cursor.fetchall()
        changes = []
        previous = {}
        for observation_id, store_id, source_name, source_store_id, name, address, lat, lng, observed_at, snapshot_key, brand, prefecture, city in history:
            current = (name, address, lat, lng)
            old = previous.get(store_id)
            if old is None or old[0] != current:
                changes.append({"id": f"{snapshot_key}:{store_id}:{'BASELINE' if old is None else 'STORE_UPDATED'}",
                    "store_id": store_id, "observed_at": observed_at.isoformat(), "change_type": "BASELINE" if old is None else "STORE_UPDATED",
                    "brand_family": brand, "observed_name": name, "observed_address": address, "prefecture": prefecture,
                    "city": city, "lat": lat, "lng": lng, "source": source_name, "source_store_id": source_store_id, "snapshot_key": snapshot_key})
            previous[store_id] = (current, observation_id)
        for event in state.get("events", []):
            if event.get("status") == "REOPENED":
                store = next((store for store in state["stores"] if store["id"] == event["store_id"]), None)
                if store:
                    changes.append({"id": f"{event['id']}:REOPENED", "store_id": event["store_id"], "observed_at": event.get("updated_at"), "change_type": "REOPENED", "brand_family": store["brand_family"], "observed_name": store["canonical_name"], "observed_address": store["address"], "prefecture": store["prefecture"], "city": store["city"], "lat": store["lat"], "lng": store["lng"], "source": store["source"], "source_store_id": store.get("source_store_id"), "snapshot_key": ""})
            elif event.get("status") in ("MISSING", "CLOSED_SUSPECTED", "CLOSED_CONFIRMED"):
                store = next((store for store in state["stores"] if store["id"] == event["store_id"]), None)
                if store:
                    changes.append({"id": f"{event['id']}:MISSING", "store_id": event["store_id"], "observed_at": event.get("detected_at"), "change_type": "MISSING", "brand_family": store["brand_family"], "observed_name": store["canonical_name"], "observed_address": store["address"], "prefecture": store["prefecture"], "city": store["city"], "lat": store["lat"], "lng": store["lng"], "source": store["source"], "source_store_id": store.get("source_store_id"), "snapshot_key": ""})
        state["changes"] = sorted(changes, key=lambda row: row["observed_at"] or "")
        state["_previous_stores"] = state["stores"]
        state["_replace_changes"] = True
        state["_sheet_row_counts"] = {"Changes": 0}
        sheets_storage.save_state(state)
        print(json.dumps({"status": "migrated_to_sheets", "stores": len(state["stores"]), "runs": len(state["runs"]), "events": len(state["events"])}, ensure_ascii=False))
        return
    prefectures = PREFECTURES if args.command == "snapshot" and args.prefecture == "全国" else (args.prefecture,) if args.command == "snapshot" else ()
    source = None
    try:
        if args.command == "snapshot" and args.source == "openpoi":
            keys = [f"{args.snapshot_key}:{prefecture}" if args.prefecture == "全国" else args.snapshot_key for prefecture in prefectures]
            if storage_mode == "sheets":
                from . import sheets_storage
                prior = sheets_storage.load_state()
                successful = {run["snapshot_key"] for run in prior["runs"] if run["status"] == "succeeded"}
                if all(key in successful for key in keys):
                    print(json.dumps({"snapshot_key": args.snapshot_key, "status": "already_exists", "prefectures": len(keys)}, ensure_ascii=False))
                    return
            else:
                with connect(os.environ["DATABASE_URL"]) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("select count(*) from snapshot_runs where snapshot_key = any(%s) and status='succeeded'", (keys,))
                        if cursor.fetchone()[0] == len(keys):
                            print(json.dumps({"snapshot_key": args.snapshot_key, "status": "already_exists", "prefectures": len(keys)}, ensure_ascii=False))
                            return
            source = OpenPoiSource(cache_key=args.snapshot_key, cache_dir=ROOT / "data" / "openpoi-cache")
            # Network collection must finish before the database write lock.
            source.prime()
        if storage_mode == "sheets":
            from . import sheets_storage
            state = sheets_storage.load_state()
            if args.command == "snapshot":
                source = source or {"fixture": lambda: FixtureSource(args.file), "csv": lambda: CsvSource(args.file)}[args.source]()
                observed_at = args.observed_at or utc_now()
                runs = []
                for index, prefecture in enumerate(prefectures, 1):
                    runs.append(apply_snapshot(state, source,
                        f"{args.snapshot_key}:{prefecture}" if args.prefecture == "全国" else args.snapshot_key,
                        observed_at, int(os.getenv("MISSING_THRESHOLD", "2")), prefecture))
                    if index % 10 == 0 or index == len(prefectures):
                        print(f"Normalized {index}/{len(prefectures)} prefectures", flush=True)
                run = {"snapshot_key": args.snapshot_key, "prefectures": len(runs),
                       "store_count": sum(r["store_count"] for r in runs), "requests": getattr(source, "requests", None)}
            elif args.command == "add-evidence":
                if args.confirm and not args.supports_closure:
                    parser.error("--confirm requires --supports-closure")
                add_event_evidence(state,args.event_id,{"evidence_type":args.evidence_type,"title":args.title,"summary":args.summary,"source_ref":args.source_ref,"evidence_date":args.evidence_date,"closure_date":args.closure_date,"supports_closure":args.supports_closure,"confirm":args.confirm})
                run={"event_id":args.event_id,"status":"evidence_added"}
            else:
                event=next(e for e in state["events"] if e["id"]==args.event_id)
                if event["status"] == "REOPENED":
                    parser.error("Cannot update reopened event")
                event.update(status=args.status,reason=args.reason,updated_at=utc_now())
                run={"event_id":args.event_id,"status":args.status}
            sheets_storage.save_state(state)
        else:
            with connect(os.environ["DATABASE_URL"]) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("select pg_advisory_xact_lock(481992)")
                state = load_state(connection)
                if args.command == "snapshot":
                    source = source or {"fixture": lambda: FixtureSource(args.file), "csv": lambda: CsvSource(args.file)}[args.source]()
                    observed_at = args.observed_at or utc_now()
                    runs = []
                    for index, prefecture in enumerate(prefectures, 1):
                        runs.append(apply_snapshot(state, source,
                            f"{args.snapshot_key}:{prefecture}" if args.prefecture == "全国" else args.snapshot_key,
                            observed_at, int(os.getenv("MISSING_THRESHOLD", "2")), prefecture))
                        if index % 10 == 0 or index == len(prefectures):
                            print(f"Normalized {index}/{len(prefectures)} prefectures", flush=True)
                    run = {"snapshot_key": args.snapshot_key, "prefectures": len(runs),
                           "store_count": sum(r["store_count"] for r in runs), "requests": getattr(source, "requests", None)}
                elif args.command == "add-evidence":
                    if args.confirm and not args.supports_closure:
                        parser.error("--confirm requires --supports-closure")
                    add_event_evidence(state,args.event_id,{"evidence_type":args.evidence_type,"title":args.title,"summary":args.summary,"source_ref":args.source_ref,"evidence_date":args.evidence_date,"closure_date":args.closure_date,"supports_closure":args.supports_closure,"confirm":args.confirm})
                    run={"event_id":args.event_id,"status":"evidence_added"}
                else:
                    event=next(e for e in state["events"] if e["id"]==args.event_id)
                    if event["status"] == "REOPENED":
                        parser.error("Cannot update reopened event")
                    event.update(status=args.status,reason=args.reason,updated_at=utc_now())
                    run={"event_id":args.event_id,"status":args.status}
                save_state(connection, state)
    except Exception as error:
        if args.command == "snapshot":
            try:
                if storage_mode == "sheets":
                    from . import sheets_storage
                    sheets_storage.record_failure(args.snapshot_key, args.source, args.prefecture, str(error)[:1000])
                    raise RuntimeError("snapshot failed; Sheets run record updated") from error
                with connect(os.environ["DATABASE_URL"]) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("""insert into snapshot_runs(id,snapshot_key,source,prefecture,started_at,finished_at,status,store_count,error_message,metadata)
                          values (%s,%s,%s,%s,now(),now(),'failed',0,%s,'{}')""",
                          (str(uuid4()),f"{args.snapshot_key}:failed:{uuid4()}",args.source,args.prefecture if args.prefecture != "全国" else "全国",str(error)[:1000]))
            except Exception:
                pass
        raise
    print(json.dumps(run, ensure_ascii=False))


if __name__ == "__main__":
    main()
