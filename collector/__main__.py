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
    if not os.getenv("DATABASE_URL"):
        parser.error("DATABASE_URL is required; use build-fixture for offline demo")
    from .db import connect, load_state, save_state
    from .engine import utc_now
    if args.command == "migrate":
        with connect(os.environ["DATABASE_URL"]) as connection:
            with connection.cursor() as cursor:
                cursor.execute((ROOT / "supabase" / "migrations" / "202610040001_initial.sql").read_text(encoding="utf-8"))
        print(json.dumps({"status": "migrated"}))
        return
    try:
        with connect(os.environ["DATABASE_URL"]) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select pg_advisory_xact_lock(481992)")
            state = load_state(connection)
            if args.command == "snapshot":
                source = {"openpoi": lambda: OpenPoiSource(), "fixture": lambda: FixtureSource(args.file), "csv": lambda: CsvSource(args.file)}[args.source]()
                prefectures = PREFECTURES if args.prefecture == "全国" else (args.prefecture,)
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
