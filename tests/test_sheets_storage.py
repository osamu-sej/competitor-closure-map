import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from collector.__main__ import recover_sheets_snapshot
from collector.engine import new_state
from collector.prefectures import PREFECTURES
from collector import sheets_storage


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"ok":true}'


class SheetsStorageTests(unittest.TestCase):
    def test_closure_notification_markers_round_trip_and_write_only_marker_columns(self):
        event = {
            "id": "event-1", "store_id": "store-1", "detected_at": "2026-10-06T00:00:00Z",
            "last_seen_at": "2026-10-01T00:00:00Z", "status": "CLOSED_SUSPECTED",
            "closure_date": None, "reason": None, "confidence": "LOW",
            "nearest_seven_store_id": "seven-1", "nearest_seven_name": "セブン-イレブン 横浜店",
            "distance_m": 45, "within_100m": True, "last_observation_id": "observation-1",
            "created_at": "2026-10-06T00:00:00Z", "updated_at": "2026-10-06T00:00:00Z",
            "notified_status": "CLOSED_SUSPECTED", "notified_at": "2026-10-09T00:00:00Z",
        }
        row = sheets_storage._rows("ClosureEvents", [event])[0]
        empty = {name: [] for name in sheets_storage.HEADERS}
        empty["ClosureEvents"] = [row]
        with patch.object(sheets_storage, "_read_ranges", return_value=empty):
            restored = sheets_storage.load_state()

        self.assertEqual(len(sheets_storage.HEADERS["ClosureEvents"]), 17)
        self.assertEqual(restored["events"][0]["notified_status"], "CLOSED_SUSPECTED")
        self.assertEqual(restored["events"][0]["notified_at"], "2026-10-09T00:00:00Z")
        self.assertEqual(restored["events"][0]["_sheet_row_number"], 2)

        with patch.object(sheets_storage, "_request") as request:
            sheets_storage.save_notification_markers(restored)

        request.assert_called_once()
        args, kwargs = request.call_args
        self.assertEqual(args[0], "values:batchUpdate?valueInputOption=RAW")
        self.assertEqual(kwargs["method"], "POST")
        self.assertEqual(kwargs["body"]["data"][0]["range"], "'ClosureEvents'!P2:Q2")
        self.assertEqual(kwargs["body"]["data"][0]["values"], [["CLOSED_SUSPECTED", "2026-10-09T00:00:00Z"]])

    def test_lawson_source_metadata_round_trips_in_store_sheet(self):
        store = {
            "id": "lawson-1", "brand_family": "LAWSON", "canonical_name": "ローソン 横浜店",
            "address": "神奈川県横浜市中区1", "prefecture": "神奈川県", "city": "横浜市中区",
            "lat": 35.4, "lng": 139.4, "current_presence": "PRESENT", "missing_count": 0,
            "first_seen_at": "2026-10-07T00:00:00Z", "last_seen_at": "2026-10-07T00:00:00Z",
            "source": "overture", "source_category": "convenience_store",
            "source_business_type": None, "licenses": ["CC-BY-4.0"],
            "attributions": ["Overture Maps Foundation"],
        }
        row = sheets_storage._rows("Stores", [store])[0]
        empty = {name: [] for name in sheets_storage.HEADERS}
        empty["Stores"] = [row]
        with patch.object(sheets_storage, "_read_ranges", return_value=empty):
            restored = sheets_storage.load_state()

        self.assertEqual(len(sheets_storage.HEADERS["Stores"]), 22)
        self.assertEqual(row[18], "convenience_store")
        self.assertEqual(json.loads(row[20]), ["CC-BY-4.0"])
        self.assertEqual(restored["stores"][0]["source_category"], "convenience_store")
        self.assertEqual(restored["observations"][0]["licenses"], ["CC-BY-4.0"])
        self.assertEqual(restored["observations"][0]["attributions"], ["Overture Maps Foundation"])

    def test_request_retries_rate_limit_and_returns_response(self):
        rate_limited = HTTPError("https://sheets.example", 429, "Too Many Requests", {"Retry-After": "0"}, io.BytesIO())
        with patch.dict("os.environ", {"SHEETS_SPREADSHEET_ID": "sheet-id"}), \
             patch.object(sheets_storage, "_auth_headers", return_value={}), \
             patch.object(sheets_storage.urllib.request, "urlopen", side_effect=[rate_limited, FakeResponse()]) as urlopen, \
             patch.object(sheets_storage.time, "sleep") as sleep, \
             patch.object(sheets_storage.random, "uniform", return_value=0), \
             patch.object(sheets_storage, "_last_write_at", 0):
            result = sheets_storage._request("values/Stores!A2:R2", method="PUT", body={"values": [["x"]]})

        self.assertEqual(result, {"ok": True})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called()

    def test_recovery_restores_prefecture_runs_and_unwritten_new_store_changes(self):
        state = new_state()
        state["changes"] = []
        snapshot_key = "sheets-cutover-test"
        observed_at = "2026-10-06T12:34:49.295918+00:00"
        state["runs"].append({"id": "previous:神奈川県", "snapshot_key": "previous:神奈川県",
                              "source": "openpoi", "prefecture": "神奈川県",
                              "started_at": "2026-10-04T00:00:00+00:00",
                              "finished_at": "2026-10-04T00:00:01+00:00", "status": "succeeded",
                              "store_count": 0, "metadata": {}})
        for index, prefecture in enumerate(PREFECTURES):
            store_id = f"store-{index}"
            state["stores"].append({
                "id": store_id, "brand_family": "FAMILY_MART", "canonical_name": f"ファミリーマート{index}",
                "normalized_name": f"ファミリーマート{index}", "address": f"{prefecture}住所{index}",
                "normalized_address": f"{prefecture}住所{index}", "prefecture": prefecture, "city": "市",
                "lat": 35.0, "lng": 139.0, "current_presence": "PRESENT", "missing_count": 0,
                "first_seen_at": observed_at, "last_seen_at": observed_at,
                "last_snapshot_key": f"{snapshot_key}:{prefecture}", "source": "openpoi",
                "source_store_id": None, "updated_at": observed_at, "last_observed_at": observed_at,
                "last_observation_id": f"observation-{index}",
            })
        first_store = state["stores"][0]
        state["changes"].append({
            "id": f"{snapshot_key}:沖縄県:{first_store['id']}:NEW_STORE",
            "store_id": first_store["id"], "observed_at": observed_at, "change_type": "NEW_STORE",
            "brand_family": "FAMILY_MART", "observed_name": first_store["canonical_name"],
            "observed_address": first_store["address"], "prefecture": first_store["prefecture"],
            "city": first_store["city"], "lat": first_store["lat"], "lng": first_store["lng"],
            "source": "openpoi", "source_store_id": None, "snapshot_key": f"{snapshot_key}:沖縄県",
        })

        summary = recover_sheets_snapshot(
            state, snapshot_key, started_at="2026-10-06T12:22:19+00:00",
            finished_at="2026-10-06T12:36:07+00:00", source_requests=2067,
            raw_family_totals={"FAMILY_MART": 18256, "LAWSON": 26942, "SEVEN_ELEVEN": 23456},
        )

        self.assertEqual(summary["prefectures"], 47)
        self.assertEqual(summary["store_count"], 47)
        self.assertEqual(len([run for run in state["runs"] if run["snapshot_key"].startswith(snapshot_key + ":")]), 47)
        self.assertEqual(len(state["changes"]), 47)
        self.assertTrue(all(run["status"] == "succeeded" for run in state["runs"]))
        recovered_runs = [run for run in state["runs"] if run["snapshot_key"].startswith(snapshot_key + ":")]
        self.assertTrue(all(run["metadata"]["recovered_after_partial_write"] for run in recovered_runs))
        self.assertTrue(all(change["change_type"] == "NEW_STORE" for change in state["changes"]))
        self.assertEqual(state["changes"][0]["snapshot_key"], first_store["last_snapshot_key"])


if __name__ == "__main__":
    unittest.main()
