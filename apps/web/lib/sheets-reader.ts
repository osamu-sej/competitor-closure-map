import 'server-only';
import { GoogleAuth } from 'google-auth-library';
import type { Store } from './types';

export type SheetRow = Array<string | number | boolean | null>;
export type SheetRun = {
  id: string;
  snapshot_key: string;
  source: string;
  prefecture: string;
  started_at: string;
  finished_at: string;
  status: string;
  store_count: number;
  metadata: Record<string, unknown>;
};

let clientPromise: ReturnType<GoogleAuth['getClient']> | undefined;
const smallTabCache = new Map<string, { expiresAt: number; value: Record<string, unknown>[] }>();
const smallTabInflight = new Map<string, Promise<Record<string, unknown>[]>>();
const spreadsheetId = () => process.env.SHEETS_SPREADSHEET_ID;
const value = (row: SheetRow, index: number, fallback: unknown = ''): unknown => row[index] === undefined || row[index] === '' ? fallback : row[index];
const number = (input: unknown, fallback = 0) => Number.isFinite(Number(input)) ? Number(input) : fallback;
const bool = (input: unknown) => input === true || String(input).toLowerCase() === 'true';

async function client() {
  if (!clientPromise) {
    const raw = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;
    if (!raw) throw new Error('GOOGLE_SERVICE_ACCOUNT_JSON is not configured');
    const auth = new GoogleAuth({ credentials: JSON.parse(raw), scopes: ['https://www.googleapis.com/auth/spreadsheets.readonly'] });
    clientPromise = auth.getClient();
  }
  return clientPromise;
}

/** Read large tabs in bounded pages so a request never constructs a second copy of the whole sheet. */
export async function forEachSheetRow(tab: string, endColumn: string, consume: (row: SheetRow) => void | boolean | Promise<void | boolean>, pageSize = 15000): Promise<void> {
  const id = spreadsheetId();
  if (!id) throw new Error('SHEETS_SPREADSHEET_ID is not configured');
  const api = await client();
  for (let first = 2; ; first += pageSize) {
    const last = first + pageSize - 1;
    const range = `'${tab}'!A${first}:${endColumn}${last}`;
    const response = await api.request<{ values?: SheetRow[] }>({
      url: `https://sheets.googleapis.com/v4/spreadsheets/${encodeURIComponent(id)}/values/${encodeURIComponent(range)}?majorDimension=ROWS`,
      method: 'GET',
    });
    const rows = response.data.values ?? [];
    for (const row of rows) {
      if (row.length && row[0] !== undefined && row[0] !== '' && await consume(row) === false) return;
    }
    if (rows.length < pageSize) return;
  }
}

async function loadSmallTab(tab: string, endColumn: string): Promise<SheetRow[]> {
  const id = spreadsheetId();
  if (!id) throw new Error('SHEETS_SPREADSHEET_ID is not configured');
  const api = await client();
  const range = `'${tab}'!A2:${endColumn}`;
  const response = await api.request<{ values?: SheetRow[] }>({
    url: `https://sheets.googleapis.com/v4/spreadsheets/${encodeURIComponent(id)}/values/${encodeURIComponent(range)}?majorDimension=ROWS`,
    method: 'GET',
  });
  return response.data.values ?? [];
}

export async function getSmallSheetTab(tab: 'SnapshotRuns' | 'ClosureEvents' | 'Evidence'): Promise<Record<string, unknown>[]> {
  const ends = { SnapshotRuns: 'I', ClosureEvents: 'O', Evidence: 'I' };
  const cached = smallTabCache.get(tab);
  if (cached && cached.expiresAt > Date.now()) return cached.value;
  let request = smallTabInflight.get(tab);
  if (!request) {
    request = loadSmallTab(tab, ends[tab]).then(rows => {
      const records = rows.map(row => parseSmallRow(tab, row)).filter(record => record.id || record.store_id || record.snapshot_key);
      smallTabCache.set(tab, { value: records, expiresAt: Date.now() + 15000 });
      return records;
    }).finally(() => { smallTabInflight.delete(tab); });
    smallTabInflight.set(tab, request);
  }
  return request;
}

