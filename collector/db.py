"""Transactional PostgreSQL projection of the snapshot state."""
import json
import base64
import zlib

from .engine import new_state


def connect(url: str):
    import psycopg
    return psycopg.connect(url)


def load_state(connection) -> dict:
    with connection.cursor() as cursor:
        cursor.execute("select state from app_state where singleton = true")
        row = cursor.fetchone()
    if not row:
        return new_state()
    value = row[0]
    if value.get("encoding") == "zlib+base64":
        return json.loads(zlib.decompress(base64.b64decode(value["payload"])))
    return value


def save_state(connection, state: dict) -> None:
    """All projections and the checkpoint commit in one transaction."""
    with connection.transaction():
        with connection.cursor() as cur:
            cur.execute("select pg_advisory_xact_lock(481992)")
            cur.execute("select id from snapshot_runs")
            existing_run_ids = {str(row[0]) for row in cur.fetchall()}
            cur.executemany("""insert into snapshot_runs(id,snapshot_key,source,prefecture,started_at,finished_at,status,store_count,metadata)
                  values (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) on conflict(id) do update set finished_at=excluded.finished_at,status=excluded.status,store_count=excluded.store_count,metadata=excluded.metadata""",
                  ((r["id"],r["snapshot_key"],r["source"],r["prefecture"],r["started_at"],r["finished_at"],r["status"],r["store_count"],json.dumps(r["metadata"])) for r in state["runs"]))
            cur.executemany("""insert into stores(id,brand_family,canonical_name,normalized_name,address,normalized_address,prefecture,city,lat,lng,source,source_store_id,first_seen_at,last_seen_at,current_presence,missing_count,created_at,updated_at)
                  values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                  on conflict(id) do update set canonical_name=excluded.canonical_name,normalized_name=excluded.normalized_name,address=excluded.address,normalized_address=excluded.normalized_address,city=excluded.city,lat=excluded.lat,lng=excluded.lng,source=excluded.source,source_store_id=excluded.source_store_id,last_seen_at=excluded.last_seen_at,current_presence=excluded.current_presence,missing_count=excluded.missing_count,updated_at=excluded.updated_at""",
                  (tuple(s[k] for k in ("id","brand_family","canonical_name","normalized_name","address","normalized_address","prefecture","city","lat","lng","source","source_store_id","first_seen_at","last_seen_at","current_presence","missing_count","created_at","updated_at")) for s in state["stores"]))
            cur.executemany("""insert into store_observations(id,snapshot_run_id,store_id,source,source_store_id,observed_name,observed_address,lat,lng,source_category,source_business_type,licenses,attributions,raw_payload,fetched_at,observed_at)
                  values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s) on conflict(id) do nothing""",
                  (tuple(json.dumps(o[k]) if k in ("licenses","attributions","raw_payload") else o[k] for k in ("id","snapshot_run_id","store_id","source","source_store_id","observed_name","observed_address","lat","lng","source_category","source_business_type","licenses","attributions","raw_payload","fetched_at","observed_at")) for o in state["observations"] if o["snapshot_run_id"] not in existing_run_ids))
            cur.executemany("""insert into closure_events(id,store_id,detected_at,last_seen_at,status,closure_date,reason,confidence,nearest_seven_store_id,distance_m,within_100m,last_observation_id,created_at,updated_at)
                  values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                  on conflict(id) do update set status=excluded.status,closure_date=excluded.closure_date,reason=excluded.reason,confidence=excluded.confidence,nearest_seven_store_id=excluded.nearest_seven_store_id,distance_m=excluded.distance_m,within_100m=excluded.within_100m,updated_at=excluded.updated_at""",
                  (tuple(e[k] for k in ("id","store_id","detected_at","last_seen_at","status","closure_date","reason","confidence","nearest_seven_store_id","distance_m","within_100m","last_observation_id","created_at","updated_at")) for e in state["events"]))
            cur.executemany("""insert into event_evidence(id,closure_event_id,evidence_type,title,source_ref,evidence_date,summary,supports_closure,created_at)
                  values (%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict(id) do nothing""",
                  (tuple(e[k] for k in ("id","closure_event_id","evidence_type","title","source_ref","evidence_date","summary","supports_closure","created_at")) for e in state["evidence"]))
            # The PostgreSQL projection is authoritative for geography distances.
            for e in state["events"]:
                if e["status"] != "REOPENED":
                    cur.execute("select refresh_event_nearest(%s)", (e["id"],))
                    cur.execute("select nearest_seven_store_id,distance_m,within_100m from closure_events where id=%s", (e["id"],))
                    nearest_id, distance, within = cur.fetchone()
                    e.update(nearest_seven_store_id=str(nearest_id) if nearest_id else None, distance_m=float(distance) if distance is not None else None, within_100m=within)
            # The relational observations table retains full history; the JSON
            # checkpoint needs only the latest observation per store for diffs.
            latest = {}
            for observation in state["observations"]:
                old = latest.get(observation["store_id"])
                if old is None or observation["observed_at"] >= old["observed_at"]:
                    latest[observation["store_id"]] = observation
            checkpoint = {**state, "observations": [
                {key: observation[key] for key in ("id", "store_id", "snapshot_run_id", "observed_at")}
                for observation in latest.values()
            ]}
            compressed = base64.b64encode(zlib.compress(json.dumps(checkpoint, ensure_ascii=False).encode("utf-8"), level=6)).decode("ascii")
            packed = {"encoding": "zlib+base64", "payload": compressed}
            cur.execute("insert into app_state(singleton,state) values (true,%s::jsonb) on conflict(singleton) do update set state=excluded.state", (json.dumps(packed),))
