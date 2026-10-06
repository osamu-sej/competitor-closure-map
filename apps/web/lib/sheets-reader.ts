import 'server-only';
import { GoogleAuth } from 'google-auth-library';
import type { Store } from './types';

type Row = Array<string | number | boolean | null>;
type SheetState = {
  stores: Array<Store & Record<string, unknown>>;
  changes: Array<Record<string, unknown>>;
  events: Array<Record<string, unknown>>;
  evidence: Array<Record<string, unknown>>;
  runs: Array<Record<string, unknown>>;
};

const cache = new Map<boolean, { expiresAt: number; value: SheetState }>();
const inflight = new Map<boolean, Promise<SheetState>>();
const spreadsheetId = () => process.env.SHEETS_SPREADSHEET_ID;
const value = (row: Row, index: number, fallback: unknown = ''): unknown => row[index] === undefined || row[index] === '' ? fallback : row[index];
const number = (input: unknown, fallback = 0) => Number.isFinite(Number(input)) ? Number(input) : fallback;
const bool = (input: unknown) => input === true || String(input).toLowerCase() === 'true';
const records = (rows: Row[], project: (row: Row) => Record<string, unknown>) => rows.map(project).filter(row => row.id || row.store_id || row.snapshot_key);

async function load(includeChanges: boolean): Promise<SheetState> {
  const id = spreadsheetId();
  if (!id) throw new Error('SHEETS_SPREADSHEET_ID is not configured');
  const raw = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;
  if (!raw) throw new Error('GOOGLE_SERVICE_ACCOUNT_JSON is not configured');
  const auth = new GoogleAuth({ credentials: JSON.parse(raw), scopes: ['https://www.googleapis.com/auth/spreadsheets.readonly'] });
  const client = await auth.getClient();
  const ranges = includeChanges
    ? ["'Stores'!A2:R", "'Changes'!A2:N", "'ClosureEvents'!A2:O", "'Evidence'!A2:I", "'SnapshotRuns'!A2:I"]
    : ["'Stores'!A2:R", "'ClosureEvents'!A2:O", "'Evidence'!A2:I", "'SnapshotRuns'!A2:I"];
  const query = new URLSearchParams();
  for (const range of ranges) query.append('ranges', range);
  const response = await client.request<{ valueRanges?: Array<{ values?: Row[] }> }>({
    url: `https://sheets.googleapis.com/v4/spreadsheets/${encodeURIComponent(id)}/values:batchGet?${query.toString()}`,
    method: 'GET',
  });
  const blocks = response.data.valueRanges ?? [];
  const [storeRows = [], changeRows = [], eventRows = [], evidenceRows = [], runRows = []] = includeChanges
    ? blocks.map(block => block.values ?? [])
    : [blocks[0]?.values ?? [], [], blocks[1]?.values ?? [], blocks[2]?.values ?? [], blocks[3]?.values ?? []];
  return {
    stores: records(storeRows, row => ({
      id: String(value(row, 0)), brand_family: String(value(row, 1)), canonical_name: String(value(row, 2)), address: String(value(row, 3)),
      prefecture: String(value(row, 4)), city: String(value(row, 5)), lat: number(value(row, 6)), lng: number(value(row, 7)),
      current_presence: String(value(row, 8, 'PRESENT')), missing_count: number(value(row, 9)), first_seen_at: String(value(row, 10)),
      last_seen_at: String(value(row, 11)), last_snapshot_key: String(value(row, 12)), source: String(value(row, 13)),
      source_store_id: value(row, 14), updated_at: String(value(row, 15)), last_observation_id: String(value(row, 16)),
      last_observed_at: String(value(row, 17, value(row, 11))),
    })) as SheetState['stores'],
    changes: records(changeRows, row => ({ id: String(value(row, 0)), store_id: String(value(row, 1)), observed_at: String(value(row, 2)),
      change_type: String(value(row, 3)), brand_family: String(value(row, 4)), observed_name: String(value(row, 5)), observed_address: String(value(row, 6)),
      prefecture: String(value(row, 7)), city: String(value(row, 8)), lat: number(value(row, 9)), lng: number(value(row, 10)),
      source: String(value(row, 11)), source_store_id: value(row, 12), snapshot_key: String(value(row, 13)),
    })),
    events: records(eventRows, row => ({ id: String(value(row, 0)), store_id: String(value(row, 1)), detected_at: String(value(row, 2)),
      last_seen_at: String(value(row, 3)), status: String(value(row, 4)), closure_date: value(row, 5) || null, reason: value(row, 6) || null,
      confidence: String(value(row, 7)), nearest_seven_store_id: value(row, 8) || null, nearest_seven_name: value(row, 9) || null,
      distance_m: value(row, 10) === '' ? null : number(value(row, 10)), within_100m: bool(value(row, 11)),
      last_observation_id: String(value(row, 12)), created_at: String(value(row, 13)), updated_at: String(value(row, 14)),
    })),
    evidence: records(evidenceRows, row => ({ id: String(value(row, 0)), closure_event_id: String(value(row, 1)), evidence_type: String(value(row, 2)),
      title: String(value(row, 3)), source_ref: value(row, 4) || null, evidence_date: value(row, 5) || null,
      summary: String(value(row, 6)), supports_closure: bool(value(row, 7)), created_at: String(value(row, 8)),
    })),
    runs: records(runRows, row => {
      let metadata: unknown = {};
      try { metadata = JSON.parse(String(value(row, 7, '{}'))); } catch { /* malformed metadata is displayed as empty */ }
      return { id: String(value(row, 0)), snapshot_key: String(value(row, 0)), source: String(value(row, 1)), prefecture: String(value(row, 2)),
        started_at: String(value(row, 3)), finished_at: String(value(row, 4)), status: String(value(row, 5)), store_count: number(value(row, 6)), metadata };
    }),
  };
}

export async function getSheetsState(options: { includeChanges?: boolean } = {}): Promise<SheetState> {
  const includeChanges = options.includeChanges ?? false;
  const cached = cache.get(includeChanges);
  if (cached && cached.expiresAt > Date.now()) return cached.value;
  let request = inflight.get(includeChanges);
  if (!request) {
    request = load(includeChanges).then(value => {
      cache.set(includeChanges, { value, expiresAt: Date.now() + 30_000 });
      return value;
    }).finally(() => { inflight.delete(includeChanges); });
    inflight.set(includeChanges, request);
  }
  return request;
}