function parseSmallRow(tab: 'SnapshotRuns' | 'ClosureEvents' | 'Evidence', row: SheetRow): Record<string, unknown> {
  if (tab === 'ClosureEvents') return {
    id: String(value(row, 0)), store_id: String(value(row, 1)), detected_at: String(value(row, 2)),
    last_seen_at: String(value(row, 3)), status: String(value(row, 4)), closure_date: value(row, 5) || null,
    reason: value(row, 6) || null, confidence: String(value(row, 7)), nearest_seven_store_id: value(row, 8) || null,
    nearest_seven_name: value(row, 9) || null, distance_m: value(row, 10) === '' ? null : number(value(row, 10)),
    within_100m: bool(value(row, 11)), last_observation_id: String(value(row, 12)), created_at: String(value(row, 13)), updated_at: String(value(row, 14)),
  };
  if (tab === 'Evidence') return {
    id: String(value(row, 0)), closure_event_id: String(value(row, 1)), evidence_type: String(value(row, 2)),
    title: String(value(row, 3)), source_ref: value(row, 4) || null, evidence_date: value(row, 5) || null,
    summary: String(value(row, 6)), supports_closure: bool(value(row, 7)), created_at: String(value(row, 8)),
  };
  let metadata: Record<string, unknown> = {};
  try {
    const parsed: unknown = JSON.parse(String(value(row, 7, '{}')));
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) metadata = parsed as Record<string, unknown>;
  } catch { /* Malformed metadata should not prevent health reporting. */ }
  return {
    id: String(value(row, 0)), snapshot_key: String(value(row, 0)), source: String(value(row, 1)),
    prefecture: String(value(row, 2)), started_at: String(value(row, 3)), finished_at: String(value(row, 4)),
    status: String(value(row, 5)), store_count: number(value(row, 6)), metadata,
  } satisfies SheetRun;
}

export function storeFromRow(row: SheetRow, includeDates = false): Store & { first_seen_at?: string; last_seen_at?: string } {
  const list = (input: unknown): string[] => {
    try {
      const parsed: unknown = JSON.parse(String(input ?? '[]'));
      return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : [];
    } catch { return []; }
  };
  const store: Store & { first_seen_at?: string; last_seen_at?: string } = {
    id: String(value(row, 0)), brand_family: String(value(row, 1)), canonical_name: String(value(row, 2)),
    address: String(value(row, 3)), prefecture: String(value(row, 4)), city: String(value(row, 5)),
    lat: number(value(row, 6)), lng: number(value(row, 7)), current_presence: String(value(row, 8, 'PRESENT')),
    source: String(value(row, 13, 'openpoi')), source_category: String(value(row, 18)) || null,
    source_business_type: String(value(row, 19)) || null, licenses: list(value(row, 20)), attributions: list(value(row, 21)),
  };
  if (includeDates) {
    store.first_seen_at = String(value(row, 10));
    store.last_seen_at = String(value(row, 11));
    store.observed_at = String(value(row, 11));
  }
  return store;
}

export type SheetChange = {
  id: string;
  store_id: string;
  observed_at: string;
  change_type: string;
  brand_family: string;
  observed_name: string;
  observed_address: string;
  prefecture: string;
  city: string;
  lat: number;
  lng: number;
  source: string;
  source_store_id: unknown;
  snapshot_key: string;
};

export function changeFromRow(row: SheetRow): SheetChange {
  return {
    id: String(value(row, 0)), store_id: String(value(row, 1)), observed_at: String(value(row, 2)),
    change_type: String(value(row, 3)), brand_family: String(value(row, 4)), observed_name: String(value(row, 5)),
    observed_address: String(value(row, 6)), prefecture: String(value(row, 7)), city: String(value(row, 8)),
    lat: number(value(row, 9)), lng: number(value(row, 10)), source: String(value(row, 11)),
    source_store_id: value(row, 12), snapshot_key: String(value(row, 13)),
  };
}
