type ExportValue = string | number | null;

export type WatchExport = {
  id: string;
  spot_id: string;
  layer: ExportValue;
  op: ExportValue;
  a: ExportValue;
  b: ExportValue;
  enabled: boolean | null;
  last_state: ExportValue;
  last_fired_at: ExportValue;
  last_sample_at: ExportValue;
  created_at: ExportValue;
};

export type EventExport = {
  id: string;
  watch_id: ExportValue;
  message: ExportValue;
  status: ExportValue;
  created_at: ExportValue;
  delivered_at: ExportValue;
};

type Row = Record<string, unknown>;

function isPlainRow(value: unknown): value is Row {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

const isId = (value: unknown): value is string => typeof value === 'string' && value.length > 0;
const own = (row: Row, key: string): unknown => Object.hasOwn(row, key) ? row[key] : undefined;

function field(row: Row, key: string): ExportValue {
  const value = own(row, key);
  return typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value)) ? value : null;
}

function enabled(value: unknown): boolean | null {
  if (value === true || value === 1) return true;
  if (value === false || value === 0) return false;
  return null;
}

function watchRow(row: Row, id: string): WatchExport | null {
  const spot_id = own(row, 'spot_id');
  if (!isId(spot_id)) return null;
  return {
    id, spot_id, layer: field(row, 'layer'), op: field(row, 'op'), a: field(row, 'a'), b: field(row, 'b'),
    enabled: enabled(own(row, 'enabled')), last_state: field(row, 'last_state'),
    last_fired_at: field(row, 'last_fired_at'), last_sample_at: field(row, 'last_sample_at'),
    created_at: field(row, 'created_at'),
  };
}

function eventRow(row: Row, id: string): EventExport {
  return {
    id, watch_id: field(row, 'watch_id'), message: field(row, 'message'), status: field(row, 'status'),
    created_at: field(row, 'created_at'), delivered_at: field(row, 'delivered_at'),
  };
}

const compareText = (a: string, b: string): number => a < b ? -1 : a > b ? 1 : 0;

function compareRows(a: WatchExport | EventExport, b: WatchExport | EventExport): number {
  if (a.created_at === null && b.created_at !== null) return 1;
  if (b.created_at === null && a.created_at !== null) return -1;
  // Finite numeric timestamps keep their value in the export but sort as text.
  return compareText(String(a.created_at), String(b.created_at)) || compareText(a.id, b.id);
}

function project<T extends WatchExport | EventExport>(
  owner: string, rows: readonly unknown[], toExport: (row: Row, id: string) => T | null,
): T[] {
  const result: T[] = [];
  let length: number;
  try {
    length = rows.length;
  } catch {
    return result;
  }
  for (let i = 0; i < length; i++) {
    try {
      const row = rows[i];
      if (!isPlainRow(row) || own(row, 'owner') !== owner) continue;
      const id = own(row, 'id');
      if (!isId(id)) continue;
      const projected = toExport(row, id);
      if (projected !== null) result.push(projected);
    } catch {
      // Discard an unreadable row without dropping the owner's other records.
    }
  }
  return result.sort(compareRows);
}

/** Project private export rows without copying unlisted fields. */
export function exportSpotWatches(
  owner: string, watches: readonly unknown[], events: readonly unknown[],
): {watches: WatchExport[]; spot_alert_events: EventExport[]} {
  if (!isId(owner)) return {watches: [], spot_alert_events: []};
  return {watches: project(owner, watches, watchRow), spot_alert_events: project(owner, events, eventRow)};
}
