"""Google Sheets storage adapter for the compact store master and change log."""
from __future__ import annotations

import json
import os
import random
import time
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from uuid import uuid4

from .engine import new_state
from .normalization import normalize_address, normalize_name

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_token: tuple[str, float] | None = None
_last_write_at = 0.0
_MIN_WRITE_INTERVAL_SECONDS = 1.1
_MAX_REQUEST_ATTEMPTS = 7
_WRITE_CHUNK_ROWS = 5000
HEADERS = {
    "Stores": ["store_id", "brand_family", "store_name", "address", "prefecture", "municipality", "latitude", "longitude", "presence", "missing_count", "first_seen_at", "last_seen_at", "last_snapshot_key", "source", "source_store_id", "updated_at", "last_observation_id", "last_observed_at", "source_category", "source_business_type", "licenses_json", "attributions_json"],
    "Changes": ["change_id", "store_id", "observed_at", "change_type", "brand_family", "store_name", "address", "prefecture", "municipality", "latitude", "longitude", "source", "source_store_id", "snapshot_key"],
    "ClosureEvents": ["event_id", "store_id", "detected_at", "last_seen_at", "status", "closure_date", "reason", "confidence", "nearest_seven_store_id", "nearest_seven_name", "distance_m", "within_100m", "last_observation_id", "created_at", "updated_at"],
    "Evidence": ["evidence_id", "event_id", "evidence_type", "title", "source_ref", "evidence_date", "summary", "supports_closure", "created_at"],
    "SnapshotRuns": ["snapshot_key", "source", "prefecture", "started_at", "finished_at", "status", "store_count", "metadata_json", "error_message"],
}


def _auth_headers() -> dict[str, str]:
    global _token
    now = datetime.now(timezone.utc).timestamp()
    if _token and _token[1] > now + 60:
        return {"Authorization": f"Bearer {_token[0]}", "Content-Type": "application/json"}
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except ImportError as error:
        raise RuntimeError("Install google-auth[requests] to use Sheets storage") from error
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required for Sheets storage")
    info = json.loads(raw)
    credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    credentials.refresh(Request())
    _token = (credentials.token, now + 3300)
    return {"Authorization": f"Bearer {credentials.token}", "Content-Type": "application/json"}


def _request(path: str, *, method: str = "GET", body: dict | None = None) -> dict:
    global _last_write_at
    sheet_id = os.getenv("SHEETS_SPREADSHEET_ID", "")
    if not sheet_id:
        raise RuntimeError("SHEETS_SPREADSHEET_ID is required for Sheets storage")
    suffix = path if path.startswith(":") else f"/{path}"
    request = urllib.request.Request(
        f"{SHEETS_API}/{sheet_id}{suffix}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers=_auth_headers(), method=method,
    )
    is_write = method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
    for attempt in range(_MAX_REQUEST_ATTEMPTS):
        if is_write:
            delay = _MIN_WRITE_INTERVAL_SECONDS - (time.monotonic() - _last_write_at)
            if delay > 0:
                time.sleep(delay)
            _last_write_at = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read()
            return json.loads(raw) if raw else {}
        except HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == _MAX_REQUEST_ATTEMPTS - 1:
                raise RuntimeError(f"Google Sheets API request failed: {error}") from error
            retry_after = error.headers.get("Retry-After") if error.headers else None
            try:
                wait = max(0.0, float(retry_after)) if retry_after else min(60.0, 2 ** attempt)
            except ValueError:
                wait = min(60.0, 2 ** attempt)
            time.sleep(wait + random.uniform(0.05, 0.25))
        except (URLError, TimeoutError) as error:
            if attempt == _MAX_REQUEST_ATTEMPTS - 1:
                raise RuntimeError(f"Google Sheets API request failed: {error}") from error
            time.sleep(min(60.0, 2 ** attempt) + random.uniform(0.05, 0.25))


def _read_ranges() -> dict[str, list[list[Any]]]:
    ranges = [f"'{name}'!A2:{chr(64 + len(headers))}" for name, headers in HEADERS.items()]
    query = urllib.parse.urlencode([( "ranges", value) for value in ranges])
    payload = _request(f"values:batchGet?{query}")
    return {name: value.get("values", []) for name, value in zip(HEADERS, payload.get("valueRanges", []))}


