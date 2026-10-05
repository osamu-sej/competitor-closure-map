import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from .engine import add_evidence, add_event_evidence, apply_snapshot, new_state
from .sources.csv_source import CsvSource
from .sources.fixture import FixtureSource
from .sources.openpoi import OpenPoiSource
from .prefectures import PREFECTURES


ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "fixture-state.json"


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
