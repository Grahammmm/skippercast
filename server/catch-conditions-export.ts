import { CONDITIONS_MAX_BYTES, parseConditionsV1, type ConditionsV1 } from './conditions-v1.ts';

export function exportConditions(raw: unknown): ConditionsV1 | null {
  if (raw === null || raw === undefined) return null;
  if (typeof raw === 'string' && new TextEncoder().encode(raw).byteLength <= CONDITIONS_MAX_BYTES) {
    try {
      const parsed = parseConditionsV1(JSON.parse(raw));
      if (parsed.ok) return parsed.value;
    } catch {
      // Invalid stored JSON is unreadable too.
    }
  }
  return { v: 1, missing: 'unreadable' };
}

export function withConditions(row: Record<string, unknown>): Record<string, unknown> {
  const { conditions, ...rest } = row;
  return { ...rest, conditions: exportConditions(conditions) };
}

export function exportEntries(rows: readonly unknown[]): Record<string, unknown>[] {
  const entries: Record<string, unknown>[] = [];
  try {
    const length = rows.length;
    for (let i = 0; i < length; i++) {
      try {
        const row = rows[i];
        if (row === null || typeof row !== 'object' || Array.isArray(row)) continue;
        const proto = Object.getPrototypeOf(row);
        if (proto === Object.prototype || proto === null) {
          entries.push(withConditions(row as Record<string, unknown>));
        }
      } catch {
        // A broken row must not suppress the other entries.
      }
    }
  } catch {
    // A failed read of the input length leaves no rows to enumerate.
  }
  return entries;
}