def _value(row: list[Any], index: int, default: Any = None) -> Any:
    return row[index] if index < len(row) and row[index] != "" else default


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def _json_list(value: Any) -> list:
    try:
        parsed = json.loads(str(value)) if value not in (None, "") else []
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def load_state() -> dict:
    rows = _read_ranges()
    state = new_state()
    stores_by_id: dict[str, dict] = {}
    for row in rows["Stores"]:
        store_id = str(_value(row, 0, ""))
        if not store_id:
            continue
        store = {
            "id": store_id, "brand_family": str(_value(row, 1, "")),
            "canonical_name": str(_value(row, 2, "")), "normalized_name": normalize_name(str(_value(row, 2, ""))),
            "address": str(_value(row, 3, "")), "normalized_address": normalize_address(str(_value(row, 3, ""))),
            "prefecture": str(_value(row, 4, "")), "city": str(_value(row, 5, "")),
            "lat": _number(_value(row, 6), 0), "lng": _number(_value(row, 7), 0),
            "current_presence": str(_value(row, 8, "PRESENT")), "missing_count": int(_number(_value(row, 9), 0) or 0),
            "first_seen_at": str(_value(row, 10, "")), "last_seen_at": str(_value(row, 11, "")),
            "last_snapshot_key": str(_value(row, 12, "")), "source": str(_value(row, 13, "openpoi")),
            "source_store_id": _value(row, 14), "updated_at": str(_value(row, 15, "")),
            "last_observation_id": str(_value(row, 16, "")), "last_observed_at": str(_value(row, 17, _value(row, 11, ""))),
            "source_category": _value(row, 18), "source_business_type": _value(row, 19),
            "licenses": _json_list(_value(row, 20)), "attributions": _json_list(_value(row, 21)),
        }
        stores_by_id[store_id] = store
        state["stores"].append(store)
    for row in rows["SnapshotRuns"]:
        snapshot_key = str(_value(row, 0, ""))
        if not snapshot_key:
            continue
        try:
            metadata = json.loads(str(_value(row, 7, "{}")))
        except json.JSONDecodeError:
            metadata = {}
        state["runs"].append({"id": snapshot_key, "snapshot_key": snapshot_key, "source": str(_value(row, 1, "openpoi")), "prefecture": str(_value(row, 2, "")), "started_at": str(_value(row, 3, "")), "finished_at": str(_value(row, 4, "")), "status": str(_value(row, 5, "")), "store_count": int(_number(_value(row, 6), 0) or 0), "metadata": metadata, "error_message": _value(row, 8)})
    run_by_key = {run["snapshot_key"]: run for run in state["runs"]}
    # One latest observation per store drives identity matching. Full weekly unchanged rows
    # are intentionally not duplicated in Sheets; Changes records only meaningful changes.
    for store in state["stores"]:
        run_key = store.get("last_snapshot_key")
        run = run_by_key.get(run_key, {})
        observation_id = store.get("last_observation_id") or f"baseline:{store['id']}"
        observation = {"id": observation_id, "store_id": store["id"], "snapshot_run_id": run_key or "", "source": store["source"], "source_store_id": store.get("source_store_id"), "observed_name": store["canonical_name"], "observed_address": store["address"], "lat": store["lat"], "lng": store["lng"], "source_category": store.get("source_category"), "source_business_type": store.get("source_business_type"), "licenses": store.get("licenses", []), "attributions": store.get("attributions", []), "raw_payload": {}, "fetched_at": store.get("last_observed_at"), "observed_at": store.get("last_observed_at") or store["last_seen_at"]}
        state["observations"].append(observation)
    for row in rows["Changes"]:
        store_id = str(_value(row, 1, ""))
        store = stores_by_id.get(store_id, {})
        state.setdefault("changes", []).append({"id": str(_value(row, 0, "")), "store_id": store_id, "observed_at": str(_value(row, 2, "")), "change_type": str(_value(row, 3, "")), "brand_family": str(_value(row, 4, store.get("brand_family", ""))), "observed_name": str(_value(row, 5, store.get("canonical_name", ""))), "observed_address": str(_value(row, 6, store.get("address", ""))), "prefecture": str(_value(row, 7, store.get("prefecture", ""))), "city": str(_value(row, 8, store.get("city", ""))), "lat": _number(_value(row, 9)), "lng": _number(_value(row, 10)), "source": str(_value(row, 11, store.get("source", "openpoi"))), "source_store_id": _value(row, 12), "snapshot_key": str(_value(row, 13, ""))})
    for row in rows["ClosureEvents"]:
        event_id = str(_value(row, 0, ""))
        if not event_id:
            continue
        state["events"].append({"id": event_id, "store_id": str(_value(row, 1, "")), "detected_at": str(_value(row, 2, "")), "last_seen_at": str(_value(row, 3, "")), "status": str(_value(row, 4, "MISSING")), "closure_date": _value(row, 5), "reason": _value(row, 6), "confidence": str(_value(row, 7, "LOW")), "nearest_seven_store_id": _value(row, 8), "nearest_seven_name": _value(row, 9), "distance_m": _number(_value(row, 10)), "within_100m": _bool(_value(row, 11, False)), "last_observation_id": str(_value(row, 12, "")), "created_at": str(_value(row, 13, "")), "updated_at": str(_value(row, 14, ""))})
    for row in rows["Evidence"]:
        evidence_id = str(_value(row, 0, ""))
        if evidence_id:
            state["evidence"].append({"id": evidence_id, "closure_event_id": str(_value(row, 1, "")), "evidence_type": str(_value(row, 2, "")), "title": str(_value(row, 3, "")), "source_ref": _value(row, 4), "evidence_date": _value(row, 5), "summary": str(_value(row, 6, "")), "supports_closure": _bool(_value(row, 7, False)), "created_at": str(_value(row, 8, ""))})
    state["_previous_stores"] = deepcopy(state["stores"])
    state["_previous_changes"] = len(state.get("changes", []))
    state["_sheet_row_counts"] = {name: len(values) for name, values in rows.items()}
    return state


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _rows(name: str, objects: list[dict]) -> list[list[Any]]:
    keys = {
        "Stores": ["id", "brand_family", "canonical_name", "address", "prefecture", "city", "lat", "lng", "current_presence", "missing_count", "first_seen_at", "last_seen_at", "last_snapshot_key", "source", "source_store_id", "updated_at", "last_observation_id", "last_observed_at", "source_category", "source_business_type", "licenses", "attributions"],
        "Changes": ["id", "store_id", "observed_at", "change_type", "brand_family", "observed_name", "observed_address", "prefecture", "city", "lat", "lng", "source", "source_store_id", "snapshot_key"],
        "ClosureEvents": ["id", "store_id", "detected_at", "last_seen_at", "status", "closure_date", "reason", "confidence", "nearest_seven_store_id", "nearest_seven_name", "distance_m", "within_100m", "last_observation_id", "created_at", "updated_at"],
        "Evidence": ["id", "closure_event_id", "evidence_type", "title", "source_ref", "evidence_date", "summary", "supports_closure", "created_at"],
    }[name]
    return [[_cell(obj.get(key)) for key in keys] for obj in objects]


def _values_update(sheet: str, start_row: int, rows: list[list[Any]]) -> None:
    if not rows:
        return
    width = len(rows[0])
    end_col = chr(64 + width)
    _request(f"values/{urllib.parse.quote(sheet)}!A{start_row}:{end_col}{start_row + len(rows) - 1}?valueInputOption=RAW", method="PUT", body={"majorDimension": "ROWS", "values": rows})


def _ensure_capacity(row_counts: dict[str, int]) -> None:
    metadata = _request("?fields=sheets.properties(sheetId,title,gridProperties(rowCount,columnCount))")
    requests = []
    for sheet in metadata.get("sheets", []):
        properties = sheet.get("properties", {})
        title = properties.get("title")
        grid = properties.get("gridProperties", {})
        needed_rows = row_counts.get(title, 0)
        needed_columns = len(HEADERS.get(title, []))
        target = {}
        fields = []
        if needed_rows > grid.get("rowCount", 0):
            target["rowCount"] = needed_rows
            fields.append("gridProperties.rowCount")
        if needed_columns > grid.get("columnCount", 0):
            target["columnCount"] = needed_columns
            fields.append("gridProperties.columnCount")
        if fields:
            requests.append({"updateSheetProperties": {"properties": {"sheetId": properties["sheetId"], "gridProperties": target}, "fields": ",".join(fields)}})
    if requests:
        _request(":batchUpdate", method="POST", body={"requests": requests})


def save_state(state: dict) -> None:
    runs_by_id = {str(run["id"]): run for run in state["runs"]}
    observations: dict[str, dict] = {}
    for observation in state["observations"]:
        old = observations.get(str(observation["store_id"]))
        if old is None or str(observation["observed_at"]) >= str(old["observed_at"]):
            observations[str(observation["store_id"])] = observation
    for store in state["stores"]:
        observation = observations.get(str(store["id"]))
        if observation:
            run = runs_by_id.get(str(observation["snapshot_run_id"]), {})
            store["last_snapshot_key"] = run.get("snapshot_key", str(observation["snapshot_run_id"]))
            store["last_observation_id"] = observation["id"]
            store["last_observed_at"] = observation["observed_at"]
    current_by_id = {str(store["id"]): store for store in state["stores"]}
    previous_by_id = {str(store["id"]): store for store in state.get("_previous_stores", [])}
    existing_change_ids = {str(change.get("id")) for change in state.get("changes", [])}
    snapshot_key = str(state["runs"][-1]["snapshot_key"]) if state["runs"] else ""
    observed_at = str(state["runs"][-1].get("finished_at") or state["runs"][-1].get("started_at") or "") if state["runs"] else ""
    appended: list[dict] = []
    for store_id, store in current_by_id.items():
        previous = previous_by_id.get(store_id)
        if previous is None:
            kind = "BASELINE" if len(state.get("_previous_stores", [])) == 0 else "NEW_STORE"
        elif previous.get("current_presence") != store.get("current_presence"):
            if store.get("current_presence") == "SUPPRESSED":
                kind = "OUT_OF_SCOPE"
            else:
                kind = "REOPENED" if store.get("current_presence") == "PRESENT" else "MISSING"
        elif any(previous.get(key) != store.get(key) for key in ("canonical_name", "address", "lat", "lng", "prefecture", "city")):
            kind = "STORE_UPDATED"
        else:
            continue
        change_id = f"{snapshot_key}:{store_id}:{kind}"
        if change_id not in existing_change_ids:
            appended.append({"id": change_id, "store_id": store_id, "observed_at": store.get("last_observed_at") or observed_at, "change_type": kind, "brand_family": store["brand_family"], "observed_name": store["canonical_name"], "observed_address": store["address"], "prefecture": store["prefecture"], "city": store["city"], "lat": store["lat"], "lng": store["lng"], "source": store["source"], "source_store_id": store.get("source_store_id"), "snapshot_key": snapshot_key})
    if appended:
        state.setdefault("changes", []).extend(appended)
    store_rows = _rows("Stores", state["stores"])
    existing = state.get("_sheet_row_counts", {})
    change_count = len(state.get("changes", [])) if state.get("_replace_changes") else int(existing.get("Changes", 0)) + len(appended)
    _ensure_capacity({"Stores": len(store_rows) + 1, "Changes": change_count + 1, "ClosureEvents": len(state["events"]) + 1, "Evidence": len(state["evidence"]) + 1, "SnapshotRuns": len(state["runs"]) + 1})
    for sheet, headers in HEADERS.items():
        _values_update(sheet, 1, [headers])
    # Fixed-size slices keep every request small and make a retry idempotently rewrite the same rows.
    for offset in range(0, len(store_rows), _WRITE_CHUNK_ROWS):
        _values_update("Stores", offset + 2, store_rows[offset:offset + _WRITE_CHUNK_ROWS])
    change_rows = _rows("Changes", state.get("changes", []))
    if state.get("_replace_changes"):
        change_rows = _rows("Changes", state.get("changes", []))
        for offset in range(0, len(change_rows), _WRITE_CHUNK_ROWS):
            _values_update("Changes", offset + 2, change_rows[offset:offset + _WRITE_CHUNK_ROWS])
    elif appended:
        first = int(state.get("_sheet_row_counts", {}).get("Changes", 0)) + 2
        for offset in range(0, len(appended), _WRITE_CHUNK_ROWS):
            _values_update("Changes", first + offset, _rows("Changes", appended[offset:offset + _WRITE_CHUNK_ROWS]))
    store_names = {str(store["id"]): store["canonical_name"] for store in state["stores"]}
    events = state["events"]
    for event in events:
        nearest_id = event.get("nearest_seven_store_id")
        if nearest_id:
            event["nearest_seven_name"] = store_names.get(str(nearest_id), event.get("nearest_seven_name"))
    event_rows = _rows("ClosureEvents", events)
    for offset in range(0, len(event_rows), _WRITE_CHUNK_ROWS):
        _values_update("ClosureEvents", offset + 2, event_rows[offset:offset + _WRITE_CHUNK_ROWS])
    evidence_rows = _rows("Evidence", state["evidence"])
    for offset in range(0, len(evidence_rows), _WRITE_CHUNK_ROWS):
        _values_update("Evidence", offset + 2, evidence_rows[offset:offset + _WRITE_CHUNK_ROWS])
    runs = state["runs"]
    run_rows = [[run.get("snapshot_key", run["id"]), run.get("source", ""), run.get("prefecture", ""), run.get("started_at", ""), run.get("finished_at", ""), run.get("status", ""), run.get("store_count", 0), _cell(run.get("metadata", {})), _cell(run.get("error_message"))] for run in runs]
    for offset in range(0, len(run_rows), _WRITE_CHUNK_ROWS):
        _values_update("SnapshotRuns", offset + 2, run_rows[offset:offset + _WRITE_CHUNK_ROWS])


def record_failure(snapshot_key: str, source: str, prefecture: str, error_message: str) -> None:
    """Append a failed run so the UI and operator can see collection failures."""
    counts = {name: len(values) for name, values in _read_ranges().items()}
    now = datetime.now(timezone.utc).isoformat()
    failed_key = f"{snapshot_key}:failed:{uuid4()}"
    run = [failed_key, source, prefecture, now, now, "failed", 0, "{}", error_message[:1000]]
    _ensure_capacity({"SnapshotRuns": counts.get("SnapshotRuns", 0) + 2})
    _values_update("SnapshotRuns", counts.get("SnapshotRuns", 0) + 2, [run])
